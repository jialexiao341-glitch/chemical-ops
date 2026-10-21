import type { AgentApi } from '#/api';
import { agentSourcePreview } from './task-view';

export interface AnswerSource {
  key: string;
  label: string;
  title: string;
  description: string;
  reference: string;
  observedAt?: string;
  timeLabel?: string;
  url?: string;
  to?: ReturnType<typeof agentSourcePreview>['to'];
  linkLabel?: string;
  record?: { dataset: string; label: string; record_id?: null | number; filters?: Record<string, string | number> };
  dataset?: string;
  status?: string;
}

export function safeSourceUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return;
  try {
    const url = new URL(value);
    if (['https:', 'http:'].includes(url.protocol)) return url.href;
  } catch { /* 无效或危险协议不能作为来源链接。 */ }
}

/** 只展示响应中实际保存的证据；历史消息不能靠重新检索补造引用。 */
export function answerSources(citations: any[] = [], canRead: (dataset: string) => boolean = () => true): AnswerSource[] {
  const sources = new Map<string, AnswerSource>();
  function add(source: AnswerSource) { sources.set(source.key, source); }
  function collect(citation: any) {
    if (!citation || typeof citation !== 'object') return;
    if (citation.type === 'multi_intent') {
      for (const task of citation.batch?.tasks ?? []) {
        if (task.status !== 'SUCCEEDED') continue;
        for (const nested of task.citations ?? []) collect(nested);
        for (const result of task.evidence ?? []) {
          const dataset = result.tool === 'inventory.query_available' ? 'inventory' : result.tool === 'supplier_quotes.compare' ? 'supplier_quotes' : undefined;
          if (!dataset || !canRead(dataset)) continue;
          for (const source of result.sources ?? []) {
            const preview = agentSourcePreview(result as AgentApi.Result, source);
            add({ ...preview, key: `${source.resource}:${source.record_id}`, label: dataset === 'inventory' ? '库存记录' : '供应商报价', observedAt: result.observed_at });
          }
        }
      }
      return;
    }
    if (citation.type === 'doc_kb') {
      const status = citation.source_status === 'changed' ? '来源内容已更新，请重新查询' : citation.source_status === 'missing' || citation.parse_status && citation.parse_status !== 'PARSED'
        ? '来源已不存在或不可用'
        : citation.source_status === 'unverified' || !citation.document_id || !citation.section_id ? '历史来源信息不完整，无法核验' : undefined;
      add({ key: `doc:${citation.document_id ?? ''}:${citation.section_id ?? citation.section_key}`, label: '知识库资料',
        title: citation.document_title || citation.title || citation.name_zh || '知识库文档',
        description: citation.content || '未保存可核验的章节摘录。',
        reference: [`文档 #${citation.document_id ?? '未记录'}`, citation.section_key || citation.title, citation.cas_no && `CAS ${citation.cas_no}`].filter(Boolean).join(' · '),
        observedAt: citation.updated_at, timeLabel: '资料更新', url: safeSourceUrl(citation.source_url), linkLabel: '打开原始来源', status });
      return;
    }
    const trace = citation.query_trace;
    if (trace?.dataset && canRead(trace.dataset)) {
      const records = (citation.source_records ?? []).filter((record: any) => canRead(record.dataset));
      const description = [`本次查询结果：${trace.row_count ?? trace.rows?.length ?? 0} 行`, trace.unit_note,
        trace.truncated ? '仅展示部分明细' : '',
        ...(trace.rows ?? []).slice(0, 5).map((row: any) => (trace.columns ?? []).map((column: any) => `${column.label || column.key}：${row[column.key] ?? '—'}`).join('；')),
      ].filter(Boolean).join('\n');
      add({ key: `query:${trace.dataset}:${trace.executed_at ?? ''}:${JSON.stringify(trace.slots ?? [])}`, label: '数据库查询',
        title: trace.dataset_label || trace.dataset,
        description: citation.snapshot_status === 'changed' ? `${description}\n\n提示：这是历史答案快照，相关数据可能已变化；重新查询可获取当前结果。` : description,
        reference: citation.snapshot_status === 'changed' ? '历史快照 · 数据可能已变化' : '当前用户权限范围内的查询快照',
        observedAt: trace.executed_at, dataset: trace.dataset,
        status: citation.snapshot_status === 'changed' ? '历史数据已变化' : undefined });
      for (const record of records) add({ key: `record:${record.dataset}:${record.record_id ?? JSON.stringify(record.filters)}`, label: '业务记录',
        title: record.label || trace.dataset_label, description: record.label || '本次查询引用的业务记录', reference: record.record_id ? `记录 #${record.record_id}` : '本次查询的筛选范围',
        observedAt: trace.executed_at, record });
    }
    if (citation.file_id && citation.type !== 'parsed_result') {
      const included = citation.parse_status === 'SUCCEEDED' && (citation.context_included === true || citation.parser === 'native-vision');
      add({ key: `file:${citation.file_id}`, label: '上传附件', title: citation.file_name || '用户上传附件',
        description: included ? '本次回答使用了该附件的解析内容或图片；具体事实请核对原文件。' : '该附件未成功进入本次回答上下文，不能作为回答依据。',
        reference: `附件 #${citation.file_id} · ${citation.parse_status || '状态未记录'}`, status: included ? undefined : '未取得可用依据' });
    }
  }
  for (const citation of citations) collect(citation);
  return [...sources.values()];
}
