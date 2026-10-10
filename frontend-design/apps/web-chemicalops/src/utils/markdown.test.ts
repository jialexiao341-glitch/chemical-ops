import { describe, expect, it } from 'vitest';
import { renderMarkdown } from './markdown';

describe('聊天 Markdown 标题', () => {
  it('批量查询编号与比较标题渲染为标题，不外露井号', () => {
    const html = renderMarkdown('已完成 2/2 项查询。\n\n### 1. 查询乙醇（已完成）\n乙醇 2445 升。\n\n### 2. 查询甲醇（已完成）\n甲醇 2331 升。\n\n### 库存比较');
    expect(html).toContain('>1. 查询乙醇（已完成）</h3>');
    expect(html).toContain('>2. 查询甲醇（已完成）</h3>');
    expect(html).toContain('>库存比较</h3>');
    expect(html).not.toContain('###');
  });
  it('标题关闭前序列表，保留转义且不执行注入标签', () => {
    const html = renderMarkdown('1. 第一项\n### <img src=x onerror=alert(1)>\n正文');
    expect(html).toContain('</ol><h3');
    expect(html).toContain('&lt;img');
    expect(html).not.toContain('<img');
    expect(renderMarkdown('###不是标题')).toBe('<p>###不是标题</p>');
  });
});
