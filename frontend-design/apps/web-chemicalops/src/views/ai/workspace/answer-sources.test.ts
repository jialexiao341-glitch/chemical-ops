import { describe, expect, it } from 'vitest';
import { answerSources, safeSourceUrl } from './answer-sources';

const doc = { type: 'doc_kb', document_id: 7, section_id: 9, document_title: '甲醇 MSDS', section_key: 'SECTION 9', cas_no: '67-56-1', parse_status: 'PARSED', content: '沸点：64.7℃', source_url: 'https://example.com/msds', updated_at: '2026-10-11T00:00:00Z' };
const query = { type: 'text2sql', query_trace: { dataset: 'purchase_orders', dataset_label: '采购订单', row_count: 1, rows: [{ count: 413 }], columns: [{ key: 'count', label: '订单数' }], executed_at: '2026-10-11T00:00:00Z' }, source_records: [{ dataset: 'purchase_orders', record_id: 3, label: '订单 PO-3' }] };

describe('统一回答来源', () => {
  it('知识库来源保留实际章节摘录、文档编号和安全原始链接', () => {
    expect(answerSources([doc])[0]).toMatchObject({ title: '甲醇 MSDS', description: '沸点：64.7℃', url: 'https://example.com/msds', reference: '文档 #7 · SECTION 9 · CAS 67-56-1', status: undefined });
  });
  it('数据库统计即使没有逐行来源编号，也有查询结果快照', () => {
    const sources = answerSources([{ ...query, source_records: [] }]);
    expect(sources).toHaveLength(1);
    expect(sources[0]?.description).toContain('订单数：413');
    expect(sources[0]?.dataset).toBe('purchase_orders');
  });
  it('批次中的知识库和数据库证据都展示并去重，失败项没有伪造来源', () => {
    const sources = answerSources([{ type: 'multi_intent', batch: { tasks: [
      { status: 'SUCCEEDED', citations: [doc, query] }, { status: 'SUCCEEDED', citations: [doc] },
      { status: 'FAILED', citations: [{ ...doc, section_id: 100 }] },
    ] } }]);
    expect(sources).toHaveLength(3);
    expect(sources.map((source) => source.label)).toEqual(['知识库资料', '数据库查询', '业务记录']);
  });
  it('权限变化后不展示相关数据库证据', () => {
    expect(answerSources([query], () => false)).toEqual([]);
  });
  it('缺失或已更新的来源不能标为可核验依据', () => {
    expect(answerSources([{ ...doc, source_status: 'changed' }])[0]?.status).toContain('已更新');
    expect(answerSources([{ ...doc, document_id: null }])[0]?.status).toContain('无法核验');
    expect(answerSources([{ ...doc, source_status: 'missing' }])[0]?.status).toContain('不可用');
  });
  it('未进入上下文和解析失败的附件不作为有效依据', () => {
    expect(answerSources([{ file_id: 1, parse_status: 'FAILED', context_included: true }])[0]?.status).toBe('未取得可用依据');
    expect(answerSources([{ file_id: 1, parse_status: 'SUCCEEDED', context_included: false }])[0]?.status).toBe('未取得可用依据');
    expect(answerSources([{ file_id: 1, parse_status: 'SUCCEEDED', context_included: true }])[0]?.status).toBeUndefined();
  });
  it('没有来源时不凭问题文字补造引用，拒绝危险协议链接', () => {
    expect(answerSources()).toEqual([]);
    expect(safeSourceUrl('javascript:alert(1)')).toBeUndefined();
    expect(safeSourceUrl('data:text/html,hello')).toBeUndefined();
  });
});
