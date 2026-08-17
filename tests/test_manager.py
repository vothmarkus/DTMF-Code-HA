"""Tests for collecting DTMF input and applying profile policies."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from custom_components.dtmf_code import manager as manager_module
from custom_components.dtmf_code.const import (
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
    NUMBER_MODE_ALLOW_LIST,
    SUBENTRY_TYPE_CODE,
)
from custom_components.dtmf_code.manager import DTMFCodeManager

INSTANCE_ID = "12345678-1234-5678-9234-567812345678"


class FakeBus:
    """Minimal event-bus stand-in."""

    def async_listen(self, _event_type, _listener):
        return lambda: None


class FakeHass:
    """Run executor work inline while preserving the async boundary."""

    def __init__(self) -> None:
        self.bus = FakeBus()

    async def async_add_executor_job(self, target, *args):
        await asyncio.sleep(0)
        return target(*args)


class FakeEntry:
    """Provide only the ConfigEntry surface used by the manager."""

    def __init__(self, profiles, *, max_attempts=5, lockout_seconds=60) -> None:
        self.entry_id = "entry-1"
        self.data = {
            CONF_INSTANCE_ID: INSTANCE_ID,
            CONF_HASH_SALT: "unused-in-manager-tests",
            CONF_SUBMIT_KEY: "#",
            CONF_CLEAR_KEY: "*",
            CONF_INPUT_TIMEOUT: 10,
            CONF_MAX_ATTEMPTS: max_attempts,
            CONF_LOCKOUT_SECONDS: lockout_seconds,
        }
        self.subentries = profiles
        self.tasks: list[asyncio.Task] = []

    def get_subentries_of_type(self, subentry_type):
        assert subentry_type == SUBENTRY_TYPE_CODE
        return self.subentries

    def async_create_task(self, _hass, coroutine, _name):
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task


def profile(
    profile_id: str,
    title: str,
    code: str,
    *,
    number_mode: str = NUMBER_MODE_ALLOW_LIST,
    numbers: list[str] | None = None,
    directions: list[str] | None = None,
):
    """Build a small ConfigSubentry-compatible object."""
    return SimpleNamespace(
        subentry_id=profile_id,
        unique_id=profile_id,
        title=title,
        data={
            CONF_CODE_HASH: code,
            CONF_NUMBER_MODE: number_mode,
            CONF_ALLOWED_NUMBERS: numbers or [],
            CONF_CALL_DIRECTIONS: directions or ["incoming"],
        },
    )


def raw_event(
    digit: str,
    *,
    call_id: str = "call-1",
    direction: str = "incoming",
    remote_number: str = "+49170123456",
):
    """Build a raw Reolink event without an access-code buffer."""
    return SimpleNamespace(
        data={
            "digit": digit,
            "duration_ms": 120,
            "call_direction": direction,
            "remote_number": remote_number,
            "call_id": call_id,
            "received_at": "2026-08-17T10:30:01Z",
            "instance_id": INSTANCE_ID,
        }
    )


async def submit(
    manager: DTMFCodeManager,
    entry: FakeEntry,
    digits: str,
    **event_kwargs: Any,
) -> None:
    """Submit digits followed by the configured confirmation key."""
    for digit in f"{digits}#":
        manager.async_handle_event(raw_event(digit, **event_kwargs))
    if entry.tasks:
        await asyncio.gather(*entry.tasks)
        entry.tasks.clear()


def build_manager(monkeypatch, profiles, **entry_kwargs):
    """Build a manager and record all dispatcher messages."""
    dispatched: list[tuple[Any, ...]] = []
    monkeypatch.setattr(manager_module, "hash_code", lambda code, _salt: code)
    monkeypatch.setattr(
        manager_module,
        "async_dispatcher_send",
        lambda _hass, *args: dispatched.append(args),
    )
    monkeypatch.setattr(manager_module, "async_call_later", lambda *_args: lambda: None)
    entry = FakeEntry(profiles, **entry_kwargs)
    return DTMFCodeManager(FakeHass(), entry), entry, dispatched


def test_multiple_profiles_apply_number_and_direction_policy(monkeypatch):
    async def run_test() -> None:
        manager, entry, dispatched = build_manager(
            monkeypatch,
            [
                profile(
                    "family",
                    "Familie",
                    "1234",
                    numbers=["+49170123456"],
                    directions=["incoming"],
                ),
                profile(
                    "service",
                    "Service",
                    "5678",
                    number_mode=NUMBER_MODE_ALLOW_ALL,
                    directions=["outgoing"],
                ),
            ],
        )

        await submit(manager, entry, "1234")
        assert dispatched[-1][0].endswith("_code_family")
        assert dispatched[-1][1]["profile_name"] == "Familie"
        assert "code" not in dispatched[-1][1]

        await submit(manager, entry, "1234", remote_number="+49170999999")
        assert dispatched[-1][0].endswith("_security")
        assert dispatched[-1][1] == EVENT_REJECTED

        await submit(manager, entry, "5678", direction="outgoing")
        assert dispatched[-1][0].endswith("_code_service")

    asyncio.run(run_test())


def test_digits_never_span_two_sip_calls(monkeypatch):
    async def run_test() -> None:
        manager, entry, dispatched = build_manager(
            monkeypatch,
            [profile("family", "Familie", "1234", numbers=["+49170123456"])],
        )

        manager.async_handle_event(raw_event("1", call_id="call-a"))
        manager.async_handle_event(raw_event("2", call_id="call-a"))
        await submit(manager, entry, "34", call_id="call-b")
        assert dispatched[-1][1] == EVENT_REJECTED

        await submit(manager, entry, "1234", call_id="call-b")
        assert dispatched[-1][0].endswith("_code_family")

    asyncio.run(run_test())


def test_failed_attempts_lock_out_only_that_remote(monkeypatch):
    async def run_test() -> None:
        manager, entry, dispatched = build_manager(
            monkeypatch,
            [profile("family", "Familie", "1234", numbers=["+49170123456"])],
            max_attempts=2,
            lockout_seconds=30,
        )

        await submit(manager, entry, "9999")
        await submit(manager, entry, "9999")
        assert [message[1] for message in dispatched] == [
            EVENT_REJECTED,
            EVENT_LOCKED_OUT,
        ]
        assert dispatched[-1][2]["lockout_seconds"] == 30

        await submit(manager, entry, "1234")
        assert len(dispatched) == 2

        await submit(manager, entry, "1234", remote_number="+49170999999")
        assert dispatched[-1][1] == EVENT_REJECTED

    asyncio.run(run_test())


def test_missing_call_id_is_ignored(monkeypatch):
    manager, entry, dispatched = build_manager(
        monkeypatch,
        [profile("family", "Familie", "1234", numbers=["+49170123456"])],
    )
    event = raw_event("1")
    event.data.pop("call_id")

    manager.async_handle_event(event)

    assert not entry.tasks
    assert not dispatched
