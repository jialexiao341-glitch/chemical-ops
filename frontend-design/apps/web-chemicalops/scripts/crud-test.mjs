/**
 * 写路径实测：以「化学品」为样板跑通一整套增删改查。
 *
 * 覆盖：
 *   A 必填校验（空表单提交应被拦截）
 *   B 失败处理（重复 CAS 应弹后端中文提示、抽屉保持打开、且不产生未捕获的 Promise 拒绝）
 *   C 新增（用唯一 CAS，应成功落库）
 *   D 编辑（回填正确、保存生效）
 *   E 停用（软删除，默认跳过，需 CRUD_DELETE=1）
 *
 * 前置：后端 8888 与前端 3000 均在运行。
 * 用法：node frontend-design/scripts/crud-test.mjs
 */
import { mkdirSync } from 'node:fs';

import { chromium } from 'playwright';

const BASE = process.env.SMOKE_BASE ?? 'http://localhost:3000';
const USER = process.env.SMOKE_USER ?? 'system_admin';
const PASSWORD = process.env.SMOKE_PASSWORD ?? 'ChemicalOps@2026';
const OUT = 'C:/self_project/ChemicalOps/.cache/shots';

mkdirSync(OUT, { recursive: true });

const stamp = Date.now().toString().slice(-8);
const NAME = `自动化测试化学品${stamp}`;
// 唯一 CAS，避免与库中既有数据冲突（首次跑曾因复用 64-17-5 被后端 409 拒绝）
const UNIQUE_CAS = `9${stamp.slice(0, 4)}-${stamp.slice(4, 6)}-${Math.floor(Math.random() * 10)}`;

