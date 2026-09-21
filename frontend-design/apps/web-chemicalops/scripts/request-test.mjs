/**
 * 写路径实测：采购申请（含明细行编辑器）。
 *
 * 重点验证明细行被正确组装进请求体 —— 这是自定义组件最容易出错的环节，
 * 曾因 ItemsEditor 的 getter 返回新对象导致初始行填了值也不生效。
 *
 * 前置：后端 8888 与前端 3000 均在运行。
 * 用法：node frontend-design/scripts/request-test.mjs
 */
import { chromium } from 'playwright';

const browser = await chromium.launch({ channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1700, height: 1000 } });

const trace = [];
page.on('response', async (r) => {
  const req = r.request();
  if (!r.url().includes('/api/v1/purchase-requests')) return;
  let res = '';
  try {
    res = (await r.text()).slice(0, 300);
  } catch {
    res = '(unreadable)';
  }
  trace.push(
    `${r.status()} ${req.method()} ${r.url().replace(/^.*\/api\/v1/, '')}\n  请求体: ${req.postData() ?? '(无)'}\n  响应: ${res}`,
  );
});
const errs = [];
page.on('pageerror', (e) => errs.push(e.message));
page.on('console', (m) => {
  if (m.type() === 'error') errs.push(`[console] ${m.text()}`);
});

await page.goto('http://localhost:3000/', { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);
const li = page.locator('input:visible');
await li.nth(0).fill('system_admin');
await li.nth(1).fill('ChemicalOps@2026');
await page.keyboard.press('Enter');
await page.waitForTimeout(5000);

await page.goto('http://localhost:3000/procurement/requests', {
  waitUntil: 'networkidle',
});
await page.waitForTimeout(2500);

const stamp = Date.now().toString().slice(-6);
await page.getByRole('button', { name: '新建采购申请' }).click();
await page.waitForTimeout(2000);

await page.fill('textarea[name="purpose"]', `诊断采购申请${stamp}`);

const row1 = page.locator('.ant-table-tbody tr').first();
await row1.locator('input[placeholder="物料名称"]').fill(`诊断物料${stamp}`);
await row1.locator('input[placeholder="数量"]').fill('25');
await row1.locator('input[placeholder="预算单价"]').fill('12.5');

await row1.locator('.ant-select').filter({ hasText: '单位' }).first().click();
await page.waitForTimeout(900);
await page.locator('.ant-select-item-option').first().click();
await page.waitForTimeout(800);

trace.length = 0;
errs.length = 0;

await page.getByRole('button', { name: /确\s*认/ }).click();
await page.waitForTimeout(1000);

const toast = await page.evaluate(() =>
  [...document.querySelectorAll('[class*="message"]')]
    .map((el) => el.textContent?.trim())
    .filter(Boolean)
    .join(' | '),
);
await page.waitForTimeout(3000);

console.log('提交后抽屉仍打开:', await page.locator('textarea[name="purpose"]').isVisible());
console.log('\n=== 页面提示 ===');
console.log(toast || '(无)');
console.log('\n=== 接口调用 ===');
console.log(trace.join('\n\n') || '(未发出请求)');
console.log('\n=== 错误 ===');
console.log(errs.join('\n') || '(无)');

await page.screenshot({
  path: 'C:/self_project/ChemicalOps/.cache/shots/diag-request.png',
});
await browser.close();
