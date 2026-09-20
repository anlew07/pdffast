from pathlib import Path

import pytest

from pdffast.providers.base import ProviderPreflight, ProviderTask, RawProviderResult


def _canonical(task_id: str, provider: str, text: str, status: str = "SUCCESS"):
    availability = "AVAILABLE" if status == "SUCCESS" else "NOT_EMITTED"
    return {
        "task_id": task_id,
        "provider": {"name": provider},
        "status": status,
        "text": {"availability": availability, "content": text},
        "tables": {"availability": "NOT_EMITTED", "items": []},
        "formulas": {"availability": "NOT_EMITTED", "items": []},
        "reading_blocks": {"availability": "NOT_EMITTED", "items": []},
        "relations": {"availability": "NOT_EMITTED", "items": []},
    }


class FakeProvider:
    def __init__(self, name: str, outputs: dict[str, dict | Exception]):
        self.name = name
        self.outputs = outputs
        self.initialized = 0
        self.closed = 0
        self.calls: list[str] = []

    def preflight(self) -> ProviderPreflight:
        return ProviderPreflight(provider=self.name, available=True)

    def initialize(self) -> None:
        self.initialized += 1

    def execute(self, task: ProviderTask) -> RawProviderResult:
        self.calls.append(task.task_id)
        output = self.outputs[task.task_id]
        if isinstance(output, Exception):
            raise output
        return RawProviderResult(
            provider=self.name,
            task_id=task.task_id,
            status="SUCCEEDED",
            payload=output,
        )

    def close(self) -> None:
        self.closed += 1


class FakeRegistry:
    def __init__(self, providers: dict[str, FakeProvider]):
        self.providers = providers

    def create(self, name: str, config: dict):
        return self.providers[name]


def _task(task_id: str, chain: list[str], *, terminal: bool = False) -> dict:
    task = {
        "task_id": task_id,
        "task_type": "REGION_FALLBACK",
        "page_number": 1,
        "source_id": f"source-{task_id}",
        "capability_route": "REGION_MULTIMODAL_PARSE",
        "input_image": f"{task_id}.png",
        "provider_chain": [{"provider": name} for name in chain],
        "output_contract": {
            "required": ["text"],
            "empty_text_requires_warning": True,
        },
    }
    if terminal:
        task["terminal_fallback"] = {"action": "PRESERVE_SOURCE_REGION_UNRESOLVED"}
    return task


def test_executor_accepts_and_escalates_by_wave(tmp_path: Path) -> None:
    from pdffast.fallback.executor import execute_fallback

    p1 = FakeProvider(
        "rapidocr_ch_light",
        {
            "accept": _canonical("accept", "rapidocr_ch_light", "first"),
            "escalate": _canonical("escalate", "rapidocr_ch_light", ""),
        },
    )
    p2 = FakeProvider(
        "mineru_local",
        {"escalate": _canonical("escalate", "mineru_local", "second")},
    )
    tasks = [
        _task("accept", ["rapidocr_ch_light", "mineru_local"]),
        _task("escalate", ["rapidocr_ch_light", "mineru_local"]),
    ]

    manifest = execute_fallback(
        policy={"source_file": "fixture.pdf", "tasks": tasks},
        plan={"tasks": tasks},
        provider_configs={
            "rapidocr_ch_light": {
                "kind": "rapidocr",
                "runtime_enabled": True,
                "benchmark_enabled": True,
            },
            "mineru_local": {
                "kind": "mineru_worker",
                "runtime_enabled": True,
                "benchmark_enabled": False,
            },
        },
        registry=FakeRegistry(
            {"rapidocr_ch_light": p1, "mineru_local": p2}
        ),
        normalizer=lambda raw, task: raw.payload,
        output_dir=tmp_path,
    )

    assert manifest["summary"]["accepted_task_count"] == 2
    assert manifest["summary"]["escalated_count"] == 1
    assert manifest["summary"]["selected_provider_counts"] == {
        "rapidocr_ch_light": 1,
        "mineru_local": 1,
    }
    assert p1.calls == ["accept", "escalate"]
    assert p2.calls == ["escalate"]
    assert p1.initialized == p1.closed == 1
    assert p2.initialized == p2.closed == 1
    assert (tmp_path / "selected_predictions/accept.json").exists()
    assert (tmp_path / "selected_predictions/escalate.json").exists()


