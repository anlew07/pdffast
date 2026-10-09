import logging
from concurrent.futures import ThreadPoolExecutor

import pytest

from pdffast.providers.base import RawProviderResult
from pdffast.providers.supplemental import validate_supplemental


def summary(raw, run_id='run'):
    from pdffast.providers.supplemental import supplemental_diagnostics
    return supplemental_diagnostics(raw, {'page_number':43}, run_id=run_id)


def raw(envelope=None, provider='mineru_local'):
    return RawProviderResult(provider=provider, task_id='task', status='SUCCESS', payload={},
        supplemental_evidence=validate_supplemental(envelope, provider=provider, page=43, markdown=''))


@pytest.mark.parametrize('status,count', [('COMPLETE',1), ('NOT_CALLED',0), ('FAILED',1), ('PARTIAL',1)])
def test_capture_states_and_unknown_counts(status,count):
    d=summary(raw({'version':'1','blocks':[], 'capture_status':status,'callback_count':count,
                   'diagnostics':[{'reason':'SUPPLEMENTAL_CAPTURE_FAILED','error':'ValueError: broken'}] if status=='FAILED' else []}))
    assert d['capture_status']==status
    assert d['callback_count']==count
    assert d['retained_count']==(0 if status=='COMPLETE' else None)
    assert d['run_id']=='run' and d['page_number']==43
    if status=='FAILED': assert 'broken' in str(d['diagnostics'])


@pytest.mark.parametrize('provider,status',[('mineru_local','MISSING'),('marker_local','NOT_SUPPORTED')])
def test_absent_protocol_not_zero(provider,status):
    d=summary(raw(provider=provider))
    assert d['capture_status']==status and d['retained_count'] is None


def test_malformed_protocol_not_empty_capture():
    d=summary(raw({'version':'bad'}))
    assert d['capture_status']=='UNAVAILABLE'
    assert d['input_count'] is None
    assert d['reason_counts']=={'UNSUPPORTED_ENVELOPE':1}


def test_dedup_counts_and_order_without_text_dump():
    block={'original_type':'page_footnote','page':43,'text':'private footnote', 'bbox':[1,80,30,90],
           'page_size':[100,100], 'coordinate_system':'mineru_page','unit':'pdf_point','source_id':'a'}
    d=summary(raw({'version':'1','capture_status':'COMPLETE','callback_count':1,'blocks':[block,dict(block,source_id='b')]}))
    assert (d['input_count'],d['eligible_count'],d['deduplicated_count'],d['retained_count'])==(2,2,1,1)
    assert d['reason_counts']['SAME_REGION_AND_CONTENT']==1
    assert d['spatial_complete'] is True and d['body_order']=='UNRESOLVED'
    assert 'private footnote' not in str(d)


def test_concurrent_summaries_isolated():
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda n: summary(raw(), n), ['one','two']))
    assert [d['run_id'] for d in results]==['one','two']


def test_chinese_summary():
    from pdffast.runtime_format import ChineseRuntimeFormatter
    record=logging.makeLogRecord({'event':'supplemental_evidence_observed','run_id':'r',
        'provider':'mineru_local','supplemental_diagnostics':{'capture_status':'COMPLETE','page_number':43,
        'retained_count':4,'body_order':'UNRESOLVED'}})
    text=ChineseRuntimeFormatter().format(record)
    assert '补充证据' in text and '保留证据：4' in text and '正文关系未知' in text


def test_attempts_manifest_keep_rejected_candidates(tmp_path):
    from test_fallback_executor import FakeProvider, FakeRegistry, _canonical, _task
    from pdffast.fallback.executor import execute_fallback
    from pdffast.runtime import observe_parse
    providers={n:FakeProvider(n, {'task':_canonical('task', n, text)})
               for n,text in [('mineru_local',''),('marker_local','accepted')]}
    with observe_parse('attempt-run') as observation:
        before=observation._last_progress
        observation.diagnostic('test_diagnostic')
        assert observation._last_progress==before
        manifest=execute_fallback(policy={'tasks':[_task('task',list(providers))]},
            plan={'tasks':[_task('task',list(providers))]},
            provider_configs={n:{'runtime_enabled':True, 'kind':n.removesuffix('_local')+'_worker'} for n in providers},
            registry=FakeRegistry(providers), normalizer=lambda raw,task,**kwargs:raw.payload, output_dir=tmp_path)
    assert [d['accepted'] for d in manifest['supplemental_diagnostics']]==[False,True]
    assert all(d['run_id']=='attempt-run' for d in manifest['supplemental_diagnostics'])
    import json
    attempts=json.loads((tmp_path/'selected_predictions/task.json').read_text())['attempts']
    assert [a['supplemental_diagnostics']['provider_id'] for a in attempts]==list(providers)


def test_capture_raw_population_count():
    from pdffast.providers.mineru_capture import CAPTURE_CODE
    from types import SimpleNamespace
    namespace={}
    exec(CAPTURE_CODE,namespace)
    common=SimpleNamespace(_process_output=lambda pdf_info:None)
    with namespace['capture_supplemental'](common,43,'task') as envelope:
        common._process_output([{'discarded_blocks':[{'type':'header'}, {'type':'page_number'}]}])
    d=summary(raw(envelope))
    assert d['raw_block_count']==2 and d['input_count']==0


def test_invalid_metadata_does_not_claim_complete():
    d=summary(raw({'version':'1','blocks':[],'capture_status':'COMPLETE','callback_count':'bad'}))
    assert d['capture_status']=='UNAVAILABLE' and d['callback_count'] is None
    assert d['retained_count'] is None
