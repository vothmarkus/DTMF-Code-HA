"""Tests for the direction-independent remote-counterpart contract."""

from custom_components.dtmf_code.const import NUMBER_MODE_ALLOW_LIST
from custom_components.dtmf_code.manager import CodeProfile, DTMFMetadata


def _metadata(direction: str, number: str) -> DTMFMetadata:
    return DTMFMetadata(
        instance_id="12345678-1234-5678-9234-567812345678",
        call_id="call-1",
        call_direction=direction,
        remote_number=number,
        received_at="2026-08-18T14:00:00+00:00",
    )


def test_allowlist_refers_to_remote_counterpart_for_both_directions() -> None:
    """The same policy field means caller inbound and destination outbound."""
    profile = CodeProfile(
        profile_id="family",
        title="Familie",
        code_hash="unused",
        number_mode=NUMBER_MODE_ALLOW_LIST,
        allowed_numbers=frozenset({"+491631416518"}),
        call_directions=frozenset({"incoming", "outgoing"}),
    )

    assert profile.authorizes(_metadata("incoming", "+491631416518"))
    assert profile.authorizes(_metadata("outgoing", "+491631416518"))
    assert not profile.authorizes(_metadata("outgoing", "+491701234567"))
