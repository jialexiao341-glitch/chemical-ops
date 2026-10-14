import type { RouteRecordRaw } from 'vue-router';

/**
 * 系统管理。
 * 后端没有菜单资源，这里的页面都对应真实的 RBAC 实体。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: {
      authority: [
        'system.users.read',
        'system.roles.read',
        'system.permissions.read',
        'system.departments.read',
        'SYS_ADMIN',
      ],
      icon: 'lucide:settings',
      order: 99,
      title: '系统管理',
    },
    name: 'System',
    path: '/system',
    children: [
      {
        name: 'SystemUser',
        path: 'users',
        component: () => import('#/views/system/users/index.vue'),
        meta: {
          authority: ['system.users.read'],
          icon: 'lucide:users',
          title: '用户管理',
        },
      },
      {
        name: 'SystemRole',
        path: 'roles',
        component: () => import('#/views/system/roles/index.vue'),
        meta: {
          authority: ['system.roles.read'],
          icon: 'lucide:user-cog',
          title: '角色管理',
        },
      },
      {
        name: 'SystemPermission',
        path: 'permissions',
        component: () => import('#/views/system/permissions/index.vue'),
        meta: {
          authority: ['system.permissions.read'],
          icon: 'lucide:key-round',
          title: '权限管理',
        },
      },
      {
        name: 'SystemDepartment',
        path: 'departments',
        component: () => import('#/views/system/departments/index.vue'),
        meta: {
          authority: ['system.departments.read'],
          icon: 'lucide:network',
          title: '部门管理',
        },
      },
      {
        name: 'SystemMonitoring',
        path: 'monitoring',
        component: () => import('#/views/system/monitoring/index.vue'),
        meta: {
          authority: ['SYS_ADMIN'],
          icon: 'lucide:activity',
          title: '运行监控',
        },
      },
    ],
  },
];

export default routes;
