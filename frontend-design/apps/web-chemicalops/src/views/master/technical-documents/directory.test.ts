import { describe, expect, it } from 'vitest';
import { directoryChemicals, filterDirectory } from './directory';

const sources = [
  { doc_type: 'msds', cas_no: '64-17-5', name_zh: '乙醇', object_key: 'a.html' },
  { doc_type: 'msds', cas_no: '64-17-5', name_zh: '乙醇', object_key: 'a.pdf' },
  { doc_type: 'tds', cas_no: '67-56-1', name_zh: '甲醇', object_key: 'b.pdf' },
  { doc_type: 'tds', cas_no: '64-17-5', name_zh: null, object_key: 'a.pdf' },
] as const;

describe('技术资料目录', () => {
  it('按类型和 CAS 构建化学品目录，不合并不同类型的条目', () => {
    expect(directoryChemicals(sources, 'msds')).toEqual([{ label: '乙醇 · 64-17-5', value: '64-17-5' }]);
    expect(directoryChemicals(sources, 'tds')).toEqual([
      { label: '64-17-5', value: '64-17-5' },
      { label: '甲醇 · 67-56-1', value: '67-56-1' },
    ]);
  });
  it('筛选后保留同一化学品的不同原始文件', () => {
    expect(filterDirectory(sources, 'msds', '64-17-5').map((row) => row.object_key)).toEqual(['a.html', 'a.pdf']);
  });
});
