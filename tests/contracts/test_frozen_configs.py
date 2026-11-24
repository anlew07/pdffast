from hashlib import sha256
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "configs/providers.json",
            "f0c1e51a9a0000daf3fb3db68c8b7a73f0c93818019a86864920013645e9c8c1",
        ),
        (
            "pdffast/resources/configs/providers.json",
            "970ec177ef7bf7d0d04aa63d83336b8aea26464cff516d331815f51f7f11573c",
        ),
        (
            "configs/profiles/production.indra-triple.json",
            "12446eefdfdc92dafc861c3c0fb8f76eb342b48b6e7659e40110927886d40971",
        ),
        (
            "configs/frozen/stage9_route_candidates_prod_v001.json",
            "0d999777e130de54ff25248c02cf39ae37e9fe7c5ef9231650aa3304008772d3",
        ),
    ],
)
def test_production_config_checksum(path: str, expected: str) -> None:
    assert sha256(Path(path).read_bytes()).hexdigest() == expected


def test_provider_registry_contains_exact_approved_scope() -> None:
    registry = json.loads(Path("configs/providers.json").read_text(encoding="utf-8"))
    bundled = json.loads(Path("pdffast/resources/configs/providers.json").read_text(encoding="utf-8"))
    historical_providers = {
        "paddleocr_v5_mobile",
        "paddleocr_vl_16",
        "rapidocr_ch_light",
        "docling_local",
        "mineru_local",
        "marker_local",
    }
    assert set(registry["providers"]) == historical_providers | {"indra_local"}
    assert set(bundled["providers"]) == historical_providers
    assert registry["plugins"] == {
        "indra_local": {
            "kind": "indra_worker",
            "factory": "pdffast.providers.indra:IndraProvider",
            "normalizer": "pdffast.providers.indra_normalizer:normalize_indra",
        },
    }
    assert registry["providers"]["indra_local"]["kind"] == registry["plugins"]["indra_local"]["kind"]
    assert registry["providers"]["marker_local"]["env"]["HOME"] == (
        "${HOME}/Library/Caches/pdffast/marker-workers/${PDFFAST_WORKER_ID}"
    )
