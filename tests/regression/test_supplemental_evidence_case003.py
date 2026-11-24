"""Artifact-backed regression for captured MinerU supplemental evidence."""

import json
import os
from pathlib import Path

import pytest

from pdffast.providers.supplemental import validate_supplemental

pytestmark = pytest.mark.regression


@pytest.mark.parametrize('number,count',[(43,4),(44,3)])
def test_frozen_case003_in_memory_capture_and_order(number,count):
    from types import SimpleNamespace
    from pdffast.providers.mineru_capture import CAPTURE_CODE
    raw_root = os.environ.get("PDFFAST_REGRESSION_ARTIFACTS_ROOT")
    if not raw_root:
        pytest.skip("PDFFAST_REGRESSION_ARTIFACTS_ROOT is required for artifact-backed regression")
    folder = Path(raw_root).resolve() / f'mineru_case003_pages43_44_validation/run_3fe3efd98b/page_{number}'
    if not folder.exists():
        pytest.skip("frozen case003 supplemental evidence is unavailable")
    page=json.loads(next((folder/'raw').rglob('*middle.json')).read_text())['pdf_info'][0]
    def original(pdf_info):return None
    common=SimpleNamespace(_process_output=original);ns={};exec(CAPTURE_CODE,ns)
    with ns['capture_supplemental'](common,number,f'page:{number}') as captured:
        common._process_output([page])
    out=validate_supplemental(json.loads(json.dumps(captured)),provider='mineru_local',page=number,markdown=(folder/'document.md').read_text())
    assert len(out.blocks)==count
    assert [b['bbox'] for b in out.blocks]==[b['bbox'] for b in page['discarded_blocks'] if b['type']=='page_footnote']
    assert all(b['page']==number and b['body_order']=='UNRESOLVED' for b in out.blocks)
    assert all(b['local_order']=='GEOMETRIC_LOCAL_CANDIDATE' for b in out.blocks)
    if number==44:
        source_by_id={b['block_id']:b['source_locators'][0]['index'] for b in out.blocks}
        assert [source_by_id[i] for i in out.local_order_groups[0]['block_ids']]==[28,27,29]
    # Same origin represented twice cannot drop differently located identical text.
    doubled=validate_supplemental({**captured,'blocks':captured['blocks']*2},provider='mineru_local',page=number,markdown='')
    assert len(doubled.blocks)==count and doubled.input_count==count*2


def test_real_jsonl_worker_capture_without_model(tmp_path):
    import sys
    from pdffast.providers.mineru import WORKER_CODE
    from pdffast.providers.workers import JsonLineWorker
    prefix=r'''
import sys, types
from pathlib import Path
for name in ('torch','torchvision','mineru','mineru.cli','mineru.backend','mineru.backend.pipeline'):
    sys.modules[name]=types.ModuleType(name)
common=types.ModuleType('mineru.cli.common')
def output(pdf_info):
    return None
def parse(**kwargs):
    page={'page_idx':0,'page_size':[100,100],'discarded_blocks':[
        {'type':'page_footnote','index':7,'bbox':[10,70,40,80],
         'lines':[{'spans':[{'type':'text','content':'original footnote'}]}]}]}
    common._process_output([page])
    root=Path(kwargs['output_dir']);root.mkdir(parents=True,exist_ok=True)
    (root/(kwargs['pdf_file_names'][0]+'.md')).write_text('Body stays unchanged')
common._process_output=output
common.do_parse=parse
common.read_fn=lambda path:b'fake-pdf'
sys.modules['mineru.cli.common']=common
sys.modules['mineru.cli'].common=common
analyze=types.ModuleType('mineru.backend.pipeline.pipeline_analyze')
analyze.doc_analyze_streaming=lambda *a,**k:None
sys.modules['mineru.backend.pipeline.pipeline_analyze']=analyze
'''
    worker=JsonLineWorker(python_executable=Path(sys.executable),worker_code=prefix+WORKER_CODE,dependency_probe_code="print('fake=ok')",init_timeout_seconds=10)
    try:
        worker.start()
        for page in (43,44):
            response=worker.request({'op':'parse','input':str(tmp_path/'input.png'),'output_dir':str(tmp_path/f'p{page}'),
                                     'physical_page':page,'task_id':f't{page}'},timeout_seconds=10)
            assert response['status']=='SUCCESS'
            evidence=response['supplemental_evidence']
            assert len(evidence['blocks'])==1 and evidence['blocks'][0]['page']==page
            assert evidence['blocks'][0]['source_id'].startswith(f'task:t{page}')
            assert Path(response['markdown_path']).read_text()=='Body stays unchanged'
    finally:
        worker.close()


def test_capture_incompatible_api_and_export_exception():
    from types import SimpleNamespace
    from pdffast.providers.mineru_capture import CAPTURE_CODE
    ns={};exec(CAPTURE_CODE,ns)
    missing=SimpleNamespace()
    with ns['capture_supplemental'](missing,43,'t') as result:
        assert result['diagnostics'][0]['reason']=='MINERU_CAPTURE_API_UNAVAILABLE'
    def broken(pdf_info):raise RuntimeError('original export failure')
    common=SimpleNamespace(_process_output=broken)
    with pytest.raises(RuntimeError,match='original export failure'):
        with ns['capture_supplemental'](common,43,'t'):
            common._process_output([])
    assert common._process_output is broken


def test_geometry_changes_not_deduplicated_and_empty_explicit_envelope():
    a=candidate(); b=candidate(bbox=[10,70.1,40,80.1],source='content/1')
    out=validate_supplemental(envelope(a,b),provider='mineru_local',page=43,markdown='')
    assert len(out.blocks)==2
    empty=validate_supplemental(envelope(),provider='mineru_local',page=43,markdown='')
    assert empty is not None and empty.input_count==0 and not empty.blocks


def test_capture_zero_notes_distinct_from_missing_callback():
    from types import SimpleNamespace
    from pdffast.providers.mineru_capture import CAPTURE_CODE
    ns={};exec(CAPTURE_CODE,ns)
    def output(pdf_info):return 'main result'
    common=SimpleNamespace(_process_output=output)
    with ns['capture_supplemental'](common,43,'task') as missing:
        pass
    with ns['capture_supplemental'](common,43,'task') as empty:
        assert common._process_output([{'page_size':[100,100],'discarded_blocks':[]}])=='main result'
    assert missing['capture_status']=='NOT_CALLED'
    assert missing['callback_count']==0
    assert any(d['reason']=='CAPTURE_NOT_CALLED' for d in missing['diagnostics'])
    assert empty['capture_status']=='COMPLETE' and empty['callback_count']==1
    validated=validate_supplemental(empty,provider='mineru_local',page=43,markdown='body')
    assert validated.to_dict()['capture_status']=='COMPLETE'


def test_capture_extraction_failure_preserves_main_result():
    from types import SimpleNamespace
    from pdffast.providers.mineru_capture import CAPTURE_CODE
    ns={};exec(CAPTURE_CODE,ns)
    def output(pdf_info):return 'unchanged body'
    common=SimpleNamespace(_process_output=output)
    with ns['capture_supplemental'](common,43,'task') as failed:
        assert common._process_output([{'discarded_blocks':None}])=='unchanged body'
    assert failed['capture_status']=='FAILED' and failed['callback_count']==1
    assert failed['diagnostics'][0]['reason']=='SUPPLEMENTAL_CAPTURE_FAILED'
    assert common._process_output is output
