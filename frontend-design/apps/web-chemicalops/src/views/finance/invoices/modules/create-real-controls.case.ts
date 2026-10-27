import { createApp, defineComponent, h, nextTick } from 'vue';
import { expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ hooks: {} as any }));
vi.mock('@vben/access', () => ({ useAccess: () => ({ hasAccessByCodes: () => true }) }));
vi.mock('@vben/common-ui', () => ({ useVbenModal: (hooks: any) => {
  mocks.hooks = hooks;
  return [defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) }), { lock: vi.fn(), unlock: vi.fn(), close: vi.fn() }];
} }));
vi.mock('#/api', () => ({ createInvoiceApi: vi.fn(), parseInvoiceFileApi: vi.fn(),
  getReconciliationListApi: async () => ({ items: [{ id: 8, status: 'CONFIRMED', reconciliation_no: 'FR-8', total_amount: '500', currency_code: 'CNY' }] }) }));

import Create from './create.vue';

it('实际表单控件可以打开并呈现', async () => {
  const host = document.createElement('div'); document.body.append(host);
  const errors: unknown[] = [];
  const app = createApp(Create); app.config.errorHandler = (err) => errors.push(err);
  app.mount(host);
  await mocks.hooks.onOpenChange(true); await nextTick();
  expect(errors).toEqual([]);
  expect(host.textContent).toContain('上传并解析发票文件');
  expect(host.querySelector('input')).not.toBeNull();
  app.unmount(); host.remove();
}, 60000);
