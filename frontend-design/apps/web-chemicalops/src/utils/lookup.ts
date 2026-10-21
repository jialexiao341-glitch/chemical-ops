/**
 * 主数据名称查询缓存。
 *
 * ChemicalOps 的列表接口大多只返回外键 ID（如 `product_id`、`warehouse_id`），
 * 表格如果直接展示 ID 可读性很差。这里按需拉取主数据并缓存，
 * 供各页面把 ID 翻译成名称。
 */
import {
  getChemicalListApi,
  getProductListApi,
  getSupplierListApi,
  getUnitListApi,
  getWarehouseListApi,
} from '#/api';

import { lookupCache as cache, lookupGeneration } from './lookup-state';
import { fetchAllPages } from './pagination';
export { clearLookupCache } from './lookup-state';

/** 单次拉取的最大条数，与后端 page_size 上限保持一致 */
const PAGE_SIZE = 100;

/** 简易缓存：记录已加载的映射与进行中的请求 */
const pending = new Map<string, { generation: number; promise: Promise<Map<number, string>> }>();

async function loadMap(
  key: string,
  loader: () => Promise<Array<{ id: number } & Record<string, any>>>,
  nameOf: (item: any) => string,
): Promise<Map<number, string>> {
  const cached = cache.get(key);
  if (cached && cached.expires > Date.now()) {
    return cached.value;
  }
  const inFlight = pending.get(key);
  if (inFlight?.generation === lookupGeneration) {
    return inFlight.promise;
  }
  const generation = lookupGeneration;
  const task = (async () => {
    try {
      const items = await loader();
      const map = new Map<number, string>();
      for (const item of items) {
        map.set(item.id, nameOf(item));
      }
      if (generation === lookupGeneration) cache.set(key, { value: map, expires: Date.now() + 60_000 });
      return map;
    } catch {
      // 主数据加载失败不应阻塞业务表格渲染，降级为显示原始 ID
      const empty = new Map<number, string>();
      return empty;
    } finally {
      if (pending.get(key)?.generation === generation) pending.delete(key);
    }
  })();
  pending.set(key, { generation, promise: task });
  return task;
}

/** 产品 ID → 产品名称 */
export function getProductNameMap() {
  return loadMap(
    'product',
    async () => (await fetchAllPages((page) => getProductListApi({ page, page_size: PAGE_SIZE }, { silent: true }))).items,
    (item) => item.product_name,
  );
}

/** 化学品 ID → 化学品名称 */
export function getChemicalNameMap() {
  return loadMap(
    'chemical',
    async () =>
      (await fetchAllPages((page) => getChemicalListApi({ page, page_size: PAGE_SIZE }, { silent: true }))).items,
    (item) => item.chemical_name,
  );
}

/** 供应商 ID → 供应商名称 */
export function getSupplierNameMap() {
  return loadMap('supplier', () => fetchAllPages((page) => getSupplierListApi({ page, page_size: PAGE_SIZE }, { silent: true })).then((r) => r.items), (item) => item.supplier_name);
}

/** 仓库 ID → 仓库名称 */
export function getWarehouseNameMap() {
  return loadMap('warehouse', () => getWarehouseListApi({ silent: true }), (item) => item.warehouse_name);
}

/** 计量单位 ID → 单位名称 */
export function getUnitNameMap() {
  return loadMap('unit', () => getUnitListApi({ silent: true }), (item) => item.unit_name);
}

/**
 * 生成一个「ID → 名称」的格式化函数，未命中时回退为 `#ID`。
 *
 * 用法：
 * ```ts
 * const productName = await createNameResolver(getProductNameMap);
 * productName(12) // => "乙醇"
 * ```
 */
export async function createNameResolver(
  loader: () => Promise<Map<number, string>>,
) {
  const map = await loader();
  return (id?: null | number) => {
    if (!id) {
      return '-';
    }
    return map.get(id) ?? `#${id}`;
  };
}
