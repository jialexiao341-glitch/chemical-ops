/**
 * 系统管理写路径实测（对应 docs/新版前端说明.md 第七节第 8 项）：
 *   P 用户：新增 → 编辑回填与改名 → 停用（二次确认）
 *   Q 角色：新增 → 编辑改名 → 停用
 *   R 部门：新增 → 编辑改名 → 停用
 *   S 权限：新增（类型下拉）→ 物理删除
 *
 * 交互约定与 module-flow / finance-flow 一致：弹层内 primary 优先点击、
 * 行操作按 rowid 跨表 fallback（vxe fixed 列拆表）、两字中文按钮正则匹配。
 *
 * 前置：后端 8888 与前端 3000 均在运行。
 * 用法：
 *   $env:SMOKE_PASSWORD='你的密码'; node scripts/system-write-test.mjs
 */
import { mkdirSync } from 'node:fs';

import { chromium } from 'playwright';

const BASE = process.env.SMOKE_BASE ?? 'http://localhost:3000';
const USER = process.env.SMOKE_USER ?? 'system_admin';
const PASSWORD = process.env.SMOKE_PASSWORD;
if (!PASSWORD) {
  console.error(
    '请通过环境变量 SMOKE_PASSWORD 提供登录密码（不写入仓库）。\n' +
      "PowerShell: $env:SMOKE_PASSWORD='***'; node scripts/system-write-test.mjs",
  );
  process.exit(1);
}
const OUT = 'C:/self_project/ChemicalOps/.cache/shots';
mkdirSync(OUT, { recursive: true });

const stamp = Date.now().toString().slice(-8);
const USERNAME = `autotest_${stamp}`;
const DISPLAY_NAME = `自动化测试用户${stamp}`;
const ROLE_CODE = `ROLE_TEST_${stamp}`;
const ROLE_NAME = `测试角色${stamp}`;
const DEPT_CODE = `DEPT_TEST_${stamp}`;
const DEPT_NAME = `测试部门${stamp}`;
const PERM_CODE = `test.${stamp}.read`;
const PERM_NAME = `测试权限${stamp}`;
// 后端密码规则：8-128 位
const NEW_PASSWORD = `Test@${stamp}1`;

