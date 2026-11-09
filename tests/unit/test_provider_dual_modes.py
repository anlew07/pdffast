"""Two-provider deployment profile contract tests; never load actual models."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from pdffast.fallback.policy import apply_provider_chain_overrides
from pdffast.providers.profiles import (
    REQUIRED_ROUTES,
    apply_production_profile,
    load_provider_profile,
)

ROOT = Path(__file__).resolve().parents[2]
PROFILE_ROOT = ROOT / "configs" / "profiles"
SELECTED = {"rapidocr_ch_light", "mineru_local"}


def _configs() -> dict:
    data = json.loads((ROOT / "configs" / "providers.json").read_text(encoding="utf-8"))
    return data["providers"]


@pytest.mark.parametrize("mode", ["speed", "quality"])
def test_only_two_runtime_providers_and_full_route_coverage(mode: str) -> None:
    before = _configs()
    untouched = deepcopy(before)
    profile = load_provider_profile(PROFILE_ROOT / f"production.{mode}.json")
    actual, overrides = apply_production_profile(before, profile)

    assert before == untouched
    assert set(profile["enabled_providers"]) == SELECTED
    assert set(overrides) == REQUIRED_ROUTES
    assert all(chain and set(chain) <= SELECTED for chain in overrides.values())
    assert {name for name, config in actual.items() if config["runtime_enabled"]} == SELECTED
    assert overrides["PAGE_DOCUMENT_LAYOUT_PARSE"] == ["mineru_local"]


@pytest.mark.parametrize(
    "mode,expected_first",
    [("speed", "rapidocr_ch_light"), ("quality", "mineru_local")],
)
def test_page_ocr_first_provider_matches_mode(mode: str, expected_first: str) -> None:
    profile = load_provider_profile(PROFILE_ROOT / f"production.{mode}.json")
    assert profile["chains"]["PAGE_DOCUMENT_OCR"][0] == expected_first


@pytest.mark.parametrize("mode", ["speed", "quality"])
def test_policy_override_applies_every_route_without_changing_acceptance(mode: str) -> None:
    profile = load_provider_profile(PROFILE_ROOT / f"production.{mode}.json")
    _, chains = apply_production_profile(_configs(), profile)
    routes = [
        ("PAGE_DOCUMENT_OCR", "PAGE_FAST_OCR_ESCALATION"),
        ("PAGE_DOCUMENT_LAYOUT_PARSE", "PAGE_LAYOUT_PARSE_ESCALATION"),
        ("REGION_MULTIMODAL_PARSE", "REGION_GENERIC_GAP_AWARE"),
        ("INLINE_CONTEXT_PARSE", "INLINE_MATH_CONTEXT"),
    ]
    tasks = [
        {
            "task_id": f"mock-{i}",
            "policy_class": policy_class,
            "capability_route": route,
            "provider_chain": [{"provider": "old-provider", "role": "OLD", "purpose": "test"}],
            "output_contract": {
                "required": ["status", "text"],
                "required_structure_channels_any": ["reading_blocks", "tables"] if route == "PAGE_DOCUMENT_LAYOUT_PARSE" else [],
            },
        }
        for i, (route, policy_class) in enumerate(routes)
    ]
    report = {
        "tasks": tasks,
        "summary": {"first_provider_counts": {}},
        "revision_notes": [],
    }
    original_contracts = deepcopy([task["output_contract"] for task in tasks])
    applied = apply_provider_chain_overrides(report, chains)
    for task, (route, _) in zip(applied["tasks"], routes):
        assert [entry["provider"] for entry in task["provider_chain"]] == chains[route]
    assert [task["output_contract"] for task in applied["tasks"]] == original_contracts
