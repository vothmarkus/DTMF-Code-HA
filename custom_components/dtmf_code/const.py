"""Constants for the DTMF Code integration."""

from __future__ import annotations

DOMAIN = "dtmf_code"
NAME = "DTMF Code"

REOLINK_DOMAIN = "reolink_sip_gateway"
SOURCE_EVENT = "reolink_sip_gateway_dtmf"
SUBENTRY_TYPE_CODE = "code"

CONF_GATEWAY_ENTRY_ID = "gateway_entry_id"
CONF_INSTANCE_ID = "instance_id"
CONF_HASH_SALT = "hash_salt"
CONF_SUBMIT_KEY = "submit_key"
CONF_CLEAR_KEY = "clear_key"
CONF_INPUT_TIMEOUT = "input_timeout"
CONF_MAX_ATTEMPTS = "max_attempts"
CONF_LOCKOUT_SECONDS = "lockout_seconds"

CONF_NAME = "name"
CONF_CODE = "code"
CONF_CODE_CONFIRM = "code_confirm"
CONF_CODE_HASH = "code_hash"
CONF_NUMBER_MODE = "number_mode"
CONF_ALLOWED_NUMBERS = "allowed_numbers"
CONF_CALL_DIRECTIONS = "call_directions"

NUMBER_MODE_ALLOW_ALL = "allow_all"
NUMBER_MODE_ALLOW_LIST = "allow_list"
NUMBER_MODES = (NUMBER_MODE_ALLOW_ALL, NUMBER_MODE_ALLOW_LIST)

CALL_DIRECTION_INCOMING = "incoming"
CALL_DIRECTION_OUTGOING = "outgoing"
CALL_DIRECTIONS = (CALL_DIRECTION_INCOMING, CALL_DIRECTION_OUTGOING)

DEFAULT_SUBMIT_KEY = "#"
DEFAULT_CLEAR_KEY = "*"
DEFAULT_INPUT_TIMEOUT = 10
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_LOCKOUT_SECONDS = 60

CODE_MIN_LENGTH = 4
CODE_MAX_LENGTH = 12
CODE_DIGITS = frozenset("0123456789")
CONTROL_KEYS = ("*", "#", "A", "B", "C", "D")
VALID_DTMF_KEYS = CODE_DIGITS | frozenset(CONTROL_KEYS)

EVENT_ACCEPTED = "accepted"
EVENT_REJECTED = "rejected"
EVENT_LOCKED_OUT = "locked_out"


def code_signal(entry_id: str, profile_id: str) -> str:
    """Return the dispatcher signal for one code profile."""
    return f"{DOMAIN}_{entry_id}_code_{profile_id}"


def security_signal(entry_id: str) -> str:
    """Return the dispatcher signal for security events."""
    return f"{DOMAIN}_{entry_id}_security"
