import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pdffast import runtime


@pytest.mark.parametrize('mode,visible', [('quiet',False),('normal',False),('debug',True)])
def test_console_only_filters_tasks(mode,visible,tmp_path,capsys):
    handler=runtime._LiveEventHandler(mode=mode)
    logger=logging.getLogger('pdffast.runtime.events')
    old=list(logger.handlers);logger.handlers[:]=[handler]
    try:
        run=runtime.ParseObservation('api_full_long_identifier',log_path=tmp_path/'events.jsonl',heartbeat_interval=30)
        run.progress('parse_started','native_analysis')
        run.task_started('mineru_local','full_task_identifier')
        run._emit('parse_heartbeat')
        run.progress('parse_finished','finished')
        run.close()
    finally:
        logger.handlers[:]=old
    output=capsys.readouterr().err
    assert ('[任务执行]' in output) is visible
    assert '[运行心跳]' in output and 'api_full_long_identifier' in output
    assert len([json.loads(x) for x in (tmp_path/'events.jsonl').read_text().splitlines()])==4


def test_short_ids_are_unique_and_exception_is_full(capsys):
    h=runtime._LiveEventHandler(mode='normal')
    a=runtime.ParseObservation('same_prefix_a',log_path=None,heartbeat_interval=30)
    b=runtime.ParseObservation('same_prefix_b',log_path=None,heartbeat_interval=30)
    assert a._console_id!=b._console_id
    record=logging.makeLogRecord(dict(event='provider_task_failed',run_id=a.run_id,console_run_id=a._console_id,task_id='full_task',exception_type='TimeoutError',exception_message='worker timeout',levelno=logging.ERROR,msg='{}',args=()))
    h.handle(record)
    assert 'same_prefix_a' in capsys.readouterr().err


@pytest.mark.parametrize('mode', ['quiet','normal','debug'])
def test_mineru_local_logging_keeps_jsonl_and_errors(mode):
    from pdffast.providers.worker_logging import MINERU_LOGGING_CODE
    python=Path('runtimes/mineru/.venv/bin/python')
    if not python.exists(): pytest.skip('requires local MinerU environment; no models loaded')
    probe=MINERU_LOGGING_CODE+'''\nimport json,traceback
from loguru import logger
from tqdm import tqdm
logger.debug('probe_debug');logger.info('probe_info');logger.warning('probe_warning');logger.error('probe_error')
for _ in tqdm(range(2),desc='probe_progress'): pass
try: raise ValueError('probe_failure')
except ValueError: traceback.print_exc()
print(json.dumps({'status':'READY'}))
'''
    env=dict(os.environ,PDFFAST_LOG_MODE=mode)
    env.pop('TQDM_DISABLE', None)  # controlled probe; debug otherwise respects operator tqdm settings
    p=subprocess.run([str(python),'-c',probe],env=env,capture_output=True,text=True,timeout=20)
    assert p.returncode==0 and json.loads(p.stdout)=={'status':'READY'}
    for value in ('probe_warning','probe_error','Traceback','probe_failure'): assert value in p.stderr
    assert ('probe_debug' in p.stderr)==(mode=='debug')
    assert ('probe_info' in p.stderr)==(mode=='debug')
    assert ('probe_progress' in p.stderr)==(mode=='debug')


@pytest.mark.parametrize('mode,access', [('quiet',False),('normal',True),('debug',True)])
def test_uvicorn_access_mode(monkeypatch,mode,access):
    from pdffast.service.__main__ import build_config
    monkeypatch.setenv('PDFFAST_LOG_MODE',mode)
    assert build_config().access_log is access


def test_normal_concurrent_ids_map_back_to_full_runs(capsys):
    from concurrent.futures import ThreadPoolExecutor
    handler=runtime._LiveEventHandler(mode='normal')
    logger=runtime._events
    old=list(logger.handlers);logger.handlers[:]=[handler]
    def run(name):
        observation=runtime.ParseObservation(name,log_path=None,heartbeat_interval=30)
        observation.progress('parse_started','native_analysis')
        observation._emit('parse_heartbeat')
        observation.progress('parse_finished','finished')
        return observation._console_id
    try:
        with ThreadPoolExecutor(2) as pool:
            a,b=list(pool.map(run,['full_alpha','full_beta']))
    finally: logger.handlers[:]=old
    lines=capsys.readouterr().err.splitlines()
    for name,short in [('full_alpha',a),('full_beta',b)]:
        own=[line for line in lines if f'运行：{short}' in line]
        assert len(own)==3
        assert name in own[0] and name in own[-1]
        assert '运行编号' not in own[1]


def test_quiet_capture_failure_remains_visible(capsys):
    handler=runtime._LiveEventHandler(mode='quiet')
    record=logging.makeLogRecord(dict(event='supplemental_evidence_observed', run_id='full_capture_run',console_run_id='1:r1',task_id='full_capture_task',supplemental_diagnostics={'capture_status':'FAILED'},levelno=logging.INFO,msg='{}',args=()))
    handler.handle(record)
    output=capsys.readouterr().err
    assert '捕获失败' in output and 'full_capture_task' in output and 'full_capture_run' in output


def test_invalid_mode_is_explicit_configuration_error(monkeypatch):
    from pdffast.runtime_format import log_mode
    monkeypatch.setenv('PDFFAST_LOG_MODE','typo')
    with pytest.raises(ValueError,match='PDFFAST_LOG_MODE'): log_mode()