const steps = [];
function record(name, ok, detail = '') {
  steps.push({ name, ok });
  console.log(`${ok ? ' ok ' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
}

const browser = await chromium.launch({ channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });

const pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(`[pageerror] ${e.message}`));

const writes = [];
page.on('response', async (r) => {
  const req = r.request();
  const u = r.url();
  if (
    u.includes('/api/v1/chemicals') &&
    ['DELETE', 'PATCH', 'POST'].includes(req.method())
  ) {
    let body = '';
    try {
      body = (await r.text()).slice(0, 160);
    } catch {
      body = '(unreadable)';
    }
    writes.push(`${r.status()} ${req.method()} ${u.replace(/^.*\/api\/v1/, '')} → ${body}`);
  }
});

const search = async (kw) => {
  await page.fill('input[name="keyword"]', kw);
  await page.getByRole('button', { name: /搜\s*索/ }).click();
  await page.waitForTimeout(2500);
};

// ---------- 登录 ----------
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);
const loginInputs = page.locator('input:visible');
await loginInputs.nth(0).fill(USER);
await loginInputs.nth(1).fill(PASSWORD);
await page.keyboard.press('Enter');
await page.waitForTimeout(5000);

await page.goto(`${BASE}/master/chemicals`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);

// ---------- A. 必填校验 ----------
await page.getByRole('button', { name: '新增化学品' }).click();
await page.waitForTimeout(1500);
await page.getByRole('button', { name: /确\s*认/ }).click();
await page.waitForTimeout(1500);

const drawerOpenAfterEmpty = await page
  .locator('input[name="chemical_name"]')
  .isVisible();
const validationMsg = await page
  .locator('text=/请输入化学品名称/')
  .first()
  .isVisible()
  .catch(() => false);
record(
  'A 必填校验：空表单被拦截',
  drawerOpenAfterEmpty && validationMsg,
  `抽屉仍开=${drawerOpenAfterEmpty} 提示可见=${validationMsg}`,
);
await page.screenshot({ path: `${OUT}/crud-A-validation.png` });

// ---------- B. 失败处理：重复 CAS ----------
pageErrors.length = 0;
await page.fill('input[name="chemical_name"]', '重复CAS测试');
await page.fill('input[name="cas_no"]', '64-17-5'); // 库中已存在
await page.getByRole('button', { name: /确\s*认/ }).click();
await page.waitForTimeout(1200);

// 提示只显示 3 秒，要在消失前抓
const toastText = await page.evaluate(() =>
  [...document.querySelectorAll('[class*="message-notice"], [class*="message"]')]
    .map((el) => el.textContent?.trim())
    .filter(Boolean)
    .join(' | '),
);
await page.waitForTimeout(2500);

const drawerKeptOpen = await page
  .locator('input[name="chemical_name"]')
  .isVisible();
const toastShown = toastText.includes('已存在') || toastText.includes('CAS');
record('B 失败处理：抽屉保持打开', drawerKeptOpen);
record(
  'B 失败处理：展示后端中文错误',
  toastShown,
  `提示文本="${toastText.slice(0, 80)}"`,
);
await page.screenshot({ path: `${OUT}/crud-B-conflict.png` });

// 关掉这个抽屉，下面用全新会话验证成功路径（失败后继续在旧抽屉里重试的
// 分支由 scripts/diag-retry.mjs 单独覆盖）
await page.getByRole('button', { name: /取\s*消/ }).click();
await page.waitForTimeout(1500);

// ---------- C. 新增（唯一 CAS） ----------
await page.getByRole('button', { name: '新增化学品' }).click();
await page.waitForTimeout(1500);
await page.fill('input[name="chemical_name"]', NAME);
await page.fill('input[name="cas_no"]', UNIQUE_CAS);
await page.fill('input[name="english_name"]', 'AutoTest Chemical');
await page.fill('input[name="molecular_weight"]', '46.068');
await page.fill('input[name="hazard_class"]', '易燃液体');
await page.getByRole('button', { name: /确\s*认/ }).click();
await page.waitForTimeout(3500);

const closedAfterCreate = !(await page
  .locator('input[name="chemical_name"]')
  .isVisible()
  .catch(() => false));
await search(NAME);
const createdRow = page.locator('tr', { hasText: NAME });
const createdCount = await createdRow.count();
record('C 新增：提交后抽屉关闭', closedAfterCreate);
record('C 新增：列表中查到新记录', createdCount > 0, `匹配行数=${createdCount}`);
await page.screenshot({ path: `${OUT}/crud-C-created.png` });

// ---------- D. 编辑 ----------
if (createdCount > 0) {
  await createdRow.first().getByText('修改').click();
  await page.waitForTimeout(2000);
  const prefilled = await page.inputValue('input[name="chemical_name"]');
  record('D 编辑：表单正确回填', prefilled === NAME, `chemical_name="${prefilled}"`);
  await page.screenshot({ path: `${OUT}/crud-D-prefill.png` });

  const NEW_HAZARD = '易燃液体（已修改）';
  await page.fill('input[name="hazard_class"]', NEW_HAZARD);
  await page.getByRole('button', { name: /确\s*认/ }).click();
  await page.waitForTimeout(3500);

  await search(NAME);
  const hazardShown = await page
    .locator('tr', { hasText: NAME })
    .first()
    .getByText(NEW_HAZARD)
    .count();
  record('D 编辑：修改已保存并反映到列表', hazardShown > 0);
  await page.screenshot({ path: `${OUT}/crud-D-updated.png` });

  // ---------- E. 停用（默认跳过）----------
  if (process.env.CRUD_DELETE === '1') {
    try {
      await page
        .locator('tr', { hasText: NAME })
        .first()
        .getByText('删除')
        .click({ timeout: 10_000 });
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `${OUT}/crud-E1-popconfirm.png` });

      // 打印确认框内的按钮文本，便于定位（antd 会给两个汉字插空格）
      const popBtns = await page.evaluate(() =>
        [...document.querySelectorAll('[class*="popconfirm"] button, [class*="popover"] button')]
          .map((b) => b.textContent)
          .filter(Boolean),
      );
      console.log('      Popconfirm 按钮:', JSON.stringify(popBtns));

      const confirmBtn = page
        .locator('[class*="popconfirm"] button, [class*="popover"] button')
        .filter({ hasText: /确\s*定|确\s*认/ })
        .first();
      if (await confirmBtn.count()) {
        await confirmBtn.click({ timeout: 10_000 });
      } else {
        await page
          .getByRole('button', { name: /确\s*[定认]/ })
          .last()
          .click({ timeout: 10_000 });
      }
      await page.waitForTimeout(3500);

      await search(NAME);
      const disabled = await page
        .locator('tr', { hasText: NAME })
        .first()
        .getByText('停用')
        .count();
      record('E 停用：状态变为「停用」', disabled > 0);
      await page.screenshot({ path: `${OUT}/crud-E2-disabled.png` });
    } catch (error) {
      await page.screenshot({ path: `${OUT}/crud-E-fail.png` });
      record('E 停用：状态变为「停用」', false, String(error).split('\n')[0]);
    }
  } else {
    console.log(' skip  E 停用（软删除）— 设置 CRUD_DELETE=1 可执行');
  }
}

// ---------- 未捕获的 Promise 拒绝 ----------
record(
  '无未捕获的 Promise 拒绝',
  pageErrors.length === 0,
  pageErrors.length ? pageErrors.join(' | ').slice(0, 200) : '',
);

console.log('\n=== 后端写请求 ===');
console.log(writes.length ? writes.join('\n') : '(未捕获到写请求)');
console.log('\n=== 浏览器 pageerror ===');
console.log(pageErrors.length ? pageErrors.join('\n') : '(无)');

await browser.close();

const failed = steps.filter((s) => !s.ok);
console.log(`\n结果：${steps.length - failed.length}/${steps.length} 通过`);
console.log(`测试数据：${NAME} / CAS ${UNIQUE_CAS}`);
process.exit(failed.length === 0 ? 0 : 1);
