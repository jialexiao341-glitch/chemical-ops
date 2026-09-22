import type { RouteRecordRaw } from 'vue-router';

/**
 * 个人中心。
 *
 * 入口在右上角头像菜单，不出现在侧栏（hideInMenu）；
 * 数据是登录者本人的，只要求登录态，不设业务权限码。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: {
      hideInMenu: true,
      icon: 'lucide:user-round',
      title: '个人中心',
    },
    name: 'Profile',
    path: '/profile',
    component: () => import('#/views/profile/index.vue'),
  },
];

export default routes;