def test_executor_applies_terminal_or_pipeline_failure(tmp_path: Path) -> None:
    from pdffast.fallback.executor import execute_fallback

    provider = FakeProvider(
        "rapidocr_ch_light",
        {
            "terminal": _canonical(
                "terminal", "rapidocr_ch_light", "", status="ERROR"
            ),
            "failure": _canonical(
                "failure", "rapidocr_ch_light", "", status="ERROR"
            ),
        },
    )
    tasks = [
        _task("terminal", ["rapidocr_ch_light"], terminal=True),
        _task("failure", ["rapidocr_ch_light"]),
    ]

    manifest = execute_fallback(
        policy={"source_file": "fixture.pdf", "tasks": tasks},
        plan={"tasks": tasks},
        provider_configs={
            "rapidocr_ch_light": {
                "kind": "rapidocr",
                "runtime_enabled": True,
                "benchmark_enabled": True,
            }
        },
        registry=FakeRegistry({"rapidocr_ch_light": provider}),
        normalizer=lambda raw, task: raw.payload,
        output_dir=tmp_path,
    )

    assert manifest["status"] == "COMPLETED_WITH_PIPELINE_FAILURES"
    assert manifest["summary"]["terminal_preserve_count"] == 1
    assert manifest["summary"]["pipeline_failure_count"] == 1
    assert provider.closed == 1


def test_executor_records_provider_and_normalizer_exceptions_then_escalates(
    tmp_path: Path,
) -> None:
    from pdffast.fallback.executor import execute_fallback

    p1 = FakeProvider(
        "rapidocr_ch_light",
        {
            "execute-error": RuntimeError("engine crashed"),
            "normalize-error": _canonical(
                "normalize-error", "rapidocr_ch_light", "raw"
            ),
        },
    )
    p2 = FakeProvider(
        "mineru_local",
        {
            "execute-error": _canonical(
                "execute-error", "mineru_local", "recovered"
            ),
            "normalize-error": _canonical(
                "normalize-error", "mineru_local", "recovered"
            ),
        },
    )
    tasks = [
        _task("execute-error", ["rapidocr_ch_light", "mineru_local"]),
        _task("normalize-error", ["rapidocr_ch_light", "mineru_local"]),
    ]

    def normalize(raw: RawProviderResult, task: dict) -> dict:
        if (
            raw.provider == "rapidocr_ch_light"
            and task["task_id"] == "normalize-error"
        ):
            raise ValueError("bad provider payload")
        return raw.payload

    manifest = execute_fallback(
        policy={"source_file": "fixture.pdf", "tasks": tasks},
        plan={"tasks": tasks},
        provider_configs={
            "rapidocr_ch_light": {
                "kind": "rapidocr",
                "runtime_enabled": True,
                "benchmark_enabled": True,
            },
            "mineru_local": {
                "kind": "mineru_worker",
                "runtime_enabled": True,
                "benchmark_enabled": False,
            },
        },
        registry=FakeRegistry(
            {"rapidocr_ch_light": p1, "mineru_local": p2}
        ),
        normalizer=normalize,
        output_dir=tmp_path,
    )

    assert manifest["summary"]["accepted_task_count"] == 2
    assert manifest["summary"]["escalated_count"] == 2
    assert p1.initialized == p1.closed == 1
    assert p2.initialized == p2.closed == 1
    exceptions = [
        item["attempts"][0]["canonical"]["exception"]
        for item in (
            __import__("json").loads(path.read_text(encoding="utf-8"))
            for path in sorted((tmp_path / "selected_predictions").glob("*.json"))
        )
    ]
    assert exceptions == [
        "RuntimeError: engine crashed",
        "ValueError: bad provider payload",
    ]


def test_executor_validates_complete_runtime_closure_before_resolving_or_writing(
    tmp_path: Path,
) -> None:
    from pdffast.fallback.executor import execute_fallback
    from pdffast.providers.registry import ProviderClosureError

    class RegistryMustNotRun:
        def create(self, name: str, config: dict):
            raise AssertionError("registry resolution happened before closure validation")

    task = _task("missing-provider", ["mineru_local"])
    output_dir = tmp_path / "must-not-exist"

    with pytest.raises(ProviderClosureError, match="mineru_local.*missing"):
        execute_fallback(
            policy={"source_file": "fixture.pdf", "tasks": [task]},
            plan={"tasks": [task]},
            provider_configs={},
            registry=RegistryMustNotRun(),
            normalizer=lambda raw, metadata: raw.payload,
            output_dir=output_dir,
        )

    assert not output_dir.exists()
