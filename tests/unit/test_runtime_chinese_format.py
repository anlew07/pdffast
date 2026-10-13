"""Presentation must not mutate runtime events or fabricate outcomes."""
import json
import logging
import sys

import pytest

from pdffast import runtime

EVENTS = 'parse_started native_analysis_started native_observation_completed section_discovery_completed page_structure_completed table_recovery_completed native_analysis_finished evidence_started evidence_completed quality_completed fallback_planning_started fallback_planning_completed capability_routing_started capability_routing_completed provider_execution_started provider_initialization_started provider_initialized provider_task_started provider_task_finished provider_task_terminal provider_execution_finished provider_task_failed provider_execution_failed canonical_started canonical_completed renderer_started renderer_completed audit_started audit_completed result_writing_started parse_finished parse_failed parse_heartbeat'.split()


def record(event, **fields):
    payload = dict(event=event, run_id='api_test', current_phase='provider_execution', elapsed_seconds=120.0, **fields)
    return logging.makeLogRecord(dict(msg=json.dumps(payload), args=(), **payload))


def formatter():
    from pdffast.runtime_format import ChineseRuntimeFormatter
    return ChineseRuntimeFormatter()


@pytest.mark.parametrize('event', EVENTS)
def test_key_events_show_chinese_without_mutating_record(event):
    r = record(event)
    before = r.__dict__.copy()
    text = formatter().format(r)
    assert '[PDFFast][' in text and '运行编号：api_test' in text
    assert '[运行事件]' not in text
    assert any('\u4e00' <= c <= '\u9fff' for c in text.split('运行编号')[0])
    assert r.__dict__ == before


def test_unknown_event_provider_and_phase_fall_back():
    text = formatter().format(record('future_event', provider='future_provider'))
    assert 'future_event' in text and 'future_provider' in text
    r = record('parse_failed')
    r.current_phase = 'future_phase'
    assert 'future_phase' in formatter().format(r)


@pytest.mark.parametrize('status,accepted,expected', [
    ('SUCCESS',False,'执行成功，结果未被接受'),
    ('SUCCESS',True,'执行成功，结果已接受'),
    ('SUCCESS_WITH_WARNINGS',False,'执行成功（有警告），结果未被接受'),
    ('FAILED',False,'执行失败，结果未被接受'),
])
def test_task_outcomes_remain_distinct(status, accepted, expected):
    text=formatter().format(record('provider_task_finished', status=status, accepted=accepted, provider='marker_local', completed_tasks=0, total_tasks=54))
    assert expected in text and 'Marker' in text and 'provider_id=marker_local' in text
    assert '0/54' in text


def test_heartbeat_shows_measured_state_without_stall_or_eta_claim():
    text=formatter().format(record('parse_heartbeat', provider='marker_local', task_id='task_x', task_elapsed_seconds=121.8, last_progress_elapsed_seconds=121.8, completed_tasks=0, total_tasks=54))
    for expected in ('运行心跳','Marker','121.8 秒','0/54','task_x','距上次真实进展'):
        assert expected in text
    assert '卡死' not in text and 'ETA' not in text and '%' not in text


def test_failure_keeps_original_error_and_traceback():
    try:
        raise ModuleNotFoundError("No module named 'torchvision'")
    except ModuleNotFoundError:
        r=record('provider_task_failed', provider='mineru_local', task_id='task_x', exception_type='ModuleNotFoundError', exception_message="No module named 'torchvision'")
        r.exc_info=sys.exc_info()
    text=formatter().format(r)
    for expected in ('MinerU', 'task_x', 'ModuleNotFoundError', 'torchvision', 'Traceback', '任务失败'):
        assert expected in text


def test_live_console_is_chinese_once_while_file_and_records_stay_structured(tmp_path, capsys):
    records=[]
    class Collector(logging.Handler):
        def emit(self, r): records.append(r)
    handler=Collector()
    logger=logging.getLogger('pdffast.runtime.events')
    logger.addHandler(handler)
    path=tmp_path/'pipeline.log'
    try:
        with runtime.observe_parse('console', log_path=path):
            pass
    finally:
        logger.removeHandler(handler)
    console=capsys.readouterr().err
    assert console.count('[PDFFast][解析开始]') == 1
    assert console.count('[PDFFast][解析完成]') == 1
    assert '"event"' not in console
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    assert [r['event'] for r in rows] == ['parse_started','parse_finished']
    assert [json.loads(r.getMessage()) for r in records] == rows


def test_audit_completion_is_not_fabricated_pass_or_duration():
    text=formatter().format(record('audit_completed'))
    assert '已完成' in text and '已通过' not in text and '耗时 120' not in text


@pytest.mark.parametrize('provider,name', [
    ('rapidocr_ch_light','RapidOCR'), ('paddleocr_v5_mobile','PaddleOCR 文本'),
    ('paddleocr_vl_16','PaddleOCR-VL'), ('mineru_local','MinerU'),
    ('marker_local','Marker'), ('docling_local','Docling'),
])
def test_provider_display_keeps_original_id(provider, name):
    text=formatter().format(record('provider_initialized', provider=provider))
    assert f'Provider：{name}（provider_id={provider}）' in text


def test_default_interval_and_initialization_heartbeat_semantics():
    import inspect
    assert inspect.signature(runtime.observe_parse).parameters['heartbeat_interval'].default == 30.0
    r=record('parse_heartbeat', provider='marker_local')
    r.current_phase='provider_initialization'
    text=formatter().format(r)
    assert '正在初始化 Marker' in text and '任务编号' not in text and '已完成任务' not in text


def test_concurrent_console_lines_keep_run_provider_task_together(capsys, monkeypatch):
    monkeypatch.setattr(runtime._events, "handlers", [runtime._LiveEventHandler(mode="debug")])
    from concurrent.futures import ThreadPoolExecutor
    import threading
    barrier=threading.Barrier(2)
    def execute(run_id, provider):
        with runtime.observe_parse(run_id) as run:
            run.tasks_known(1)
            run.provider_started(provider)
            barrier.wait(timeout=2)
            run.task_started(provider, f'{run_id}_task')
            run.task_finished(accepted=True, completed=1, status='SUCCESS')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(execute,'alpha','mineru_local'),pool.submit(execute,'beta','marker_local')]
        for future in futures: future.result(timeout=3)
    lines=capsys.readouterr().err.splitlines()
    for run_id, provider, other in [('alpha','mineru_local','beta'),('beta','marker_local','alpha')]:
        own=[line for line in lines if f'运行编号：{run_id}' in line]
        assert len(own) == 5
        assert all(f'运行编号：{other}' not in line and f'{other}_task' not in line for line in own)
        tasks=[line for line in own if '任务编号' in line]
        assert len(tasks) == 2
        assert all(f'provider_id={provider}' in line and f'{run_id}_task' in line for line in tasks)
