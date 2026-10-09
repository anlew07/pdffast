"""Stateless Chinese presentation of the existing structured runtime events."""
from __future__ import annotations

import logging


EVENT_LABELS = {
    'supplemental_evidence_observed': ('补充证据', '捕获诊断'),
    'parse_started': ('解析开始', '开始处理 PDF'),
    'native_analysis_started': ('原生解析', '开始分析'),
    'native_observation_completed': ('原生观察', '已完成，开始章节发现'),
    'section_discovery_completed': ('章节发现', '已完成，开始页面结构分析'),
    'page_structure_completed': ('页面结构', '已完成，开始表格恢复'),
    'table_recovery_completed': ('表格恢复', '已完成，开始文本流整理'),
    'native_analysis_finished': ('原生解析', '已完成'),
    'evidence_started': ('证据检查', '开始执行'),
    'evidence_completed': ('证据检查', '已完成'),
    'quality_completed': ('质量检查', '已完成'),
    'fallback_planning_started': ('增强规划', '开始执行'),
    'fallback_planning_completed': ('增强规划', '已完成'),
    'capability_routing_started': ('能力路由', '开始执行'),
    'capability_routing_completed': ('能力路由', '已完成'),
    'provider_execution_started': ('增强执行', '开始执行'),
    'provider_initialization_started': ('模型初始化', '开始初始化'),
    'provider_initialized': ('模型初始化', '初始化完成（Worker 已就绪）'),
    'provider_task_started': ('任务执行', '开始处理'),
    'provider_task_finished': ('任务完成', '执行结束'),
    'provider_cleanup_failed': ('资源清理失败', 'Provider 资源清理异常'),
    'provider_task_failed': ('任务失败', '执行异常'),
    'provider_task_terminal': ('任务终结', '已结束增强尝试'),
    'provider_execution_failed': ('增强失败', '执行异常'),
    'provider_execution_finished': ('增强执行', '已完成'),
    'canonical_started': ('结果构建', '开始构建 Canonical'),
    'canonical_completed': ('结果构建', 'Canonical 构建完成'),
    'renderer_started': ('文档输出', '开始生成 Markdown'),
    'renderer_completed': ('文档输出', 'Markdown 生成完成'),
    'audit_started': ('质量审计', '开始执行'),
    'audit_completed': ('质量审计', '已完成'),
    'result_writing_started': ('结果写出', '开始写出'),
    'parse_finished': ('解析完成', '处理结束'),
    'parse_failed': ('解析失败', '处理异常'),
    'parse_heartbeat': ('运行心跳', '仍在运行'),
}

PHASE_LABELS = {
    'parse_preparation': '解析准备', 'native_observation': '原生观察',
    'native_analysis': '原生解析', 'section_discovery': '章节发现',
    'page_structure': '页面结构', 'table_recovery': '表格恢复',
    'text_flow': '文本流整理', 'evidence': '证据检查', 'quality': '质量检查',
    'fallback_planning': '增强规划', 'capability_routing': '能力路由',
    'provider_policy': '增强执行计划', 'provider_initialization': '模型初始化',
    'provider_execution': '增强执行', 'canonical': '结果构建',
    'renderer': '文档输出', 'audit': '质量审计',
    'result_writing': '结果写出', 'finished': '已结束',
}

PROVIDER_LABELS = {
    'rapidocr_ch_light': 'RapidOCR', 'paddleocr_v5_mobile': 'PaddleOCR 文本',
    'paddleocr_vl_16': 'PaddleOCR-VL', 'docling_local': 'Docling',
    'mineru_local': 'MinerU', 'marker_local': 'Marker',
}


class ChineseRuntimeFormatter(logging.Formatter):
    """Format record attributes without changing its JSON message or state."""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, 'event', None)
        if event is None:
            return record.getMessage()
        label, message = EVENT_LABELS.get(event, ('运行事件', str(event)))
        provider = getattr(record, 'provider', None)
        provider_name = PROVIDER_LABELS.get(provider, provider) if provider else None
        phase = getattr(record, 'current_phase', None)
        if event == 'provider_task_finished':
            status = getattr(record, 'status', None)
            message = {
                'SUCCESS': '执行成功',
                'SUCCESS_WITH_WARNINGS': '执行成功（有警告）',
                'FAILED': '执行失败',
            }.get(status, '执行结束')
            accepted = getattr(record, 'accepted', None)
            if accepted is True:
                message += '，结果已接受'
            elif accepted is False:
                message += '，结果未被接受'
        elif event == 'parse_heartbeat' and provider_name:
            message = ('正在初始化 ' if phase == 'provider_initialization' else '正在执行 ') + provider_name
        parts = [f'[PDFFast][{label}] {message}', f'运行编号：{getattr(record, "run_id", "未知")}']
        if phase is not None:
            parts.append(f'阶段：{PHASE_LABELS.get(phase, phase)}')
        if provider_name:
            parts.append(f'Provider：{provider_name}（provider_id={provider}）')
        task_id = getattr(record, 'task_id', None)
        if task_id is not None:
            parts.append(f'任务编号：{task_id}')
        completed = getattr(record, 'completed_tasks', None)
        total = getattr(record, 'total_tasks', None)
        if completed is not None and total is not None:
            parts.append(f'已完成任务：{completed}/{total}')
        elif total is not None:
            parts.append(f'任务总数：{total}')
        elapsed = getattr(record, 'elapsed_seconds', None)
        if elapsed is not None:
            title = '总耗时' if event == 'parse_finished' else '累计运行'
            parts.append(f'{title}：{elapsed:.1f} 秒')
        if event == 'parse_heartbeat':
            for field, title in [('task_elapsed_seconds', '当前任务耗时'),
                                 ('last_progress_elapsed_seconds', '距上次真实进展')]:
                value = getattr(record, field, None)
                if value is not None:
                    parts.append(f'{title}：{value:.1f} 秒')
        status = getattr(record, 'status', None)
        if status is not None:
            parts.append(f'原始状态：{status}')
        for field, title in [('exception_type', '错误类型'), ('exception_message', '错误原因')]:
            value = getattr(record, field, None)
            if value is not None:
                parts.append(f'{title}：{value}')
        if event == 'supplemental_evidence_observed':
            diagnostic = getattr(record, 'supplemental_diagnostics', {})
            labels = {'COMPLETE': '捕获流程完成', 'NOT_CALLED': '捕获未执行',
                      'FAILED': '捕获失败', 'PARTIAL': '捕获不完整',
                      'UNAVAILABLE': '捕获不可用', 'MISSING': '捕获数据缺失',
                      'EXPORT_FAILED': '原始导出失败'}
            state = diagnostic.get('capture_status')
            parts.append(f'捕获状态：{labels.get(state, state)}')
            if diagnostic.get('page_number') is not None:
                parts.append(f'页码：{diagnostic["page_number"]}')
            if diagnostic.get('retained_count') is not None:
                parts.append(f'保留证据：{diagnostic["retained_count"]}')
            if diagnostic.get('body_order') == 'UNRESOLVED':
                local = diagnostic.get('local_order_statuses', [])
                parts.append('顺序：' + ('局部几何候选，' if local == ['GEOMETRIC_LOCAL_CANDIDATE'] else '') + '正文关系未知')
        text = ' | '.join(parts)
        if record.exc_info:
            text += '\n' + self.formatException(record.exc_info)
        return text