const steps = [];
function record(name, ok, detail = '') {
  steps.push({ name, ok });
  console.log(`${ok ? ' ok ' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
}

const writes = [];
const pageErrors = [];

function dumpDiagnostics() {
  console.log('\n=== 后端写请求 ===');
  console.log(writes.join('\n') || '(未捕获到写请求)');
  console.log('\n=== 浏览器 pageerror ===');
  console.log(pageErrors.join('\n') || '(无)');
}
process.on('uncaughtException', (e) => {
  console.error('\n脚本异常中止：', e.message);
  dumpDiagnostics();
  process.exit(1);
});

const browser = await chromium.launch({ channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1700, height: 1000 } });

page.on('pageerror', (e) => pageErrors.push(`[pageerror] ${e.message}`));
page.on('response', async (r) => {
  const req = r.request();
  const method = req.method();
  if (method === 'GET' || method === 'HEAD') return;
  const u = r.url();
  if (!u.includes('/api/v1/system/')) return;
  let body = '';
  try {
    body = (await r.text()).slice(0, 300);
  } catch {
    body = '(unreadable)';
  }
  const path = u.replace(/^.*\/api\/v1/, '');
  writes.push(`${r.status()} ${method} ${path} → ${body.slice(0, 140)}`);
});

// ---------- 通用工具 ----------

const CONFIRM_NAME =
  /^(确\s*认|确\s*定|提\s*交|保\s*存|停\s*用|删\s*除)$/;

function dialog(hasText = null) {
  let loc = page.locator('[role="dialog"]:visible');
  if (hasText) loc = loc.filter({ hasText });
  return loc.last();
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

async function gotoPage(path) {
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
}

function row(text) {
  return page.locator('tr', { hasText: text }).first();
}

async function waitForRow(text, timeout = 10_000) {
  try {
    await row(text).waitFor({ state: 'visible', timeout });
    return true;
  } catch {
    return false;
  }
}

async function dumpDialogs(tag) {
  const info = await page.evaluate(() => {
    const dialogs = [...document.querySelectorAll('[role="dialog"]')].map(
      (d) => ({
        buttons: [...d.querySelectorAll('button')]
          .map((b) => b.textContent?.trim())
          .filter(Boolean),
        title:
          d.querySelector('header, [role="heading"]')?.textContent?.trim() ??
          d.textContent?.slice(0, 60),
        visible: !!(d.offsetWidth || d.offsetHeight),
      }),
    );
    const toasts = [...document.querySelectorAll('[class*="message-notice"]')]
      .map((el) => el.textContent?.trim())
      .filter(Boolean);
    return { dialogs, toasts };
  });
  console.log(`       [diag:${tag}]`, JSON.stringify(info));
}

/**
 * 点击列表行操作：内联按钮优先（含 vxe fixed 列按 rowid 跨表 fallback），
 * 下拉兜底。
 */
async function rowAction(rowText, itemRe, expectedTitle = null) {
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  const r = row(rowText);
  if ((await r.count()) === 0) {
    await dumpDialogs(`row-missing:${rowText.slice(0, 20)}`);
    throw new Error(`列表里找不到「${rowText}」所在的行`);
  }

  let inlineBtn = r
    .locator('.table-operations button')
    .filter({ hasText: itemRe })
    .first();
  if ((await inlineBtn.count()) === 0) {
    inlineBtn = r.locator('button').filter({ hasText: itemRe }).first();
  }
  if ((await inlineBtn.count()) === 0) {
    const rowid =
      (await r.getAttribute('data-rowid')) ?? (await r.getAttribute('rowid'));
    if (rowid) {
      inlineBtn = page
        .locator(`tr[data-rowid="${rowid}"], tr[rowid="${rowid}"]`)
        .locator('button')
        .filter({ hasText: itemRe })
        .first();
    }
  }
  const hasInline = (await inlineBtn.count()) > 0;
  console.log(
    `       [rowAction] 目标="${rowText.slice(0, 24)}" 模式=${hasInline ? '内联' : '下拉'}`,
  );

  let clickedText;
  if (hasInline) {
    clickedText = ((await inlineBtn.textContent()) ?? '').trim();
    await inlineBtn.click();
  } else {
    let opBtn = r.locator('.table-operations button').last();
    if ((await opBtn.count()) === 0) {
      opBtn = r.locator('button').last();
    }
    if ((await opBtn.count()) === 0) {
      throw new Error(`「${rowText}」行没有操作按钮`);
    }
    await opBtn.click();
    const dropdown = page
      .locator('.ant-dropdown:not(.ant-dropdown-hidden)')
      .last();
    try {
      await dropdown.waitFor({ state: 'visible', timeout: 8000 });
    } catch {
      await dumpDialogs(`dropdown-not-open:${rowText.slice(0, 20)}`);
      throw new Error(`「${rowText}」的操作下拉没有打开`);
    }
    const target = dropdown.locator('button').filter({ hasText: itemRe }).first();
    if ((await target.count()) === 0) {
      const texts = await dropdown.locator('button').allTextContents();
      throw new Error(
        `操作菜单中没有匹配 ${itemRe} 的项，可选：${texts.join('/')}`,
      );
    }
    clickedText = ((await target.textContent()) ?? '').trim();
    await target.click();
  }
  await page.waitForTimeout(800);

  if (expectedTitle) {
    const opened = await page
      .locator('[role="dialog"]:visible')
      .filter({ hasText: expectedTitle })
      .count();
    if (opened === 0) {
      await dumpDialogs(`expect:${expectedTitle}`);
      throw new Error(`点击「${clickedText}」后未打开「${expectedTitle}」弹层`);
    }
  }
}

/** 弹层内点确认：primary 优先，文本正则兜底 */
async function clickConfirm(titleRe) {
  const dlg = dialog(titleRe);
  if ((await dlg.count()) === 0) {
    await dumpDialogs(`confirm-missing:${titleRe}`);
    throw new Error(`找不到弹层：${titleRe}`);
  }
  const primary = dlg.locator('button.ant-btn-primary').last();
  if ((await primary.count()) > 0) {
    console.log(`       [confirm] 点击 primary：${titleRe}`);
    await primary.click();
  } else {
    const btn = dlg.getByRole('button', { name: CONFIRM_NAME }).last();
    if ((await btn.count()) === 0) {
      await dumpDialogs(`confirm-no-btn:${titleRe}`);
      throw new Error(`弹层「${titleRe}」内没有可点的确认按钮`);
    }
    await btn.click();
  }
  await page.waitForTimeout(1500);
}

async function waitDialogClosed(hasText, timeout = 8000) {
  try {
    await page
      .locator('[role="dialog"]')
      .filter({ hasText })
      .waitFor({ state: 'hidden', timeout });
    return true;
  } catch {
    return false;
  }
}

/** 打开工具栏新建抽屉/弹窗 */
async function openCreate(btnName, titleRe) {
  await page.getByRole('button', { name: new RegExp(btnName) }).click();
  await page.waitForTimeout(2000);
  const opened = await page
    .locator('[role="dialog"]:visible')
    .filter({ hasText: titleRe })
    .count();
  if (opened === 0) {
    await dumpDialogs(`open-create:${titleRe}`);
    throw new Error(`点击「${btnName}」后未打开「${titleRe}」弹层`);
  }
}

/**
 * CellOperation 的 delete 按钮是两层确认：先弹 Popconfirm 气泡
 * （"确定删除…吗？"），点确认后才触发页面的 Modal.confirm。
 * 这里先过 Popconfirm，再由 clickConfirm 处理 Modal。
 */
async function passPopconfirmAndConfirm(rowText, modalTitleRe) {
  await rowAction(rowText, /删\s*除/);
  // Popconfirm 渲染在 body 下的 popover，不在 [role=dialog] 里
  const popConfirm = page
    .locator(
      '.ant-popover:not(.ant-popover-hidden) button, .ant-popconfirm button',
    )
    .filter({ hasText: /^(确\s*定|确\s*认|OK)$/ })
    .last();
  try {
    await popConfirm.waitFor({ state: 'visible', timeout: 5000 });
    await popConfirm.click();
    console.log('       [popconfirm] 已确认删除气泡');
  } catch {
    // 没有 Popconfirm（或已直接进入 Modal）则继续
    console.log('       [popconfirm] 未出现，直接等 Modal');
  }
  await page.waitForTimeout(1000);
  // 此时应出现页面级 Modal（停用/删除二次确认）
  const modalOpened = await page
    .locator('[role="dialog"]:visible')
    .filter({ hasText: modalTitleRe })
    .count();
  if (modalOpened === 0) {
    await dumpDialogs(`after-popconfirm:${rowText.slice(0, 16)}`);
    throw new Error(`Popconfirm 后未出现「${modalTitleRe}」确认弹窗`);
  }
  await clickConfirm(modalTitleRe);
}

// ---------- 登录 ----------
await login();
record('登录成功', true, page.url());

// ============================================================
// P. 系统用户：新增 → 编辑 → 停用
// ============================================================
console.log('\n--- P. 系统用户 ---');
await gotoPage('/system/users');

await openCreate('新增用户', '新增用户');
{
  const dlg = dialog('新增用户');
  await dlg.locator('input[name="username"]').fill(USERNAME);
  await dlg.locator('input[name="password"]').fill(NEW_PASSWORD);
  await dlg.locator('input[name="display_name"]').fill(DISPLAY_NAME);
  await clickConfirm('新增用户');
  const closed = await waitDialogClosed('新增用户');
  const appeared = await waitForRow(USERNAME);
  record('P1 新增用户', closed && appeared, USERNAME);
}
if (!(await waitForRow(USERNAME))) throw new Error('新用户未出现在列表，中止');

// 编辑：回填校验 + 改显示姓名
const NEW_DISPLAY = `${DISPLAY_NAME}改`;
// CellOperation 的 edit 码文案来自 locale common.edit = 「修改」
await rowAction(USERNAME, /修\s*改/, '编辑用户');
{
  const dlg = dialog('编辑用户');
  await page.waitForTimeout(800);
  const prefilled = await dlg.locator('input[name="display_name"]').inputValue();
  record('P2 编辑抽屉正确回填', prefilled === DISPLAY_NAME, `display_name="${prefilled}"`);
  await dlg.locator('input[name="display_name"]').fill(NEW_DISPLAY);
  await clickConfirm('编辑用户');
  const closed = await waitDialogClosed('编辑用户');
  await page.waitForTimeout(1500);
  const updated = (await row(USERNAME).getByText(NEW_DISPLAY).count()) > 0;
  record('P3 编辑保存并在列表反映', closed && updated);
}
await page.screenshot({ path: `${OUT}/system-P-user.png` });

// 停用（CellOperation delete：Popconfirm → Modal 两层确认）
await passPopconfirmAndConfirm(USERNAME, '停用用户');
await page.waitForTimeout(2000);
record(
  'P4 停用用户（两层确认）',
  writes.some((w) => w.includes(`/users/`) && w.includes('DELETE')) &&
    (await row(USERNAME).getByText(/停用|INACTIVE/).count()) > 0,
);

// ============================================================
// Q. 角色：新增 → 编辑 → 停用
// ============================================================
console.log('\n--- Q. 角色 ---');
await gotoPage('/system/roles');

await openCreate('新增角色', '新增角色');
{
  const dlg = dialog('新增角色');
  await dlg.locator('input[name="role_code"]').fill(ROLE_CODE);
  await dlg.locator('input[name="role_name"]').fill(ROLE_NAME);
  await clickConfirm('新增角色');
  const closed = await waitDialogClosed('新增角色');
  const appeared = await waitForRow(ROLE_CODE);
  record('Q1 新增角色', closed && appeared, ROLE_CODE);
}
if (!(await waitForRow(ROLE_CODE))) throw new Error('新角色未出现在列表，中止');

const NEW_ROLE_NAME = `${ROLE_NAME}改`;
await rowAction(ROLE_CODE, /修\s*改/, '编辑角色');
{
  const dlg = dialog('编辑角色');
  await page.waitForTimeout(800);
  const prefilled = await dlg.locator('input[name="role_name"]').inputValue();
  record('Q2 编辑抽屉正确回填', prefilled === ROLE_NAME, `role_name="${prefilled}"`);
  await dlg.locator('input[name="role_name"]').fill(NEW_ROLE_NAME);
  await clickConfirm('编辑角色');
  const closed = await waitDialogClosed('编辑角色');
  await page.waitForTimeout(1500);
  const updated = (await row(ROLE_CODE).getByText(NEW_ROLE_NAME).count()) > 0;
  record('Q3 编辑保存并在列表反映', closed && updated);
}

await passPopconfirmAndConfirm(ROLE_CODE, '停用角色');
await page.waitForTimeout(2000);
record(
  'Q4 停用角色（两层确认）',
  writes.some((w) => w.includes(`/roles/`) && w.includes('DELETE')) &&
    (await row(ROLE_CODE).getByText(/停用|INACTIVE/).count()) > 0,
);
await page.screenshot({ path: `${OUT}/system-Q-role.png` });

// ============================================================
// R. 部门：新增 → 编辑 → 停用
// ============================================================
console.log('\n--- R. 部门 ---');
await gotoPage('/system/departments');

await openCreate('新增部门', '新增部门');
{
  const dlg = dialog('新增部门');
  await dlg.locator('input[name="department_code"]').fill(DEPT_CODE);
  await dlg.locator('input[name="department_name"]').fill(DEPT_NAME);
  await clickConfirm('新增部门');
  const closed = await waitDialogClosed('新增部门');
  const appeared = await waitForRow(DEPT_CODE);
  record('R1 新增部门', closed && appeared, DEPT_CODE);
}
if (!(await waitForRow(DEPT_CODE))) throw new Error('新部门未出现在列表，中止');

const NEW_DEPT_NAME = `${DEPT_NAME}改`;
await rowAction(DEPT_CODE, /修\s*改/, '编辑部门');
{
  const dlg = dialog('编辑部门');
  await page.waitForTimeout(800);
  const prefilled = await dlg.locator('input[name="department_name"]').inputValue();
  record('R2 编辑抽屉正确回填', prefilled === DEPT_NAME, `department_name="${prefilled}"`);
  await dlg.locator('input[name="department_name"]').fill(NEW_DEPT_NAME);
  await clickConfirm('编辑部门');
  const closed = await waitDialogClosed('编辑部门');
  await page.waitForTimeout(1500);
  const updated = (await row(DEPT_CODE).getByText(NEW_DEPT_NAME).count()) > 0;
  record('R3 编辑保存并在列表反映', closed && updated);
}

await passPopconfirmAndConfirm(DEPT_CODE, '停用部门');
await page.waitForTimeout(2000);
record(
  'R4 停用部门（两层确认）',
  writes.some((w) => w.includes(`/departments/`) && w.includes('DELETE')) &&
    (await row(DEPT_CODE).getByText(/停用|INACTIVE/).count()) > 0,
);
await page.screenshot({ path: `${OUT}/system-R-dept.png` });

// ============================================================
// S. 权限：新增 → 物理删除
// ============================================================
console.log('\n--- S. 权限 ---');
await gotoPage('/system/permissions');

await openCreate('新增权限', '新增权限');
{
  const dlg = dialog('新增权限');
  await dlg.locator('input[name="permission_code"]').fill(PERM_CODE);
  await dlg.locator('input[name="permission_name"]').fill(PERM_NAME);
  // permission_type 是 Select：表单内唯一下拉，选第一个选项（菜单）
  await dlg.locator('.ant-select').first().click();
  await page.waitForTimeout(800);
  const opt = page
    .locator('.ant-select-dropdown:visible .ant-select-item-option')
    .first();
  await opt.waitFor({ state: 'visible', timeout: 8000 });
  const typeLabel = ((await opt.textContent()) ?? '').trim();
  await opt.click();
  await page.waitForTimeout(400);
  await page.keyboard.press('Escape');
  // resource / action 后端必填；action 的 input 未渲染 name 属性，用 placeholder 定位
  await dlg.locator('input[name="resource"]').fill('test_resource');
  await dlg.locator('input[placeholder*="read / write"]').fill('read');
  await clickConfirm('新增权限');
  const closed = await waitDialogClosed('新增权限');
  const appeared = await waitForRow(PERM_CODE);
  record('S1 新增权限', closed && appeared, `${PERM_CODE} 类型=${typeLabel}`);
}
if (!(await waitForRow(PERM_CODE))) throw new Error('新权限未出现在列表，中止');

// 物理删除（已建测试权限，删掉不留垃圾）：Popconfirm → Modal 两层确认
await passPopconfirmAndConfirm(PERM_CODE, '删除权限');
await page.waitForTimeout(2000);
const permGone = !(await waitForRow(PERM_CODE, 5000));
record(
  'S2 删除权限（物理删除）',
  permGone && writes.some((w) => w.includes('/permissions/') && w.includes('DELETE')),
);
await page.screenshot({ path: `${OUT}/system-S-perm.png` });

// ---------- 汇总 ----------
record(
  '全程无未捕获的 Promise 拒绝',
  pageErrors.length === 0,
  pageErrors.slice(0, 3).join(' | ').slice(0, 200),
);

dumpDiagnostics();
await browser.close();

const failed = steps.filter((s) => !s.ok);
console.log(`\n结果：${steps.length - failed.length}/${steps.length} 通过`);
if (failed.length) {
  console.log('失败项：');
  for (const f of failed) console.log(`  - ${f.name}`);
}
process.exit(failed.length === 0 ? 0 : 1);
