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
    assert manifest["version"] == "0.2.0"
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


def test_raw_event_contract_is_documented_without_legacy_caller_field():
    source = (INTEGRATION / "manager.py").read_text()

    assert 'data.get("remote_number")' in source
    assert 'data.get("call_id")' in source
    assert "caller_number" not in source
