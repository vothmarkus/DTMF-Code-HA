"""Security and normalization helpers for DTMF Code."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from urllib.parse import unquote

from .const import CODE_MAX_LENGTH, CODE_MIN_LENGTH

HASH_NAME = "sha256"
HASH_ITERATIONS = 240_000
HASH_SIZE = 32
SALT_SIZE = 16
HASH_PREFIX = "pbkdf2_sha256"
_CODE_PATTERN = re.compile(rf"^[0-9]{{{CODE_MIN_LENGTH},{CODE_MAX_LENGTH}}}$")


def new_hash_salt() -> str:
    """Create a random salt for one gateway configuration."""
    return base64.urlsafe_b64encode(secrets.token_bytes(SALT_SIZE)).decode("ascii")


def hash_code(code: str, encoded_salt: str) -> str:
    """Derive the stored representation of a numeric access code."""
    salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
    digest = hashlib.pbkdf2_hmac(
        HASH_NAME,
        code.encode("utf-8"),
        salt,
        HASH_ITERATIONS,
        dklen=HASH_SIZE,
    )
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"{HASH_PREFIX}${HASH_ITERATIONS}${encoded_digest}"


def hashes_equal(first: str, second: str) -> bool:
    """Compare derived code values without early exit."""
    return hmac.compare_digest(first.encode("ascii"), second.encode("ascii"))


def valid_code(code: str) -> bool:
    """Return whether a code satisfies the deliberately narrow policy."""
    return _CODE_PATTERN.fullmatch(code) is not None


def normalize_remote_number(value: str) -> str:
    """Canonicalize the user part of a SIP, SIPS, TEL, or dial identity.

    The implementation intentionally mirrors the Reolink SIP Gateway. It does
    not infer a country code and never performs suffix matching.
    """
    candidate = value.strip()
    if "<" in candidate and ">" in candidate:
        start = candidate.find("<") + 1
        end = candidate.find(">", start)
        if end >= start:
            candidate = candidate[start:end]
    candidate = candidate.strip().strip('"')

    lowered = candidate.lower()
    for scheme in ("sip:", "sips:", "tel:"):
        if lowered.startswith(scheme):
            candidate = candidate[len(scheme) :]
            break

    if "@" in candidate:
        candidate = candidate.rsplit("@", 1)[0]
    separator_positions = [
        position for character in ";?" if (position := candidate.find(character)) >= 0
    ]
    if separator_positions:
        candidate = candidate[: min(separator_positions)]
    candidate = unquote(candidate).strip().strip('"')
    if not candidate:
        return ""

    dial = []
    dial_like = True
    for index, character in enumerate(candidate):
        if character.isdigit() or character in "*#" or (character == "+" and index == 0):
            dial.append(character)
        elif character.isspace() or character in "-()./":
            continue
        else:
            dial_like = False

    if dial_like and dial:
        return "".join(dial)
    return candidate.lower()
