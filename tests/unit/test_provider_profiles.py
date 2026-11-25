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


@pytest.mark.parametrize("raw", ['{"name":NaN}', '{"name":"first","name":"second"}', 'not-json'])
def test_profile_rejects_non_json_numbers_duplicate_keys_and_malformed_objects(tmp_path, raw):
    path = tmp_path / "production.json"
    path.write_text(raw)
    with pytest.raises(ProviderProfileError):
        load_provider_profile(path)


def test_plan_rejects_legacy_provider_even_if_registered_and_enabled(tmp_path):
    from pathlib import Path

    from pdffast import ParserConfig
    from pdffast.application.production_profile import load_production_profile
    from pdffast.fallback.executor import execute_provider_plan
    from pdffast.fallback.policy import ProviderExecutionPlan
    from pdffast.providers.registry import ProviderClosureError

    root = Path(__file__).resolve().parents[2]
    snapshot = load_production_profile(ParserConfig(
        project_root=root, provider_profile=Path("configs/profiles/production.indra-triple.json"),
    ))
    snapshot.configs["marker_local"]["runtime_enabled"] = True
    plan = ProviderExecutionPlan({"tasks": [{
        "task_id": "disallowed-candidate",
        "capability_route": "PAGE_DOCUMENT_OCR",
        "provider_chain": [{"provider": "indra_local"}, {"provider": "marker_local"}],
    }]})
    with pytest.raises(ProviderClosureError, match="locked capability route"):
        execute_provider_plan(
            execution_plan=plan, registry=snapshot.registry, provider_configs=snapshot.configs,
            normalizer=lambda *args, **kwargs: {}, output_dir=tmp_path / "unused",
            locked_routes=snapshot.chains,
        )
    assert not (tmp_path / "unused").exists()


def test_profile_keeps_existing_frozen_policy_when_not_selected():
    from pdffast.config import ParserConfig
    assert ParserConfig().provider_profile is None
    assert ParserConfig().provider_chain_overrides is None


@pytest.mark.parametrize("injected", [
    {"provider_configs": {}},
    {"registry": object()},
    {"normalizer": object()},
    {"provider_plugins": {}},
])
def test_parse_service_rejects_injected_dependencies_before_pipeline(tmp_path, monkeypatch, injected):
    from pdffast.application.parse_service import ParseService
    from pdffast.config import ParserConfig

    profile_path = tmp_path / "production.json"
    profile_path.write_text(json.dumps(_profile()), encoding="utf-8")
    from pdffast import ConfigurationError

    def unexpected_pipeline(*args, **kwargs):
        pytest.fail("locked configuration must be checked before the pipeline")

    monkeypatch.setattr("pdffast.application.parse_service.run_core_pipeline", unexpected_pipeline)
    with pytest.raises(ConfigurationError, match="cannot be combined"):
        ParseService(ParserConfig(
            project_root=tmp_path, output_root=tmp_path / "out",
            provider_profile=profile_path, **injected,
        )).parse(tmp_path / "sample.pdf")
    assert not (tmp_path / "out").exists()


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


def test_facade_profile_cannot_be_silently_ignored(tmp_path):
    from pdffast import ConfigurationError, ParserConfig, PDFFastParser

    parser = PDFFastParser(
        config=ParserConfig(output_root=tmp_path / "out"),
        provider_profile=tmp_path / "locked.json",
    )
    with pytest.raises(ConfigurationError, match="provider_profile"):
        parser.parse(tmp_path / "absent.pdf")
