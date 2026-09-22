/**
 * 前端页面冒烟测试。
 *
 * 用真实账号登录后逐页访问，收集控制台错误并截图。
 * 用于在改动后快速确认「页面还能打开、没有运行时报错」。
 *
 * 前置：后端已在 8888 运行，前端 dev server 已在 3000 运行。
 *
 * 用法：
 *   node frontend-design/scripts/smoke-test.mjs
 *   SMOKE_USER=system_admin SMOKE_PASSWORD=xxx node frontend-design/scripts/smoke-test.mjs
 *
 * 说明：使用系统已安装的 Chrome（channel: 'chrome'），无需额外下载浏览器。
 */
import { mkdirSync } from 'node:fs';

import { chromium } from 'playwright';

const BASE = process.env.SMOKE_BASE ?? 'http://localhost:3000';
const USER = process.env.SMOKE_USER ?? 'system_admin';
const PASSWORD = process.env.SMOKE_PASSWORD ?? 'ChemicalOps@2026';
const OUT = process.env.SMOKE_OUT ?? 'C:/self_project/ChemicalOps/.cache/shots';

const PAGES = [
  ['dashboard', '/dashboard/overview'],
  ['master-chemicals', '/master/chemicals'],
  ['master-products', '/master/products'],
  ['master-suppliers', '/master/suppliers'],
  ['proc-requests', '/procurement/requests'],
  ['proc-rfqs', '/procurement/rfqs'],
  ['proc-orders', '/procurement/orders'],
  ['wh-deliveries', '/warehouse/deliveries'],
  ['wh-inventory', '/warehouse/inventory'],
  ['wh-transactions', '/warehouse/transactions'],
  ['wh-expiry', '/warehouse/expiry-alerts'],
  ['wh-issues', '/warehouse/issue-requests'],
  ['wh-transfers', '/warehouse/transfers'],
  ['wh-stocktakes', '/warehouse/stocktakes'],
  ['quality-accept', '/quality/acceptances'],
  ['ops-exceptions', '/operations/exceptions'],
  ['ai-workspace', '/ai/workspace'],
  ['sys-users', '/system/users'],
  ['sys-roles', '/system/roles'],
  ['sys-perms', '/system/permissions'],
  ['sys-depts', '/system/departments'],
  ['notifications', '/notifications'],
];

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ channel: 'chrome' });
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
});
const page = await ctx.newPage();

// 页面「看起来正常」但控制台报错也要能发现
const errors = [];
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`[console] ${m.text()}`);
});
page.on('pageerror', (e) => errors.push(`[pageerror] ${e.message}`));

await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);

const inputs = page.locator('input:visible');
await inputs.nth(0).fill(USER);
await inputs.nth(1).fill(PASSWORD);
await page.keyboard.press('Enter');
await page.waitForTimeout(6000);

if (page.url().includes('/auth/login')) {
  console.error('登录失败，请确认账号密码与后端状态');
  await browser.close();
  process.exit(1);
}
console.log(`登录成功（${USER}）: ${page.url()}\n`);

let failed = 0;
for (const [name, path] of PAGES) {
  errors.length = 0;
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  const title = await page.title();
  const bad = errors.length > 0;
  if (bad) failed += 1;
  console.log(
    `${bad ? 'FAIL' : ' ok '} ${name.padEnd(18)} ${page.url().replace(BASE, '')}  ${title}`,
  );
  for (const e of errors.slice(0, 4)) {
    console.log(`       ! ${e.slice(0, 180)}`);
  }
}

await browser.close();
console.log(`\n截图: ${OUT}`);
console.log(failed === 0 ? '全部页面无控制台错误' : `${failed} 个页面存在错误`);
process.exit(failed === 0 ? 0 : 1);
