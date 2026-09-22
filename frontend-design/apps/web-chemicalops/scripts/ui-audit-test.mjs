/**
 * 响应式与主题适配验证（对应 docs/新版前端说明.md 第七节第 10 项）：
 *   T 深浅色主题：header 切换 → 关键页面渲染 → 0 控制台错误 → 还原浅色
 *   U 窄屏适配：768px / 390px 视口访问关键页面 → 无横向溢出 → 0 控制台错误
 *
 * 判定口径：
 * - 主题：html[data-theme] 或 :root class 变化 + 页面无报错
 * - 溢出：document.documentElement.scrollWidth > window.innerWidth + 2（容忍 2px 抖动）
 *
 * 前置：后端 8888 与前端 3000 均在运行。
 * 用法：
 *   $env:SMOKE_PASSWORD='你的密码'; node scripts/ui-audit-test.mjs
 */
import { mkdirSync } from 'node:fs';

import { chromium } from 'playwright';

const BASE = process.env.SMOKE_BASE ?? 'http://localhost:3000';
const USER = process.env.SMOKE_USER ?? 'system_admin';
const PASSWORD = process.env.SMOKE_PASSWORD;
if (!PASSWORD) {
  console.error(
    '请通过环境变量 SMOKE_PASSWORD 提供登录密码（不写入仓库）。\n' +
      "PowerShell: $env:SMOKE_PASSWORD='***'; node scripts/ui-audit-test.mjs",
  );
  process.exit(1);
}
const OUT = 'C:/self_project/ChemicalOps/.cache/shots';
mkdirSync(OUT, { recursive: true });

const steps = [];
function record(name, ok, detail = '') {
  steps.push({ name, ok });
  console.log(`${ok ? ' ok ' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
}

/** 覆盖核心模块的代表页面 */
const PAGES = [
  ['dashboard', '/dashboard/overview'],
  ['proc-orders', '/procurement/orders'],
  ['wh-inventory', '/warehouse/inventory'],
  ['fin-reconciliations', '/finance/reconciliations'],
  ['ai-workspace', '/ai/workspace'],
  ['sys-users', '/system/users'],
];

const browser = await chromium.launch({ channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

let pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(`[pageerror] ${e.message}`));
page.on('console', (m) => {
  if (m.type() === 'error') pageErrors.push(`[console] ${m.text().slice(0, 200)}`);
});

function resetErrors() {
  pageErrors = [];
}

async function login() {
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
  const inputs = page.locator('input:visible');
  await inputs.nth(0).fill(USER);
  await inputs.nth(1).fill(PASSWORD);
  await page.keyboard.press('Enter');
  await page.waitForTimeout(5000);
  if (page.url().includes('/auth/login')) {
    throw new Error('登录失败，请确认账号密码与后端状态');
  }
}

/** 读取当前生效的主题（html data-theme 或 class） */
async function readTheme() {
  return page.evaluate(() => {
    const el = document.documentElement;
    return {
      dataTheme: el.dataset.theme ?? null,
      hasDarkClass: el.classList.contains('dark'),
      bg: getComputedStyle(el).getPropertyValue('--background').trim().slice(0, 30),
    };
  });
}

/** 逐页访问：收集报错 + 横向溢出 */
async function auditPages(tag, { checkOverflow }) {
  const results = [];
  for (const [name, path] of PAGES) {
    resetErrors();
    await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2200);
    const overflow = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
    }));
    const hasOverflow = overflow.scrollW > overflow.innerW + 2;
    const clean = pageErrors.length === 0;
    const ok = clean && (!checkOverflow || !hasOverflow);
    results.push({ name, ok });
    record(
      `${tag} ${name}`,
      ok,
      `错误=${pageErrors.length}${checkOverflow ? ` 溢出=${hasOverflow}(${overflow.scrollW}>${overflow.innerW})` : ''}`,
    );
    if (!clean) console.log(`       ${pageErrors.slice(0, 2).join(' | ')}`);
    await page.screenshot({ path: `${OUT}/ui-${tag}-${name}.png` });
  }
  return results.every((r) => r.ok);
}

// ---------- 登录 ----------
await login();
record('登录成功', true, page.url());

// ============================================================
// T. 深浅色主题切换
// ============================================================
console.log('\n--- T. 主题切换 ---');

const before = await readTheme();
record('T0 初始主题已识别', true, JSON.stringify(before));

// 点 header 的主题切换按钮（ThemeButton 带 .theme-toggle class，
// aria-label 是目标主题 light/dark）
const themeBtn = page.locator('header .theme-toggle, header [aria-label="dark"], header [aria-label="light"]').first();
const themeBtnCount = await themeBtn.count();
if (themeBtnCount === 0) {
  record('T1 找到主题切换按钮', false, 'header 内未找到 .theme-toggle 按钮');
} else {
  await themeBtn.click();
  await page.waitForTimeout(1500);
  const afterToggle = await readTheme();
  const changed =
    afterToggle.dataTheme !== before.dataTheme ||
    afterToggle.hasDarkClass !== before.hasDarkClass ||
    afterToggle.bg !== before.bg;
  record('T1 切换主题生效', changed, JSON.stringify(afterToggle));

  if (changed) {
    const darkOk = await auditPages('T-dark', { checkOverflow: false });
    record('T2 深色主题全页面无报错', darkOk);

    // 切回原主题
    resetErrors();
    await page.goto(`${BASE}/dashboard/overview`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    const btn2 = page
      .locator('header .theme-toggle, header [aria-label="dark"], header [aria-label="light"]')
      .first();
    if ((await btn2.count()) > 0) {
      await btn2.click();
      await page.waitForTimeout(1500);
    }
    const restored = await readTheme();
    const isLight =
      restored.dataTheme === before.dataTheme &&
      restored.hasDarkClass === before.hasDarkClass;
    record('T3 还原原主题', isLight, JSON.stringify(restored));
  } else {
    record('T2 深色主题全页面无报错', false, '主题未切换，跳过');
    record('T3 还原原主题', true, '未切换无需还原');
  }
}

// ============================================================
// U. 窄屏适配（768 / 390）
// ============================================================
console.log('\n--- U. 窄屏适配 ---');

const originalViewport = page.viewportSize();

await page.setViewportSize({ width: 768, height: 900 });
await page.waitForTimeout(800);
const tabletOk = await auditPages('U-768', { checkOverflow: true });
record('U1 768px 平板宽度无溢出无报错', tabletOk);

await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(800);
const phoneOk = await auditPages('U-390', { checkOverflow: true });
record('U2 390px 手机宽度无溢出无报错', phoneOk);

// 还原视口
await page.setViewportSize(originalViewport ?? { width: 1440, height: 900 });

// ---------- 汇总 ----------
record(
  '全程无未捕获的页面错误',
  pageErrors.length === 0,
  pageErrors.slice(0, 3).join(' | ').slice(0, 200),
);

await browser.close();

const failed = steps.filter((s) => !s.ok);
console.log(`\n结果：${steps.length - failed.length}/${steps.length} 通过`);
if (failed.length) {
  console.log('失败项：');
  for (const f of failed) console.log(`  - ${f.name}`);
}
process.exit(failed.length === 0 ? 0 : 1);
