import { beforeEach, describe, expect, it, vi } from 'vitest';

const post = vi.fn(async (..._args: unknown[]) => ({
  draft: {},
  display_items: [],
  warnings: [],
}));

vi.mock('#/api/request', () => ({
  requestClient: { post: (...args: unknown[]) => post(...args) },
}));
vi.mock('@vben/stores', () => ({ useAccessStore: () => ({ accessToken: null }) }));
vi.mock('./sse-parser', () => ({ createSseParser: () => ({ push: vi.fn(), finish: vi.fn() }) }));

import { proposePurchaseRequestDraftApi } from './index';

describe('采购申请草稿预览请求', () => {
  beforeEach(() => post.mockClear());

  it('自然语言预览携带当前会话，供服务端还原查询来源', async () => {
    await proposePurchaseRequestDraftApi('按刚才的库存整理采购申请', 17);
    expect(post).toHaveBeenCalledWith('/ai/purchase-request-draft/preview', {
      question: '按刚才的库存整理采购申请',
      conversation_id: 17,
    });
  });

  it('结构化补齐仍携带同一会话，且没有会话时保持兼容', async () => {
    const draft = { purpose: '实验', items: [] } as never;
    await proposePurchaseRequestDraftApi(draft, 17);
    expect(post).toHaveBeenCalledWith('/ai/purchase-request-draft/preview', {
      draft,
      conversation_id: 17,
    });
    await proposePurchaseRequestDraftApi('采购乙醇 12 升');
    expect(post).toHaveBeenLastCalledWith('/ai/purchase-request-draft/preview', {
      question: '采购乙醇 12 升',
      conversation_id: undefined,
    });
  });
});
