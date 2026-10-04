import type { RouteRecordRaw } from 'vue-router';

/**
 * 主数据模块。
 *
 * `meta.authority` 使用后端权限码，与 `/auth/me` 返回的
 * `permission_codes` 对齐；用户缺少任一权限码时该菜单不会出现。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: {
      authority: [
        'master.chemicals.read',
        'master.products.read',
        'master.suppliers.read',
      ],
      icon: 'lucide:database',
      order: 2,
      title: '主数据',
    },
    name: 'MasterData',
    path: '/master',
    children: [
      {
        name: 'ChemicalList',
        path: 'chemicals',
        component: () => import('#/views/master/chemicals/index.vue'),
        meta: {
          authority: ['master.chemicals.read'],
          icon: 'lucide:flask-conical',
          title: '化学品',
        },
      },
      {
        name: 'TechnicalDocuments',
        path: 'technical-documents',
        component: () => import('#/views/master/technical-documents/index.vue'),
        meta: {
          authority: ['TECHNICAL', 'SYS_ADMIN'],
          icon: 'lucide:files',
          title: '技术资料',
        },
      },
      {
        name: 'ProductList',
        path: 'products',
        component: () => import('#/views/master/products/index.vue'),
        meta: {
          authority: ['master.products.read'],
          icon: 'lucide:package',
          title: '产品规格',
        },
      },
      {
        name: 'SupplierList',
        path: 'suppliers',
        component: () => import('#/views/master/suppliers/index.vue'),
        meta: {
          authority: ['master.suppliers.read'],
          icon: 'lucide:factory',
          title: '供应商',
        },
      },
    ],
  },
];

export default routes;
