"""Runtime event collector and code validator."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later

from .const import (
    CALL_DIRECTIONS,
    CODE_DIGITS,
    CODE_MAX_LENGTH,
    CONF_ALLOWED_NUMBERS,
    CONF_CALL_DIRECTIONS,
    CONF_CLEAR_KEY,
    CONF_CODE_HASH,
    CONF_HASH_SALT,
    CONF_INPUT_TIMEOUT,
    CONF_INSTANCE_ID,
    CONF_LOCKOUT_SECONDS,
    CONF_MAX_ATTEMPTS,
    CONF_NUMBER_MODE,
    CONF_SUBMIT_KEY,
    EVENT_LOCKED_OUT,
    EVENT_REJECTED,
    NUMBER_MODE_ALLOW_ALL,
    SOURCE_EVENT,
    SUBENTRY_TYPE_CODE,
    VALID_DTMF_KEYS,
    code_signal,
    security_signal,
)
from .security import hash_code, hashes_equal, normalize_remote_number

_LOGGER = logging.getLogger(__name__)
_MAX_TRACKED_REMOTES = 128


@dataclass(frozen=True, slots=True)
class CodeProfile:
    """One configured access code and its authorization policy."""

    profile_id: str
    title: str
    code_hash: str
    number_mode: str
    allowed_numbers: frozenset[str]
    call_directions: frozenset[str]

    @classmethod
    def from_subentry(cls, subentry: ConfigSubentry) -> CodeProfile:
        """Create a runtime profile from a Home Assistant subentry."""
        data = subentry.data
        return cls(
            profile_id=subentry.unique_id or subentry.subentry_id,
            title=subentry.title,
            code_hash=str(data[CONF_CODE_HASH]),
            number_mode=str(data[CONF_NUMBER_MODE]),
            allowed_numbers=frozenset(str(value) for value in data[CONF_ALLOWED_NUMBERS]),
            call_directions=frozenset(str(value) for value in data[CONF_CALL_DIRECTIONS]),
        )

    def authorizes(self, metadata: DTMFMetadata) -> bool:
        """Return whether the call metadata may use this profile."""
        if metadata.call_direction not in self.call_directions:
            return False
        return (
            self.number_mode == NUMBER_MODE_ALLOW_ALL
            or metadata.remote_number in self.allowed_numbers
        )


@dataclass(frozen=True, slots=True)
class DTMFMetadata:
    """Validated non-secret metadata attached to every raw DTMF event."""

    instance_id: str
    call_id: str
    call_direction: str
    remote_number: str
    received_at: str

    @property
    def session_key(self) -> tuple[str, str, str]:
        """Return the key that prevents input spanning multiple calls."""
        return (self.call_id, self.call_direction, self.remote_number)

    @property
    def attempt_key(self) -> tuple[str, str]:
        """Return the key used for per-remote attempt limiting."""
        return (self.call_direction, self.remote_number)

    def event_data(self) -> dict[str, str]:
        """Return the safe metadata exposed on result event entities."""
        return {
            "instance_id": self.instance_id,
            "call_id": self.call_id,
            "call_direction": self.call_direction,
            "remote_number": self.remote_number,
            "received_at": self.received_at,
        }


@dataclass(slots=True)
class AttemptState:
    """Failed-attempt and lockout state for one remote party."""

    failures: int = 0
    locked_until: float = 0.0
    last_seen: float = 0.0


class DTMFCodeManager:
    """Collect raw key events and publish only validated result events."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.instance_id = str(entry.data[CONF_INSTANCE_ID])
        self.hash_salt = str(entry.data[CONF_HASH_SALT])
        self.submit_key = str(entry.data[CONF_SUBMIT_KEY])
        self.clear_key = str(entry.data[CONF_CLEAR_KEY])
        self.input_timeout = int(entry.data[CONF_INPUT_TIMEOUT])
        self.max_attempts = int(entry.data[CONF_MAX_ATTEMPTS])
        self.lockout_seconds = int(entry.data[CONF_LOCKOUT_SECONDS])
        self.profiles = tuple(
            CodeProfile.from_subentry(subentry)
            for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_CODE)
        )

        self._buffer: list[str] = []
        self._invalid_sequence = False
        self._session_key: tuple[str, str, str] | None = None
        self._timeout_cancel: CALLBACK_TYPE | None = None
        self._event_unsubscribe: CALLBACK_TYPE | None = None
        self._attempts: dict[tuple[str, str], AttemptState] = {}

    @callback
    def start(self) -> None:
        """Start listening for the raw Reolink integration event."""
        if self._event_unsubscribe is None:
            self._event_unsubscribe = self.hass.bus.async_listen(
                SOURCE_EVENT, self.async_handle_event
            )

    @callback
    def stop(self) -> None:
        """Stop listeners and discard transient input."""
        if self._event_unsubscribe is not None:
            self._event_unsubscribe()
            self._event_unsubscribe = None
        self._reset_input()
        self._attempts.clear()

    @callback
    def async_handle_event(self, event: Event) -> None:
        """Consume one raw DTMF key event without exposing the current buffer."""
        parsed = self._parse_event(event.data)
        if parsed is None:
            return
        digit, metadata = parsed
        now = time.monotonic()
        attempt = self._attempts.get(metadata.attempt_key)
        if attempt is not None and attempt.locked_until > now:
            self._reset_input()
            return

        if digit == self.clear_key:
            self._reset_input()
            return

        if self._session_key is not None and self._session_key != metadata.session_key:
            self._reset_input()
        self._session_key = metadata.session_key

        if digit == self.submit_key:
            if not self._buffer and not self._invalid_sequence:
                self._reset_input()
                return
            entered = "".join(self._buffer)
            invalid = self._invalid_sequence
            self._reset_input()
            self.entry.async_create_task(
                self.hass,
                self._async_verify(entered, invalid, metadata),
                "validate DTMF code",
            )
            return

        if digit not in CODE_DIGITS:
            self._invalid_sequence = True
        elif len(self._buffer) < CODE_MAX_LENGTH:
            self._buffer.append(digit)
        else:
            self._invalid_sequence = True
        self._schedule_timeout()

    def _parse_event(self, data: Mapping[str, Any]) -> tuple[str, DTMFMetadata] | None:
        """Validate the deliberately small raw event contract."""
        if data.get("instance_id") != self.instance_id:
            return None
        digit = data.get("digit")
        direction = data.get("call_direction")
        remote_number = data.get("remote_number")
        call_id = data.get("call_id")
        received_at = data.get("received_at")
        if (
            not isinstance(digit, str)
            or digit not in VALID_DTMF_KEYS
            or not isinstance(direction, str)
            or direction not in CALL_DIRECTIONS
            or not isinstance(remote_number, str)
            or not isinstance(call_id, str)
            or not call_id
            or len(call_id) > 256
            or not isinstance(received_at, str)
        ):
            _LOGGER.debug("Ignored malformed Reolink SIP Gateway DTMF event")
            return None
        normalized_remote = normalize_remote_number(remote_number)
        if not normalized_remote:
            _LOGGER.debug("Ignored DTMF event without a remote party")
            return None
        return (
            digit,
            DTMFMetadata(
                instance_id=self.instance_id,
                call_id=call_id,
                call_direction=direction,
                remote_number=normalized_remote,
                received_at=received_at,
            ),
        )

    @callback
    def _schedule_timeout(self) -> None:
        if self._timeout_cancel is not None:
            self._timeout_cancel()
        self._timeout_cancel = async_call_later(
            self.hass, self.input_timeout, self._async_input_timeout
        )

    @callback
    def _async_input_timeout(self, _now: datetime) -> None:
        self._timeout_cancel = None
        self._reset_input()

    @callback
    def _reset_input(self) -> None:
        if self._timeout_cancel is not None:
            self._timeout_cancel()
            self._timeout_cancel = None
        self._buffer.clear()
        self._invalid_sequence = False
        self._session_key = None

    async def _async_verify(
        self, entered: str, invalid_sequence: bool, metadata: DTMFMetadata
    ) -> None:
        """Derive the entered code off-loop, then apply profile policy."""
        submitted_hash: str | None = None
        if not invalid_sequence:
            submitted_hash = await self.hass.async_add_executor_job(
                hash_code, entered, self.hash_salt
            )

        matched: CodeProfile | None = None
        if submitted_hash is not None:
            for profile in self.profiles:
                if hashes_equal(submitted_hash, profile.code_hash):
                    matched = profile
                    break

        if matched is not None and matched.authorizes(metadata):
            self._attempts.pop(metadata.attempt_key, None)
            event_data: dict[str, str] = metadata.event_data()
            event_data.update({"profile_id": matched.profile_id, "profile_name": matched.title})
            async_dispatcher_send(
                self.hass,
                code_signal(self.entry.entry_id, matched.profile_id),
                event_data,
            )
            return

        self._record_failure(metadata)

    @callback
    def _record_failure(self, metadata: DTMFMetadata) -> None:
        now = time.monotonic()
        state = self._attempts.setdefault(metadata.attempt_key, AttemptState())
        state.failures += 1
        state.last_seen = now
        event_data: dict[str, str | int] = metadata.event_data()

        if state.failures >= self.max_attempts:
            state.failures = 0
            state.locked_until = now + self.lockout_seconds
            event_data["lockout_seconds"] = self.lockout_seconds
            async_dispatcher_send(
                self.hass,
                security_signal(self.entry.entry_id),
                EVENT_LOCKED_OUT,
                event_data,
            )
        else:
            async_dispatcher_send(
                self.hass,
                security_signal(self.entry.entry_id),
                EVENT_REJECTED,
                event_data,
            )
        self._prune_attempts()

    def _prune_attempts(self) -> None:
        """Bound untrusted remote-number cardinality."""
        while len(self._attempts) > _MAX_TRACKED_REMOTES:
            oldest = min(self._attempts, key=lambda key: self._attempts[key].last_seen)
            self._attempts.pop(oldest, None)
