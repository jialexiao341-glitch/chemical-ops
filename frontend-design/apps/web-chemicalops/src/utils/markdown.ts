/**
 * 极简 Markdown → HTML 渲染器（零依赖）。
 *
 * 背景：AI 回复会输出 **粗体**、列表等 Markdown，此前前端按纯文本显示，
 * 星号原文外露。项目未引入 marked/dompurify（本机 pnpm 装大包有已知网络坑），
 * 因此自实现受支持的子集：
 *   段落换行 / 无序列表(- ) / 有序列表(1. ) / **粗体** / *斜体* /
 *   `行内代码` / [链接](http(s)://…) / 标题(# 至 ######)
 *
 * 安全：先对全文做 HTML 转义，再只拼接白名单标签，
 * 模型输出即使含 <script> 也只会以文本呈现，可安全 v-html。
 */

/** 先转义，后续所有标签都由本函数生成，杜绝注入 */
function escapeHtml(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

/** 行内语法（入参已转义） */
function renderInline(text: string): string {
  return text
    // 行内代码优先，保护其中的 * 等字符不被后续规则改写
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
    )
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
}

/** 渲染为可 v-html 的 HTML；空输入返回空串 */
export function renderMarkdown(source: null | string | undefined): string {
  if (!source) {
    return '';
  }
  const lines = escapeHtml(source).split(/\r?\n/);
  const out: string[] = [];
  let list: null | 'ol' | 'ul' = null;

  const closeList = () => {
    if (list) {
      out.push(list === 'ul' ? '</ul>' : '</ol>');
      list = null;
    }
  };

  for (const line of lines) {
    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      closeList();
      const level = heading[1]!.length;
      out.push(`<h${level} class="my-2 text-sm font-semibold">${renderInline(heading[2]!)}</h${level}>`);
      continue;
    }
    const unordered = line.match(/^\s*[-*]\s+(.*)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (unordered) {
      if (list !== 'ul') {
        closeList();
        out.push('<ul>');
        list = 'ul';
      }
      out.push(`<li>${renderInline(unordered[1]!)}</li>`);
      continue;
    }
    if (ordered) {
      if (list !== 'ol') {
        closeList();
        out.push('<ol>');
        list = 'ol';
      }
      out.push(`<li>${renderInline(ordered[1]!)}</li>`);
      continue;
    }
    closeList();
    if (!line.trim()) {
      continue; // 空行只负责分段，段距交给容器样式
    }
    out.push(`<p>${renderInline(line)}</p>`);
  }
  closeList();
  return out.join('');
}
