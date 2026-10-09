"""Fault injection around real Worker and production executor ownership."""
import json
import sys
import threading
import time
from pathlib import Path

import pytest


def test_partial_worker_line_obeys_response_deadline(tmp_path):
    from pdffast.providers.workers import JsonLineWorker
    code='''import sys,json,time\nfrom pathlib import Path\nprint(json.dumps({'status':'READY'}),flush=True)\nfor line in sys.stdin:\n if json.loads(line).get('op')=='close':print(json.dumps({'status':'BYE'}),flush=True);break\n sys.stdout.write('{"status":');sys.stdout.flush()\n while not Path(RELEASE).exists():time.sleep(.01)\n print('"SUCCESS"}',flush=True)\n'''.replace('RELEASE',repr(str(tmp_path/'release')))
    worker=JsonLineWorker(python_executable=Path(sys.executable),worker_code=code,dependency_probe_code='')
    worker.start(); process=worker._process
    outcomes=[]
    def request():
        try:worker.request({'op':'parse'},timeout_seconds=.1);outcomes.append('success')
        except TimeoutError:outcomes.append('timeout')
    thread=threading.Thread(target=request);thread.start()
    try:
        thread.join(timeout=.8)
        assert not thread.is_alive(), 'partial JSONL line blocked beyond response deadline'
        assert outcomes==['timeout']
        assert process.poll() is not None and process.stdout.closed
    finally:
        (tmp_path/'release').write_text('release')
        thread.join(timeout=3)
        worker.close()


def execute(tmp_path, providers):
    from test_fallback_executor import FakeRegistry,_task
    from pdffast.fallback.executor import execute_fallback
    tasks=[_task(name,[name]) for name in providers]
    return execute_fallback(policy={'tasks':tasks},plan={'tasks':tasks},
        provider_configs={n:{'runtime_enabled':True,'kind':'rapidocr'} for n in providers},
        registry=FakeRegistry(providers), normalizer=lambda raw,task,**kwargs:raw.payload,output_dir=tmp_path)


def test_initialization_failure_still_closes_owned_provider(tmp_path):
    from test_fallback_executor import FakeProvider
    class Broken(FakeProvider):
        def initialize(self):raise RuntimeError('init failed')
    p=Broken('rapidocr_ch_light',{})
    with pytest.raises(RuntimeError,match='init failed'):execute(tmp_path,{p.name:p})
    assert p.closed==1


def test_close_failure_does_not_skip_remaining_provider(tmp_path):
    from test_fallback_executor import FakeProvider,_canonical
    class BrokenClose(FakeProvider):
        def close(self):
            super().close();raise RuntimeError('close failed')
    p1=BrokenClose('rapidocr_ch_light',{'rapidocr_ch_light':_canonical('rapidocr_ch_light','rapidocr_ch_light','ok')})
    p2=BrokenClose('paddleocr_v5_mobile',{'paddleocr_v5_mobile':_canonical('paddleocr_v5_mobile','paddleocr_v5_mobile','ok')})
    # sorted provider order makes Paddle close first.
    with pytest.raises(RuntimeError,match='close failed'):execute(tmp_path,{p2.name:p2,p1.name:p1})
    assert p1.closed==1 and p2.closed==1


def test_cleanup_errors_preserve_original_initialization_error(tmp_path):
    from test_fallback_executor import FakeProvider
    class Broken(FakeProvider):
        def initialize(self):raise ValueError('original init failure')
        def close(self):raise RuntimeError('cleanup also failed')
    p=Broken('rapidocr_ch_light',{})
    with pytest.raises(ValueError,match='original init failure'):execute(tmp_path,{p.name:p})


def test_cancellation_is_scoped_and_not_a_success():
    from pdffast.runtime import cancellable_parse,check_parse_cancelled,ParseCancelledError
    one,two=threading.Event(),threading.Event()
    with cancellable_parse(one):
        one.set()
        with pytest.raises(ParseCancelledError):check_parse_cancelled()
        with cancellable_parse(two):check_parse_cancelled()
        with pytest.raises(ParseCancelledError):check_parse_cancelled()
    check_parse_cancelled()


def test_service_request_cancellation_reaps_worker_and_heartbeat(tmp_path,monkeypatch):
    import asyncio
    from io import BytesIO
    from fastapi import UploadFile
    from pdffast.service import app as service
    from pdffast.runtime import observe_parse
    from pdffast.providers.workers import JsonLineWorker
    handles={};finished=[]
    class Parser:
        def parse(self,*args,run_id,**kwargs):
            with observe_parse(run_id,heartbeat_interval=.01):
                worker=JsonLineWorker(python_executable=Path(sys.executable),dependency_probe_code='',
                    worker_code="import json,sys,time\nprint(json.dumps({'status':'READY'}),flush=True)\nfor line in sys.stdin:time.sleep(20)\n")
                try:
                    worker.start();handles['process']=worker._process
                    worker.request({'op':'parse'},timeout_seconds=10)
                    finished.append(True)
                finally:worker.close()
    monkeypatch.setattr(service,'create_parser',lambda:Parser())
    async def run():
        task=asyncio.create_task(service.parse_pdf(UploadFile(file=BytesIO(b'%PDF-test'),filename='short.pdf')))
        deadline=time.monotonic()+3
        while 'process' not in handles:
            if time.monotonic()>deadline:raise AssertionError('worker did not start')
            await asyncio.sleep(.01)
        started=time.monotonic();task.cancel()
        with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(task,timeout=3)
        assert time.monotonic()-started<3
    asyncio.run(run())
    assert handles['process'].poll() is not None
    assert handles['process'].stdout.closed
    assert not finished
    assert not any(t.name.startswith('pdffast-heartbeat-') for t in threading.enumerate())


