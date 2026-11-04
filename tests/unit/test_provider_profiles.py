from __future__ import annotations

import copy
import json

import pytest

from pdffast.providers.profiles import (
    REQUIRED_ROUTES, ProviderProfileError, apply_production_profile, load_provider_profile,
)


def _profile():
    return {
        "schema_version": "1.0",
        "name": "test-production",
        "enabled_providers": ["a", "b", "c"],
        "chains": {
            "PAGE_DOCUMENT_OCR": ["a", "b"],
            "PAGE_DOCUMENT_LAYOUT_PARSE": ["b", "c"],
            "REGION_MULTIMODAL_PARSE": ["a", "c"],
            "INLINE_CONTEXT_PARSE": ["c", "a"],
        },
    }


def test_profile_enables_only_chosen_and_retains_input():
    config = {name: {"kind": "test", "runtime_enabled": True, "benchmark_enabled": True} for name in ["a","b","c","unused"]}
    before = copy.deepcopy(config)
    applied, chains = apply_production_profile(config, _profile())
    assert config == before
    assert set(chains) == REQUIRED_ROUTES
    assert applied["unused"]["runtime_enabled"] is False
    assert all(applied[k]["runtime_enabled"] for k in ["a", "b", "c"])
    chains["PAGE_DOCUMENT_OCR"].append("unexpected")
    assert _profile()["chains"]["PAGE_DOCUMENT_OCR"] == ["a", "b"]


@pytest.mark.parametrize("mutation", [
    lambda p: p["chains"].pop("INLINE_CONTEXT_PARSE"),
    lambda p: p["chains"].update({"PAGE_DOCUMENT_OCR": ["a", "unused"]}),
    lambda p: p["chains"].update({"PAGE_DOCUMENT_OCR": ["a", "a"]}),
    lambda p: p["enabled_providers"].append("unknown"),
    lambda p: p["enabled_providers"].append("a"),
    lambda p: p["enabled_providers"].append("unused"),
    lambda p: p.update({"schema_version": "2.0"}),
    lambda p: p["chains"].update({"INVALID_ROUTE": ["a"]}),
])
def test_profile_rejects_invalid_changes(mutation):
    profile = _profile()
    mutation(profile)
    with pytest.raises(ProviderProfileError):
        apply_production_profile({name: {} for name in ("a", "b", "c", "unused")}, profile)


def test_profile_load_from_json(tmp_path):
    path = tmp_path / "profile.json"
    payload = _profile()
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_provider_profile(path) == payload
    with pytest.raises(ProviderProfileError):
        load_provider_profile(tmp_path / "missing.json")


def test_profile_keeps_existing_frozen_policy_when_not_selected():
    from pdffast.config import ParserConfig
    assert ParserConfig().provider_profile is None
    assert ParserConfig().provider_chain_overrides is None
