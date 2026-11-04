from __future__ import annotations

import json
import sys
import types

import pytest

from pdffast.fallback.policy import apply_provider_chain_overrides, build_report
from pdffast.providers.base import ProviderPreflight, RawProviderResult
from pdffast.providers.registry import (
    ProviderConfigurationError, ProviderRegistry, ProviderClosureError,
    validate_runtime_provider_closure,
)
from pdffast.providers.runtime_normalization import normalize_runtime_result


def _module(monkeypatch):
    mod = types.ModuleType("pdffast_test_provider_plugin")

    class Provider:
        def __init__(self, name, config):
            self.name, self.config = name, config

        def preflight(self):
            return ProviderPreflight(self.name, True)

        def initialize(self):
            pass

        def execute(self, task):
            return RawProviderResult(self.name, task.task_id, "SUCCESS", {"text": "hello"})

        def close(self):
            pass

    def normalize(*, result, manifest_task, manifest_path, result_path, known_hashes=None):
        value = result["text"]
        empty = {"availability": "NOT_EMITTED", "items": []}
        return {
            "task_id": manifest_task["task_id"],
            "provider": result["provider"],
            "status": "SUCCESS",
            "text": {"availability": "AVAILABLE", "content": value, "raw_content": value},
            "tables": dict(empty), "formulas": dict(empty),
            "reading_blocks": dict(empty), "relations": dict(empty),
            "source_artifacts": {"task_result": str(result_path)},
        }

    mod.Provider = Provider
    mod.normalize = normalize
    monkeypatch.setitem(sys.modules, mod.__name__, mod)
    return mod


def _plugin():
    return {
        "demo_provider": {
            "kind": "demo_kind",
            "factory": "pdffast_test_provider_plugin:Provider",
            "normalizer": "pdffast_test_provider_plugin:normalize",
        }
    }


def test_default_registry_remains_closed(monkeypatch):
    _module(monkeypatch)
    with pytest.raises(ProviderConfigurationError, match="outside the production closure"):
        ProviderRegistry().create("demo_provider", {"kind": "demo_kind", "runtime_enabled": True})


def test_explicit_plugin_registers_without_editing_default_adapter_list(monkeypatch):
    mod = _module(monkeypatch)
    registry = ProviderRegistry(plugins=_plugin())
    assert registry.supports("demo_provider", "demo_kind")
    assert registry.plugin_normalizers == {"demo_provider": "pdffast_test_provider_plugin:normalize"}
    provider = registry.create("demo_provider", {"kind": "demo_kind", "runtime_enabled": True})
    assert isinstance(provider, mod.Provider)
    with pytest.raises(ProviderConfigurationError, match="declared kind"):
        registry.create("demo_provider", {"kind": "wrong", "runtime_enabled": True})


def test_plugin_requires_explicit_complete_policy_closure(monkeypatch):
    _module(monkeypatch)
    policy = {"tasks": [{"task_id": "t", "provider_chain": [{"provider": "demo_provider"}]}]}
    config = {"demo_provider": {"kind": "demo_kind", "runtime_enabled": True}}
    with pytest.raises(ProviderClosureError):
        validate_runtime_provider_closure(policy, config)
    assert validate_runtime_provider_closure(
        policy, config, registry=ProviderRegistry(plugins=_plugin())
    ) == frozenset({"demo_provider"})
    with pytest.raises(ProviderClosureError, match="runtime-disabled"):
        validate_runtime_provider_closure(
            policy, {"demo_provider": {"kind": "demo_kind", "runtime_enabled": False}},
            registry=ProviderRegistry(plugins=_plugin()),
        )


def test_explicit_plugin_runtime_normalizes_to_canonical(monkeypatch, tmp_path):
    _module(monkeypatch)
    raw = RawProviderResult("demo_provider", "t", "SUCCESS", {"text": "hello"})
    canonical = normalize_runtime_result(
        raw, {"task_id": "t", "capability_route": "PAGE_DOCUMENT_OCR"},
        result_path=tmp_path / "result.json",
        manifest_path=tmp_path / "manifest.json",
        plugin_normalizer_paths=ProviderRegistry(plugins=_plugin()).plugin_normalizers,
    )
    assert canonical["text"]["content"] == "hello"
    saved = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert saved["provider"]["name"] == "demo_provider"


def test_policy_override_changes_only_selected_chain_and_summary():
    plan = {
        "source_file": "test.pdf", "version": "0.2.1",
        "tasks": [{"task_id": "t", "capability_route": "PAGE_DOCUMENT_OCR", "route_hints": {}}],
    }
    routes = {
        route: {"frontiers": {"quality_latency": {"frontier": sorted(names)}}, "gaps": []}
        for route, names in {
            "PAGE_DOCUMENT_OCR": {"rapidocr_ch_light", "mineru_local", "paddleocr_vl_16"},
            "REGION_MULTIMODAL_PARSE": {"rapidocr_ch_light", "mineru_local", "marker_local", "paddleocr_v5_mobile"},
            "INLINE_CONTEXT_PARSE": {"rapidocr_ch_light", "marker_local", "paddleocr_v5_mobile"},
        }.items()
    }
    original = build_report(plan, {"version": "0.1.0", "routes": routes})
    assert original["tasks"][0]["provider_chain"][0]["provider"] == "rapidocr_ch_light"
    changed = apply_provider_chain_overrides(original, {"PAGE_DOCUMENT_OCR": ["demo_provider", "rapidocr_ch_light"]})
    assert [p["provider"] for p in changed["tasks"][0]["provider_chain"]] == ["demo_provider", "rapidocr_ch_light"]
    assert changed["summary"]["first_provider_counts"] == {"demo_provider": 1}
    with pytest.raises(ValueError, match="1-10 distinct"):
        apply_provider_chain_overrides(changed, {"PAGE_DOCUMENT_OCR": ["demo_provider", "demo_provider"]})


def test_builtin_names_cannot_be_overridden():
    with pytest.raises(ProviderConfigurationError, match="reserved"):
        ProviderRegistry(plugins={"mineru_local": _plugin()["demo_provider"]})

def test_parse_service_loads_plugin_and_overrides_from_local_config(monkeypatch, tmp_path):
    from pdffast.application.parse_service import ParseService
    from pdffast.config import ParserConfig
    from pdffast.result import ParseResult

    _module(monkeypatch)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "providers.json").write_text(
        json.dumps({
            "providers": {"demo_provider": {"kind": "demo_kind", "runtime_enabled": True}},
            "plugins": _plugin(),
            "provider_chain_overrides": {"PAGE_DOCUMENT_OCR": ["demo_provider"]},
        }),
        encoding="utf-8",
    )
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    captured = {}
    expected = ParseResult(canonical={}, markdown="", audit={}, artifacts={})

    def fake_pipeline(context, **kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr("pdffast.application.parse_service.run_core_pipeline", fake_pipeline)
    result = ParseService(ParserConfig(project_root=tmp_path, output_root=tmp_path / "out")).parse(pdf)
    assert result is expected
    assert captured["registry"].supports("demo_provider", "demo_kind")
    assert captured["provider_chain_overrides"] == {"PAGE_DOCUMENT_OCR": ["demo_provider"]}
    canonical = captured["normalizer"](
        RawProviderResult("demo_provider", "one", "SUCCESS", {"text": "hello"}),
        {"task_id": "one"},
        result_path=tmp_path / "raw.json",
        manifest_path=tmp_path / "manifest.json",
    )
    assert canonical["text"]["content"] == "hello"
