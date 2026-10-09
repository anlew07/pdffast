"""MinerU must reject missing runtime imports before READY or page inference."""
import builtins
import io
import json
from types import SimpleNamespace

import pytest

from pdffast.providers.mineru import MinerUProvider, WORKER_CODE


@pytest.mark.parametrize('boundary', ['preflight', 'worker'])
@pytest.mark.parametrize('missing', ['torch', 'torchvision', 'mineru.backend.pipeline.pipeline_analyze'])
def test_missing_runtime_dependency_is_rejected_before_inference(monkeypatch, capsys, boundary, missing):
    original = builtins.__import__
    def controlled_import(name, *args, **kwargs):
        if name == missing:
            raise ModuleNotFoundError(f"No module named '{missing}'")
        if name in ('torch', 'torchvision'):
            return SimpleNamespace()
        if name == 'mineru.backend.pipeline.pipeline_analyze':
            return SimpleNamespace(doc_analyze_streaming=lambda: pytest.fail('inference must not run'))
        if name == 'mineru.cli.common':
            return SimpleNamespace(do_parse=lambda: pytest.fail('inference must not run'), read_fn=lambda: None)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', controlled_import)
    monkeypatch.setattr('sys.stdin', io.StringIO(''))
    code = MinerUProvider.dependency_probe_code if boundary == 'preflight' else WORKER_CODE
    with pytest.raises(ModuleNotFoundError, match=missing):
        exec(compile(code, '<mineru dependency check>', 'exec'), {})
    output = capsys.readouterr().out
    if boundary == 'worker':
        response = json.loads(output)
        assert response['status'] == 'INIT_FAILED'
        assert missing in response['error']
