import { describe, expect, it } from 'vitest';
import * as remote from './remote-options';
describe('远程选项', () => {
 it('关键词命中第101条并按ID保留已选名称，迟到搜索不覆盖新结果', async () => {
  expect(remote.createRemoteOptions).toBeTypeOf('function');
  let finish!: (rows: {label:string;value:number}[]) => void;
  const state = remote.createRemoteOptions(async (keyword) => keyword === '旧' ? new Promise((resolve) => { finish = resolve; }) : [{value:101,label:'产品101'}], async (id) => ({value:id,label:`已选${id}`}));
  await state.hydrate([7]);
  const old = state.search('旧'); await state.search('101'); finish([{value:1,label:'旧结果'}]); await old;
  expect(state.options()).toEqual([{value:7,label:'已选7'},{value:101,label:'产品101'}]);
 });
});
