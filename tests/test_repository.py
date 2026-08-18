"""Repository-level contract checks."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "dtmf_code"


def _key_tree(value):
    if isinstance(value, dict):
        return {key: _key_tree(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_key_tree(child) for child in value]
    return type(value).__name__


def test_manifest_and_hacs_metadata():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())

    assert manifest["domain"] == "dtmf_code"
    assert manifest["version"] == "0.2.3"
    assert manifest["config_flow"] is True
    assert manifest["integration_type"] == "helper"
    assert manifest["iot_class"] == "local_push"
    assert hacs["name"] == manifest["name"]
    assert (INTEGRATION / "brand" / "icon.png").is_file()


def test_translation_files_and_strings_have_identical_keys():
    strings = json.loads((INTEGRATION / "strings.json").read_text())
    english = json.loads((INTEGRATION / "translations" / "en.json").read_text())
    german = json.loads((INTEGRATION / "translations" / "de.json").read_text())

    assert _key_tree(strings) == _key_tree(english)
    assert _key_tree(english) == _key_tree(german)

    first_page_fields = {
        "gateway_entry_id",
        "submit_key",
        "clear_key",
        "input_timeout",
        "max_attempts",
        "lockout_seconds",
    }
    shared_fields = first_page_fields - {"gateway_entry_id"}
    assert set(strings["config"]["step"]["user"]["data"]) == first_page_fields
    assert set(strings["options"]["step"]["init"]["data"]) == shared_fields
    assert "already_configured" in strings["config"]["abort"]
    assert "code_profile_added" in strings["config"]["abort"]
    assert "stored_configuration_invalid" in strings["config"]["abort"]
    assert "stored_configuration_invalid" in strings["config_subentries"]["code"]["abort"]


def test_german_helper_pages_have_explicit_field_translations():
    """Protect the labels that previously appeared as raw schema keys in HA."""
    german = json.loads((INTEGRATION / "translations" / "de.json").read_text())

    first_page = german["config"]["step"]["user"]
    assert first_page["title"] == "DTMF-Code einrichten"
    assert first_page["data"] == {
        "gateway_entry_id": "Reolink SIP Gateway",
        "submit_key": "Bestätigungstaste",
        "clear_key": "Löschtaste",
        "input_timeout": "Eingabezeitlimit",
        "max_attempts": "Fehlversuche bis zur Sperre",
        "lockout_seconds": "Sperrdauer",
    }

    profile_page = german["config"]["step"]["code"]
    assert profile_page["title"] == "Codeprofil hinzufügen"
    assert profile_page["data"] == {
        "name": "Profilname",
        "code": "Zugangscode",
        "code_confirm": "Zugangscode bestätigen",
        "number_mode": "Zugelassene Gegenstellen",
        "allowed_numbers": "Rufnummernfreigabe der Gegenstelle",
        "call_directions": "Zugelassene Anrufrichtungen",
    }

    options_page = german["options"]["step"]["init"]
    assert options_page["title"] == "DTMF-Code-Einstellungen"
    assert options_page["data"] == {
        "submit_key": "Bestätigungstaste",
        "clear_key": "Löschtaste",
        "input_timeout": "Eingabezeitlimit",
        "max_attempts": "Fehlversuche bis zur Sperre",
        "lockout_seconds": "Sperrdauer",
    }


def test_raw_event_contract_is_documented_without_legacy_caller_field():
    source = (INTEGRATION / "manager.py").read_text()

    assert 'data.get("remote_number")' in source
    assert 'data.get("call_id")' in source
    assert "caller_number" not in source
