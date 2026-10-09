from dataclasses import replace
import json
from pathlib import Path
import pytest
from pdffast.providers.supplemental import validate_supplemental, SupplementalEvidence


def candidate(text='note', bbox=None, source='middle/0'):
    return {'original_type':'page_footnote','text':text,'page':43,'bbox':bbox if bbox is not None else [10,70,40,80],
            'coordinate_system':'mineru_page','unit':'pdf_point','page_size':[100,100],
            'source_id':source,'source_index':1,'source_position':0}


def envelope(*items):
    return {'version':'1','blocks':list(items),'diagnostics':[]}


def test_identity_and_spatial_duplicates_preserve_sources():
    out=validate_supplemental(envelope(candidate(),candidate(source='content/5')),provider='mineru_local',page=43,markdown='')
    assert out.input_count==2 and len(out.blocks)==1
    assert out.blocks[0]['source_ids']==['middle/0','content/5']
    assert out.diagnostics[-1]['reason']=='SAME_REGION_AND_CONTENT'


def test_identical_text_different_region_not_deleted():
    out=validate_supplemental(envelope(candidate(),candidate(bbox=[10,40,40,50],source='middle/1')),provider='mineru_local',page=43,markdown='note')
    assert len(out.blocks)==2
    assert all('MARKDOWN_TEXT_MATCH_WITHOUT_SPATIAL_PROOF' in b['uncertainties'] for b in out.blocks)


def test_missing_geometry_and_unknown_role():
    a=candidate();a['bbox']=None
    b=candidate();b['original_type']='alien'
    out=validate_supplemental(envelope(a,a,b),provider='mineru_local',page=43,markdown='')
    assert len(out.blocks)==2 and out.blocks[0]['local_order']=='UNRESOLVED'
    assert any(x['reason']=='UNKNOWN_TYPE' for x in out.diagnostics)


def test_nonoverlap_local_order_and_crosscolumn():
    out=validate_supplemental(envelope(candidate(),candidate('earlier',[10,40,40,50])),provider='mineru_local',page=43,markdown='')
    assert out.local_order_groups[0]['block_ids']==[out.blocks[1]['block_id'],out.blocks[0]['block_id']]
    out=validate_supplemental(envelope(candidate(),candidate('right',[60,70,90,80])),provider='mineru_local',page=43,markdown='')
    assert all(b['body_order']=='UNRESOLVED' for b in out.blocks)
    assert all('CROSS_COLUMN_ORDER_UNKNOWN' in b['uncertainties'] for b in out.blocks)


def test_serialization_and_none_compatibility():
    out=validate_supplemental(envelope(candidate()),provider='mineru_local',page=43,markdown='')
    assert SupplementalEvidence.from_dict(json.loads(json.dumps(out.to_dict()))).to_dict()==out.to_dict()
    assert validate_supplemental(None,provider='marker_local',page=1,markdown='hello') is None


def test_invalid_geometry_and_conflicting_identity_retained():
    a=candidate();a['bbox']=[0,0,float('nan'),1]
    out=validate_supplemental(envelope(a,candidate('different')),provider='mineru_local',page=43,markdown='')
    assert len(out.blocks)==2
    assert 'INVALID_BBOX' in out.blocks[0]['uncertainties']


def test_no_footers_or_mislabelled_page():
    x=candidate();x['original_type']='footer'; y=candidate();y['page']=999
    out=validate_supplemental(envelope(x,y),provider='mineru_local',page=43,markdown='')
    assert not out.blocks and {d['reason'] for d in out.diagnostics}=={'EXCLUDED_ROLE','PAGE_MISMATCH'}


def test_capture_restores_callback_and_preserves_call_result():
    from types import SimpleNamespace
    from pdffast.providers.mineru_capture import CAPTURE_CODE
    namespace={};exec(CAPTURE_CODE,namespace)
    page={'page_idx':0,'page_size':[100,100],'discarded_blocks':[{'type':'page_footnote','index':7,'bbox':[10,70,40,80],'lines':[{'spans':[{'type':'text','content':'note'}]}]}]}
    def output(pdf_info):return 'unchanged'
    common=SimpleNamespace(_process_output=output)
    with namespace['capture_supplemental'](common,43,'task-1') as data:
        assert common._process_output([page])=='unchanged'
    assert common._process_output is output
    assert data['blocks'][0]['page']==43 and data['blocks'][0]['text']=='note'
    with pytest.raises(RuntimeError):
        with namespace['capture_supplemental'](common,43,'task-1'):
            raise RuntimeError('task error')
    assert common._process_output is output


