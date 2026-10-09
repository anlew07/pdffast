"""Real, isolated Uvicorn signal tests using small HTTP and Worker workloads."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest


def short_pdf() -> bytes:
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    stream = b'BT /F1 12 Tf 20 250 Td (Short PDF lifecycle test) Tj ET'
    objects.append(b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream')
    pdf = b'%PDF-1.4\n'
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(pdf)
    pdf += b'xref\n0 6\n0000000000 65535 f \n'
    pdf += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets)
    return pdf + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()


def wait_for(condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            raise AssertionError('lifecycle condition was not reached')
        time.sleep(.02)


@pytest.mark.parametrize('mode, sig, budget', [
    ('idle', signal.SIGINT, '.4'),
    ('short', signal.SIGINT, '.4'),
    ('worker', signal.SIGINT, '.4'),
    ('worker', signal.SIGTERM, '.4'),
    ('partial', signal.SIGINT, '.4'),
    ('worker', signal.SIGINT, '20'),
    ('worker', signal.SIGTERM, '20'),
    ('graceful', signal.SIGINT, '20'),
    ('init_failed', signal.SIGINT, '20'),
    ('failed', signal.SIGTERM, '20'),
])
def test_uvicorn_stops_reaps_worker_and_releases_port(tmp_path, mode, sig, budget):
    pytest.importorskip('uvicorn')
    from pdffast.providers.workers import JsonLineWorker
    try:
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            port = reserved.getsockname()[1]
    except PermissionError:
        pytest.skip('sandbox forbids localhost bind; run isolated service tests with network permission')
    assert port != 8010
    server = Path(__file__).resolve().parents[1] / 'fixtures/service_shutdown_lab.py'
    root = Path(__file__).resolve().parents[2]
    response = {}
    client = None
    worker_identity = None
    with (tmp_path/'server.log').open('w') as log:
        process = subprocess.Popen(
            [sys.executable, str(server), mode, str(tmp_path), str(port)],
            env=dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE='1',
                     LAB_TASK_TIMEOUT=budget, LAB_GRACE='.3'),
            stdout=log, stderr=log, start_new_session=True,
        )
        def healthy():
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=.2).close()
                return True
            except OSError:
                return False
        def request():
            body = b'--lab\r\nContent-Disposition: form-data; name="file"; filename="short.pdf"\r\nContent-Type: application/pdf\r\n\r\n' + short_pdf() + b'\r\n--lab--\r\n'
            try:
                req = urllib.request.Request(f'http://127.0.0.1:{port}/parse', data=body,
                    headers={'Content-Type': 'multipart/form-data; boundary=lab'})
                with urllib.request.urlopen(req, timeout=10) as result:
                    response['status'] = result.status
                    response['body'] = json.loads(result.read())
            except Exception as exc:
                response['error'] = str(exc)
        try:
            wait_for(healthy)
            if mode != 'idle':
                client = threading.Thread(target=request)
                client.start()
                target = tmp_path / ('finished.json' if mode == 'short' else 'worker.json')
                wait_for(target.exists)
                if mode != 'short':
                    worker = json.loads(target.read_text())
                    assert worker['ppid'] == process.pid
                    worker_identity = JsonLineWorker._current_identity(worker['pid'])
                    assert worker_identity is not None
            if mode in ('init_failed', 'failed'):
                (tmp_path/'release').write_text('trigger injected failure')
                client.join(timeout=3)
                assert not client.is_alive() and response.get('status') != 200
            started = time.monotonic()
            process.send_signal(sig)
            if mode == 'graceful':
                (tmp_path/'release').write_text('complete within grace')
            process.wait(timeout=8)
            elapsed = time.monotonic()-started
            if client:
                client.join(timeout=3)
                assert not client.is_alive()
            if worker_identity:
                wait_for(lambda: JsonLineWorker._current_identity(worker_identity.pid) != worker_identity, 3)
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(('127.0.0.1', port))
            if mode in ('short', 'graceful'):
                assert response['status'] == 200
                assert set(response['body']) == {'schema_version','run_id','markdown','canonical','audit'}
                threads = json.loads((tmp_path/'finished.json').read_text())['threads']
                assert not any(name.startswith('pdffast-heartbeat-') for name in threads)
            elif mode != 'idle':
                assert response.get('status') != 200
                assert 'parse_failed' in (tmp_path/'server.log').read_text() or '解析失败' in (tmp_path/'server.log').read_text()
            (tmp_path/'evidence.json').write_text(json.dumps({
                'pid': process.pid, 'port': port, 'signal': sig.name, 'elapsed':elapsed,
                'worker_pid': worker_identity.pid if worker_identity else None,
                'returncode':process.returncode, 'response':response,
                'port_released': True, 'worker_reaped': True,
            }, ensure_ascii=False, indent=2))
        finally:
            (tmp_path/'release').write_text('cleanup lab only')
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=3)
            if client: client.join(timeout=3)
            # PID identity protects unrelated processes if the test itself fails.
            if worker_identity and JsonLineWorker._current_identity(worker_identity.pid)==worker_identity:
                os.kill(worker_identity.pid, signal.SIGTERM)
