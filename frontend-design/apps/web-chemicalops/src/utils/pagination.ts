/** 现有本地筛选控件需要完整选项时，逐页读取，禁止默默截断到第一页。 */
export async function fetchAllPages<T>(load: (page: number) => Promise<{ items: T[]; total: number }>) {
  const first = await load(1);
  const items = [...first.items];
  let page = 1;
  while (items.length < first.total) {
    const next = await load(++page);
    if (!next.items.length) throw new Error('选项数据已变化，请刷新后重试');
    items.push(...next.items);
  }
  return { ...first, items };
}

/** 没有 total 的兼容列表接口，短页表示读取结束。 */
export async function fetchAllListPages<T>(load: (page: number) => Promise<T[]>, pageSize = 100) {
  const items: T[] = [];
  for (let page = 1; ; page++) {
    const rows = await load(page);
    items.push(...rows);
    if (rows.length < pageSize) return items;
  }
}
