"""Non-authoritative Provider evidence, independent of body reading blocks.

No file reads, content correction, Acceptance decision or Markdown insertion.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class SupplementalEvidence:
    data: Mapping[str, Any]

    @property
    def blocks(self) -> list[dict[str, Any]]:
        return deepcopy(self.data['blocks'])

    @property
    def diagnostics(self) -> list[dict[str, Any]]:
        return deepcopy(self.data['diagnostics'])

    @property
    def input_count(self) -> int:
        return self.data['input_count']

    @property
    def local_order_groups(self) -> list[dict[str, Any]]:
        return deepcopy(self.data['local_order_groups'])

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self.data))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SupplementalEvidence:
        if data.get('version') != '1' or not all(isinstance(data.get(k), list) for k in ('blocks','diagnostics','local_order_groups')):
            raise ValueError('invalid supplemental evidence envelope')
        return cls(deepcopy(dict(data)))


def _numbers(value: Any, count: int) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != count:
        return None
    if not all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in value):
        return None
    return list(value)


def validate_supplemental(envelope: Any, *, provider: str, page: int | None, markdown: str) -> SupplementalEvidence | None:
    if envelope is None:
        return None
    diagnostics: list[dict[str, Any]] = []
    if not isinstance(envelope, dict) or envelope.get('version') != '1' or not isinstance(envelope.get('blocks'), list):
        return SupplementalEvidence({'version':'1','blocks':[], 'input_count':0,'output_count':0,
                                     'diagnostics':[{'reason':'UNSUPPORTED_ENVELOPE'}], 'local_order_groups':[]})
    diagnostics.extend(deepcopy(envelope.get('diagnostics', [])) if isinstance(envelope.get('diagnostics'),list) else [])
    blocks: list[dict[str, Any]] = []
    identities: dict[str, dict[str, Any]] = {}
    whitespace = lambda text: re.sub(r'\s+', ' ', text).strip()
    for position, raw in enumerate(envelope['blocks']):
        if not isinstance(raw, dict):
            diagnostics.append({'position':position,'reason':'INVALID_BLOCK'}); continue
        kind = raw.get('original_type')
        source = str(raw.get('source_id') or f'ipc:{position}')
        if kind != 'page_footnote':
            diagnostics.append({'source_id':source,'original_type':kind,'reason':'EXCLUDED_ROLE' if kind in ('header','footer','page_number','aside_text','image') else 'UNKNOWN_TYPE'}); continue
        pn = raw.get('page')
        if not isinstance(pn,int) or isinstance(pn,bool) or pn < 1 or (page is not None and pn != page):
            diagnostics.append({'source_id':source,'reason':'PAGE_MISMATCH'}); continue
        text = raw.get('text')
        if not isinstance(text,str) or not text.strip():
            diagnostics.append({'source_id':source,'reason':'EMPTY_TEXT'}); continue
        bbox = _numbers(raw.get('bbox'),4)
        size = _numbers(raw.get('page_size'),2)
        uncertain = []
        if bbox is None or bbox[0]>=bbox[2] or bbox[1]>=bbox[3]:
            bbox = None; uncertain.extend(['INVALID_BBOX', 'DEDUP_GEOMETRY_UNAVAILABLE'])
        if size is None or min(size)<=0:
            size = None; uncertain.append('UNKNOWN_PAGE_SIZE')
        if bbox and size and not (0 <= bbox[0] < bbox[2] <= size[0] and 0 <= bbox[1] < bbox[3] <= size[1]):
            uncertain.append('BBOX_OUTSIDE_PAGE'); bbox = None
        coordinate_system = raw.get('coordinate_system')
        unit = raw.get('unit')
        if coordinate_system != 'mineru_page' or unit != 'pdf_point':
            uncertain.append('UNKNOWN_COORDINATE_SPACE')
        if whitespace(text) in whitespace(markdown):
            uncertain.append('MARKDOWN_TEXT_MATCH_WITHOUT_SPATIAL_PROOF')
        key = json.dumps([provider,pn,kind,whitespace(text),bbox,size,coordinate_system,unit],ensure_ascii=False)
        # Text alone, or a repeated ID without trusted geometry, never authorizes deletion.
        trusted = bbox is not None and size is not None and coordinate_system=='mineru_page' and unit=='pdf_point'
        if trusted and key in identities:
            prior=identities[key]
            if source not in prior['source_ids']: prior['source_ids'].append(source)
            prior['source_locators'].append({'source_id':source,'index':raw.get('source_index'),'position':raw.get('source_position',position)})
            diagnostics.append({'source_id':source,'block_id':prior['block_id'],'reason':'SAME_REGION_AND_CONTENT'});continue
        block_id=hashlib.sha256((key+f':{position}').encode()).hexdigest()[:24]
        block={'block_id':block_id,'evidence_type':'PAGE_FOOTNOTE','authority':'SUPPLEMENTAL_ONLY',
               'text':text,'page':pn,'bbox':bbox,'original_bbox':_numbers(raw.get('bbox'),4),
               'coordinate_system':coordinate_system,'unit':unit,'page_size':size,'provider_id':provider,
               'original_type':kind,'source_ids':[source],
               'source_locators':[{'source_id':source,'index':raw.get('source_index'),'position':raw.get('source_position',position)}],
               'local_order':'UNRESOLVED','body_order':'UNRESOLVED','uncertainties':uncertain}
        blocks.append(block)
        if trusted: identities[key]=block
    for i, block in enumerate(blocks):
        for other in blocks[:i]:
            if set(block['source_ids']) & set(other['source_ids']):
                for item in (block, other):
                    if 'SOURCE_ID_CONFLICT_OR_UNVERIFIABLE' not in item['uncertainties']:
                        item['uncertainties'].append('SOURCE_ID_CONFLICT_OR_UNVERIFIABLE')
            if block['bbox'] and block['bbox'] == other['bbox'] and block['page'] == other['page'] and whitespace(block['text']) != whitespace(other['text']):
                for item in (block, other):
                    item['uncertainties'].append('SAME_REGION_CONTENT_CONFLICT')
    groups=[]
    # Keep input order; expose separate geometric candidate groups, never rewrite body order.
    pages=sorted({b['page'] for b in blocks})
    for pn in pages:
        spatial=[b for b in blocks if b['page']==pn and b['bbox'] and b['page_size'] and 'UNKNOWN_COORDINATE_SPACE' not in b['uncertainties']]
        columns: dict[str,list[dict[str, Any]]] = {}
        for b in spatial:
            x0,_,x1,_=b['bbox']; width=b['page_size'][0]
            column='LEFT' if x1<=width/2 else ('RIGHT' if x0>=width/2 else 'SPANNING')
            columns.setdefault(column,[]).append(b)
        for column,items in columns.items():
            ordered=sorted(items,key=lambda b:(b['bbox'][1],b['bbox'][0]))
            # Overlapping boxes may still have strict vertical precedence when both edges agree.
            ambiguous=column=='SPANNING' or any(a['bbox'][1]>=b['bbox'][1] or a['bbox'][3]>=b['bbox'][3] for a,b in zip(ordered,ordered[1:]))
            state='UNRESOLVED' if ambiguous else 'GEOMETRIC_LOCAL_CANDIDATE'
            for b in items:
                b['local_order']=state
                if len(columns)>1:b['uncertainties'].append('CROSS_COLUMN_ORDER_UNKNOWN')
                if ambiguous:b['uncertainties'].append('LOCAL_GEOMETRY_AMBIGUOUS')
            groups.append({'page':pn,'region':f'FOOTNOTE_{column}','status':state,'block_ids':[b['block_id'] for b in ordered]})
    return SupplementalEvidence({'version':'1','blocks':blocks,'diagnostics':diagnostics,
                                 'input_count':len(envelope['blocks']),'output_count':len(blocks),'local_order_groups':groups,
                                 'capture_status':envelope.get('capture_status', 'UNSPECIFIED_LEGACY'),
                                 'callback_count':envelope.get('callback_count'),
                                 'raw_block_count':envelope.get('raw_block_count')})


def supplemental_diagnostics(raw: Any, task: Mapping[str, Any], *, run_id: str | None) -> dict[str, Any]:
    """Summarize an attempt without treating missing capture as an empty page.

    Counts describe observed evidence, not OCR accuracy or content coverage.
    No text bodies are copied into the diagnostic summary.
    """
    from collections import Counter

    evidence = raw.supplemental_evidence if raw is not None else None
    data = evidence.to_dict() if evidence is not None else {}
    diagnostics = [d for d in data.get('diagnostics', []) if isinstance(d, dict)]
    reasons = Counter(str(d.get('reason', 'UNKNOWN')) for d in diagnostics)
    provider = raw.provider if raw is not None else task.get('provider')
    status = data.get('capture_status')
    if status is None:
        status = ('UNAVAILABLE' if evidence is not None else
                  'MISSING' if provider == 'mineru_local' else 'NOT_SUPPORTED')
    callback_count = data.get('callback_count')
    allowed = {'COMPLETE', 'NOT_CALLED', 'FAILED', 'PARTIAL', 'UNAVAILABLE',
               'EXPORT_FAILED', 'UNSPECIFIED_LEGACY', 'MISSING', 'NOT_SUPPORTED'}
    if not isinstance(status, str) or status not in allowed or (callback_count is not None and (
        not isinstance(callback_count, int) or isinstance(callback_count, bool) or callback_count < 0
    )):
        status = 'UNAVAILABLE'
        callback_count = None
        diagnostics.append({'reason': 'INVALID_CAPTURE_METADATA'})
        reasons['INVALID_CAPTURE_METADATA'] += 1
    complete = status == 'COMPLETE'
    blocks = data.get('blocks', [])
    deduplicated = reasons.get('SAME_REGION_AND_CONTENT', 0)
    observed = len(blocks) if evidence is not None else None
    # Legacy or failed capture totals remain unknown; never infer from skip diagnostics.
    return {
        'run_id': run_id, 'provider_id': provider,
        'task_id': raw.task_id if raw is not None else task.get('task_id'),
        'page_number': task.get('page_number'), 'capture_status': status,
        'callback_count': callback_count,
        'raw_block_count': data.get('raw_block_count') if complete else None,
        'input_count': data.get('input_count') if complete else None,
        'eligible_count': observed + deduplicated if complete else None,
        'deduplicated_count': deduplicated if complete else None,
        'retained_count': observed if complete else None,
        'observed_retained_count': observed,
        'reason_counts': dict(sorted(reasons.items())), 'diagnostics': diagnostics,
        'spatial_complete': all(b.get('bbox') and b.get('page_size') and
            b.get('coordinate_system') == 'mineru_page' and b.get('unit') == 'pdf_point'
            for b in blocks) if blocks else None,
        'local_order_statuses': sorted({b.get('local_order', 'UNRESOLVED') for b in blocks}),
        'body_order': 'UNRESOLVED' if blocks else None,
        'uncertainty_counts': dict(sorted(Counter(u for b in blocks for u in b.get('uncertainties', [])).items())),
    }
