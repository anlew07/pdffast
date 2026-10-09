"""Isolated real Uvicorn/Profiler/JSONL lab; inference is deliberately synthetic."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading

import uvicorn

from pdffast.native.profiler import run_profiler
from pdffast.providers.workers import JsonLineWorker
from pdffast.result import ParseResult
from pdffast.runtime import observe_parse
from pdffast.service import app as service


mode, directory, port = sys.argv[1:]
root = Path(directory)

WORKER = r'''
import json, os, sys, time
from pathlib import Path
root = Path(os.environ['LAB_ROOT'])
mode = os.environ['LAB_MODE']
def identity():
    (root/'worker.json').write_text(json.dumps({'pid':os.getpid(),'ppid':os.getppid()}))
def released():
    while not (root/'release').exists():
        time.sleep(.02)
def emit(data):
    print(json.dumps(data),flush=True)
if mode == 'init_failed':
    identity()
    released()
    emit({'status':'INIT_FAILED','error':'injected initialization error'})
else:
    emit({'status':'READY'})
for line in sys.stdin:
    if json.loads(line).get('op') == 'close':
        emit({'status':'BYE'})
        break
    identity()
    if mode == 'partial':
        sys.stdout.write('{"status":')
        sys.stdout.flush()
    released()
    if mode == 'partial':
        print('"SUCCESS"}',flush=True)
    elif mode == 'failed':
        emit({'status':'FAILED','error':'injected execution error'})
    else:
        emit({'status':'SUCCESS'})
'''


class SmallParser:
    def parse(self, pdf_path, *, run_id, case_id):
        with observe_parse(run_id):
            if mode == 'short':
                run_profiler(pdf_path=pdf_path, profile_output=root/'profile.json',
                             snapshot_output=root/'snapshot.jsonl', table_mode='off')
            else:
                worker = JsonLineWorker(
                    python_executable=Path(sys.executable), worker_code=WORKER,
                    dependency_probe_code="print('ok')",
                    env={'LAB_ROOT':str(root),'LAB_MODE':mode},
                )
                try:
                    worker.start()
                    response = worker.request({'op':'parse'},
                        timeout_seconds=float(os.getenv('LAB_TASK_TIMEOUT','.4')))
                    if response.get('status') != 'SUCCESS':
                        raise RuntimeError(response.get('error'))
                finally:
                    worker.close()
        (root/'finished.json').write_text(json.dumps({
            'threads':[thread.name for thread in threading.enumerate()],
        }))
        return ParseResult({}, '# lab', {'validation':{'pass':True}}, {})


service.create_parser = lambda: SmallParser()
uvicorn.run(service.app, host='127.0.0.1', port=int(port), log_level='info',
            timeout_graceful_shutdown=float(os.getenv('LAB_GRACE','1')))
