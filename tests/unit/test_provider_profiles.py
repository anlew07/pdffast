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


def test_parse_service_applies_profile_without_touching_original_registry(tmp_path, monkeypatch):
    from pdffast.application.parse_service import ParseService
    from pdffast.config import ParserConfig

    profile_path = tmp_path / "production.json"
    profile_path.write_text(json.dumps(_profile()), encoding="utf-8")
    original = {name: {"kind": "dummy", "runtime_enabled": True} for name in ("a", "b", "c", "unused")}
    seen = {}

    def fake_pipeline(context, **kwargs):
        seen.update(kwargs)
        return "pipeline-call-stub"

    monkeypatch.setattr("pdffast.application.parse_service.run_core_pipeline", fake_pipeline)
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    result = ParseService(ParserConfig(
        project_root=tmp_path, output_root=tmp_path / "out",
        provider_configs=original, registry=object(),
        normalizer=lambda *args, **kwargs: {},
        provider_profile=profile_path,
    )).parse(pdf)
    assert result == "pipeline-call-stub"
    assert seen["provider_chain_overrides"] == _profile()["chains"]
    assert seen["provider_configs"]["unused"]["runtime_enabled"] is False
    assert original["unused"]["runtime_enabled"] is True


def test_parse_service_rejects_profile_and_explicit_overrides(tmp_path):
    from pdffast.application.parse_service import ParseService
    from pdffast.config import ParserConfig
    from pdffast.errors import ConfigurationError

    p = tmp_path / "prod.json"
    p.write_text(json.dumps(_profile()), encoding="utf-8")
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(ConfigurationError, match="cannot be combined"):
        ParseService(ParserConfig(
            project_root=tmp_path, output_root=tmp_path / "out",
            provider_configs={name: {} for name in ("a", "b", "c")},
            registry=object(), normalizer=lambda *args, **kwargs: {},
            provider_chain_overrides={"PAGE_DOCUMENT_OCR": ["a"]},
            provider_profile=p,
        )).parse(pdf)