def test_service_entry_has_finite_grace_window(monkeypatch):
    from pdffast.service.__main__ import build_config
    monkeypatch.delenv('PDFFAST_SHUTDOWN_GRACE_SECONDS',raising=False)
    assert build_config().timeout_graceful_shutdown==30
    monkeypatch.setenv('PDFFAST_SHUTDOWN_GRACE_SECONDS','nan')
    with pytest.raises(ValueError):build_config()


def test_cancelling_one_request_preserves_other_worker(tmp_path, monkeypatch):
    import asyncio
    from io import BytesIO
    from fastapi import UploadFile
    from pdffast.service import app as service
    from pdffast.runtime import observe_parse
    from pdffast.providers.workers import JsonLineWorker
    from pdffast.result import ParseResult
    handles={}
    class Parser:
        def parse(self,*args,run_id,case_id):
            release=tmp_path/case_id
            code='''import sys,json,time\nfrom pathlib import Path\nprint(json.dumps({'status':'READY'}),flush=True)\nfor line in sys.stdin:\n if json.loads(line).get('op')=='close':print(json.dumps({'status':'BYE'}),flush=True);break\n while not Path(RELEASE).exists():time.sleep(.01)\n print(json.dumps({'status':'SUCCESS'}),flush=True)\n'''.replace('RELEASE',repr(str(release)))
            with observe_parse(run_id,heartbeat_interval=.01):
                worker=JsonLineWorker(python_executable=Path(sys.executable),worker_code=code,dependency_probe_code='')
                try:
                    worker.start();handles[case_id]=worker._process
                    worker.request({'op':'parse'},timeout_seconds=5)
                    return ParseResult({},case_id,{'validation':{'pass':True}},{})
                finally:worker.close()
    monkeypatch.setattr(service,'create_parser',lambda:Parser())
    async def run():
        one=asyncio.create_task(service.parse_pdf(UploadFile(file=BytesIO(b'%PDF-a'),filename='one.pdf')))
        two=asyncio.create_task(service.parse_pdf(UploadFile(file=BytesIO(b'%PDF-b'),filename='two.pdf')))
        try:
            deadline=time.monotonic()+3
            while len(handles)!=2:
                if time.monotonic()>deadline:raise AssertionError('both workers did not start')
                await asyncio.sleep(.01)
            one.cancel()
            with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(one,timeout=3)
            assert handles['one.pdf'].poll() is not None
            assert handles['two.pdf'].poll() is None
            (tmp_path/'two.pdf').write_text('release survivor')
            result=await asyncio.wait_for(two,timeout=3)
            assert result.markdown=='two.pdf'
            assert handles['two.pdf'].poll() is not None
        finally:
            (tmp_path/'one.pdf').write_text('release')
            (tmp_path/'two.pdf').write_text('release')
            await asyncio.gather(one,two,return_exceptions=True)
    asyncio.run(run())
    assert not service.app.state.parse_operations
    assert not any(t.name.startswith('pdffast-heartbeat-') for t in threading.enumerate())


def test_lifespan_cleanup_wait_is_bounded_and_logs_unfinished_run(monkeypatch, caplog):
    import asyncio
    from pdffast.service import app as service
    monkeypatch.setenv('PDFFAST_SHUTDOWN_CLEANUP_SECONDS', '.01')
    async def run():
        never=asyncio.Event()
        operation=asyncio.create_task(never.wait())
        cancelled=threading.Event()
        monkeypatch.setattr(service.app.state,'parse_operations',{operation:(cancelled,'unfinished-run')})
        try:
            with caplog.at_level('ERROR'):
                async with service.service_lifespan(service.app):pass
            assert cancelled.is_set()
            assert 'cleanup incomplete' in caplog.text and 'unfinished-run' in caplog.text
        finally:
            operation.cancel()
            await asyncio.gather(operation,return_exceptions=True)
    asyncio.run(run())


def test_preflight_cancellation_reaps_probe_process(tmp_path):
    from pdffast.runtime import cancellable_parse, ParseCancelledError
    from pdffast.providers.workers import JsonLineWorker
    cancelled=threading.Event()
    pid_file=tmp_path/'probe.pid'
    probe=f"import os,time; from pathlib import Path; Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(20)"
    worker=JsonLineWorker(python_executable=Path(sys.executable),worker_code='',
        dependency_probe_code=probe,preflight_timeout_seconds=2)
    result=[]
    def preflight():
        with cancellable_parse(cancelled):
            try:result.append(worker.preflight())
            except ParseCancelledError:result.append('cancelled')
    thread=threading.Thread(target=preflight);thread.start()
    try:
        deadline=time.monotonic()+1
        while not pid_file.exists():
            if time.monotonic()>deadline:raise AssertionError('probe did not start')
            time.sleep(.01)
        pid=int(pid_file.read_text())
        cancelled.set();thread.join(timeout=.5)
        assert not thread.is_alive(), 'preflight ignored shutdown cancellation'
        assert result==['cancelled']
        assert JsonLineWorker._current_identity(pid) is None
    finally:
        cancelled.set();thread.join(timeout=3);worker.close()