def test_worker_handoff_and_normalizer_does_not_change_body_or_acceptance(tmp_path):
    from pdffast.providers.base import ProviderTask
    from pdffast.providers.mineru import MinerUProvider
    from pdffast.providers.runtime_normalization import normalize_runtime_result
    from pdffast.fallback.executor import _evaluate
    from pdffast.providers.normalization import normalize_prediction
    from tests.unit.test_provider_lifecycle import FakeWorker
    md=tmp_path/'body.md';md.write_text('# Title\n\nBody text')
    task={'task_id':'t1','task_type':'PAGE_FALLBACK','page_number':43,'source_id':'page:43',
          'capability_route':'PAGE_DOCUMENT_LAYOUT_PARSE','output_contract':{'required':['text'],'required_structure_channels_any':['reading_blocks']}}
    worker=FakeWorker({'status':'SUCCESS','markdown_path':str(md),'supplemental_evidence':envelope(candidate())})
    provider=MinerUProvider('mineru_local',{},worker_factory=lambda _:worker)
    raw=provider.execute(ProviderTask('t1',task['capability_route'],tmp_path/'input.png',metadata=task))
    assert worker.commands[0]['physical_page']==43
    assert raw.supplemental_evidence.blocks[0]['text']=='note'
    result=normalize_runtime_result(raw,task,result_path=tmp_path/'raw.json',manifest_path=tmp_path/'manifest.json')
    old=normalize_runtime_result(replace(raw,supplemental_evidence=None),task,result_path=tmp_path/'old.json',manifest_path=tmp_path/'oldmanifest.json')
    assert {k:v for k,v in result.items() if k not in ('source_artifacts','supplemental_evidence')}=={k:v for k,v in old.items() if k!='source_artifacts'}
    assert _evaluate(result,task)==_evaluate(old,task)==(True,[])
    assert result['text']['content']=='Title\n\nBody text'
    from pdffast.canonical._stage10_builder import compact_canonical
    assert compact_canonical(result)==compact_canonical(old)
    # File replay consumes serialized evidence but does not alter authoritative channels.
    manifest=json.loads((tmp_path/'manifest.json').read_text())
    replay=normalize_prediction(manifest=manifest,manifest_path=tmp_path/'manifest.json',task_map={'t1':task},provider='mineru_local',result_path=tmp_path/'raw.json')
    assert replay['supplemental_evidence']==result['supplemental_evidence']
    provider.close()


def test_worker_markdown_only_other_provider_unchanged(tmp_path):
    from pdffast.providers.base import ProviderTask
    from pdffast.providers.marker import MarkerProvider
    from tests.unit.test_provider_lifecycle import FakeWorker
    md=tmp_path/'x.md';md.write_text('body')
    worker=FakeWorker({'status':'SUCCESS','result_path':str(md)})
    provider=MarkerProvider('marker_local',{},worker_factory=lambda _:worker)
    raw=provider.execute(ProviderTask('t1','PAGE_DOCUMENT_LAYOUT_PARSE',tmp_path/'input.png'))
    assert raw.supplemental_evidence is None and raw.markdown=='body'
    provider.close()


@pytest.mark.parametrize('number,count',[(43,4),(44,3)])
def test_frozen_case003_in_memory_capture_and_order(number,count):
    from types import SimpleNamespace
    from pdffast.providers.mineru_capture import CAPTURE_CODE
    root=Path(__file__).resolve().parents[2]
    folder=root/f'outputs/mineru_case003_pages43_44_validation/run_3fe3efd98b/page_{number}'
    if not folder.exists():pytest.skip('local frozen case003 evidence unavailable')
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
