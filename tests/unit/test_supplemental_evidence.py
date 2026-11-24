from dataclasses import replace
import json
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


