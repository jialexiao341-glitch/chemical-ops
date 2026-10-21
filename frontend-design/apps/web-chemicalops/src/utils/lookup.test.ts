import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ getProductListApi: vi.fn(), getChemicalListApi: vi.fn(), getSupplierListApi: vi.fn(), getUnitListApi: vi.fn(), getWarehouseListApi: vi.fn() }));
vi.mock('#/api', () => api);
import { clearLookupCache, getProductNameMap } from './lookup';

describe('名称映射', () => {
  beforeEach(() => { clearLookupCache(); vi.clearAllMocks(); });
  it('超过 100 条继续分页且同一轮请求合并', async () => {
    api.getProductListApi.mockImplementation(async ({ page }) => ({
      items: Array.from({ length: page === 1 ? 100 : 1 }, (_, i) => ({ id: (page - 1) * 100 + i + 1, product_name: `产品${(page - 1) * 100 + i + 1}` })), total: 101,
    }));
    const [a, b] = await Promise.all([getProductNameMap(), getProductNameMap()]);
    expect(a).toBe(b);
    expect(a.get(101)).toBe('产品101');
    expect(api.getProductListApi).toHaveBeenCalledTimes(2);
    expect(api.getProductListApi).toHaveBeenLastCalledWith({ page: 2, page_size: 100 }, { silent: true });
  });
  it('失败不缓存，失效后加载改名结果', async () => {
    api.getProductListApi.mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ items: [{ id: 1, product_name: '旧名称' }], total: 1 })
      .mockResolvedValueOnce({ items: [{ id: 1, product_name: '新名称' }], total: 1 });
    expect((await getProductNameMap()).size).toBe(0);
    expect((await getProductNameMap()).get(1)).toBe('旧名称');
    clearLookupCache();
    expect((await getProductNameMap()).get(1)).toBe('新名称');
  });
  it('切换身份后不复用旧请求，迟到结果不回填缓存', async () => {
    let finish!: (value: unknown) => void;
    api.getProductListApi.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValue({ items: [{ id: 2, product_name: '当前身份' }], total: 1 });
    const old = getProductNameMap();
    clearLookupCache();
    expect((await getProductNameMap()).has(1)).toBe(false);
    finish({ items: [{ id: 1, product_name: '旧身份' }], total: 1 });
    await old;
    expect((await getProductNameMap()).get(2)).toBe('当前身份');
  });
});
