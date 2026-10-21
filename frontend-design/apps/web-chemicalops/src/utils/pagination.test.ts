import { describe, expect, it } from 'vitest';
import * as pagination from './pagination';
describe('无total分页选项', () => {
 it('加载第101条且精确满页继续读取空页', async () => {
   expect(pagination.fetchAllListPages).toBeTypeOf('function');
   const pages: number[] = [];
   const rows = await pagination.fetchAllListPages(async (page) => {
     pages.push(page); return page === 1 ? Array.from({length:100}, (_, i) => i) : [100];
   });
   expect(rows).toHaveLength(101); expect(pages).toEqual([1,2]);
 });
});
