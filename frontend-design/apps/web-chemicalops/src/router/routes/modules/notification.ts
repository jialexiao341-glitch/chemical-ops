import type { RouteRecordRaw } from 'vue-router';

/**
 * 站内通知。
 *
 * 后端按业务事件自动创建通知，用户只能读取和处理发给自己的通知，
 * 因此这里不设权限码，登录即可访问。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: {
      authority: ['system.notifications.read'],
      hideInMenu: true,
      icon: 'lucide:bell',
      order: 98,
      title: '站内通知',
    },
    name: 'NotificationCenter',
    path: '/notifications',
    component: () => import('#/views/notification/index.vue'),
  },
];

export default routes;
