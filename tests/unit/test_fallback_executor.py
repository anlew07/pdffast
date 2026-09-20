from pathlib import Path

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
        "p1",
        {
            "accept": _canonical("accept", "p1", "first"),
            "escalate": _canonical("escalate", "p1", ""),
        },
    )
    p2 = FakeProvider("p2", {"escalate": _canonical("escalate", "p2", "second")})
    tasks = [_task("accept", ["p1", "p2"]), _task("escalate", ["p1", "p2"])]

    manifest = execute_fallback(
        policy={"source_file": "fixture.pdf", "tasks": tasks},
        plan={"tasks": tasks},
        provider_configs={"p1": {"enabled": True}, "p2": {"enabled": True}},
        registry=FakeRegistry({"p1": p1, "p2": p2}),
        normalizer=lambda raw, task: raw.payload,
        output_dir=tmp_path,
    )

    assert manifest["summary"]["accepted_task_count"] == 2
    assert manifest["summary"]["escalated_count"] == 1
    assert manifest["summary"]["selected_provider_counts"] == {"p1": 1, "p2": 1}
    assert p1.calls == ["accept", "escalate"]
    assert p2.calls == ["escalate"]
    assert p1.initialized == p1.closed == 1
    assert p2.initialized == p2.closed == 1
    assert (tmp_path / "selected_predictions/accept.json").exists()
    assert (tmp_path / "selected_predictions/escalate.json").exists()


def test_executor_applies_terminal_or_pipeline_failure(tmp_path: Path) -> None:
    from pdffast.fallback.executor import execute_fallback

    provider = FakeProvider(
        "p1",
        {
            "terminal": _canonical("terminal", "p1", "", status="ERROR"),
            "failure": _canonical("failure", "p1", "", status="ERROR"),
        },
    )
    tasks = [_task("terminal", ["p1"], terminal=True), _task("failure", ["p1"])]

    manifest = execute_fallback(
        policy={"source_file": "fixture.pdf", "tasks": tasks},
        plan={"tasks": tasks},
        provider_configs={"p1": {"enabled": True}},
        registry=FakeRegistry({"p1": provider}),
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
        "p1",
        {
            "execute-error": RuntimeError("engine crashed"),
            "normalize-error": _canonical("normalize-error", "p1", "raw"),
        },
    )
    p2 = FakeProvider(
        "p2",
        {
            "execute-error": _canonical("execute-error", "p2", "recovered"),
            "normalize-error": _canonical("normalize-error", "p2", "recovered"),
        },
    )
    tasks = [
        _task("execute-error", ["p1", "p2"]),
        _task("normalize-error", ["p1", "p2"]),
    ]

    def normalize(raw: RawProviderResult, task: dict) -> dict:
        if raw.provider == "p1" and task["task_id"] == "normalize-error":
            raise ValueError("bad provider payload")
        return raw.payload

    manifest = execute_fallback(
        policy={"source_file": "fixture.pdf", "tasks": tasks},
        plan={"tasks": tasks},
        provider_configs={"p1": {"enabled": True}, "p2": {"enabled": True}},
        registry=FakeRegistry({"p1": p1, "p2": p2}),
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
