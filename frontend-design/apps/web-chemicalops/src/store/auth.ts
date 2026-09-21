import type { Recordable, UserInfo } from '@vben/types';

import { ref } from 'vue';
import { useRouter } from 'vue-router';

import { LOGIN_PATH } from '@vben/constants';
import { preferences } from '@vben/preferences';
import { resetAllStores, useAccessStore, useUserStore } from '@vben/stores';

import { notification } from 'antdv-next';
import { defineStore } from 'pinia';

import { getCurrentUserApi, loginApi, logoutApi } from '#/api';
import { $t } from '#/locales';

/**
 * 把后端 CurrentUser 转换为 vben 的 BasicUserInfo。
 *
 * - `role_codes` 作为角色码写入 userInfo.roles，用于角色判断与展示。
 * - `permission_codes` 单独写入 accessStore.accessCodes，用于按钮级权限。
 */
function toUserInfo(current: {
  [key: string]: any;
  display_name: string;
  id: number;
  role_codes: string[];
  username: string;
}): UserInfo {
  return {
    avatar: '',
    displayName: current.display_name,
    departmentId: current.department_id ?? null,
    email: current.email ?? '',
    homePath: preferences.app.defaultHomePath,
    phone: current.phone ?? '',
    realName: current.display_name,
    roles: current.role_codes ?? [],
    userId: String(current.id),
    username: current.username,
  } as unknown as UserInfo;
}

export const useAuthStore = defineStore('auth', () => {
  const accessStore = useAccessStore();
  const userStore = useUserStore();
  const router = useRouter();

  const loginLoading = ref(false);

  /**
   * 登录：获取 JWT，再拉取当前用户与权限码。
   */
  async function authLogin(
    params: Recordable<any>,
    onSuccess?: () => Promise<void> | void,
  ) {
    let userInfo: null | UserInfo = null;
    try {
      loginLoading.value = true;
      const { access_token: accessToken } = await loginApi({
        password: params.password,
        username: params.username,
      });

      if (accessToken) {
        accessStore.setAccessToken(accessToken);

        // 后端没有独立的权限码接口，角色与权限都来自 /auth/me
        const currentUser = await getCurrentUserApi();
        userInfo = toUserInfo(currentUser);

        userStore.setUserInfo(userInfo);
        accessStore.setAccessCodes(currentUser.permission_codes ?? []);

        if (accessStore.loginExpired) {
          accessStore.setLoginExpired(false);
        } else {
          onSuccess
            ? await onSuccess?.()
            : await router.push(
                userInfo.homePath || preferences.app.defaultHomePath,
              );
        }

        if (userInfo?.realName) {
          notification.success({
            description: `${$t('authentication.loginSuccessDesc')}:${userInfo?.realName}`,
            duration: 3,
            title: $t('authentication.loginSuccess'),
          });
        }
      }
    } finally {
      loginLoading.value = false;
    }

    return {
      userInfo,
    };
  }

  async function logout(redirect: boolean = true) {
    try {
      await logoutApi();
    } catch {
      // JWT 无状态，退出接口失败不影响本地清理
    }
    resetAllStores();
    accessStore.setLoginExpired(false);

    await router.replace({
      path: LOGIN_PATH,
      query: redirect
        ? {
            redirect: encodeURIComponent(router.currentRoute.value.fullPath),
          }
        : {},
    });
  }

  /**
   * 刷新当前用户信息与权限码。用于刷新页面后恢复登录态。
   */
  async function fetchUserInfo() {
    const currentUser = await getCurrentUserApi();
    const userInfo = toUserInfo(currentUser);
    userStore.setUserInfo(userInfo);
    accessStore.setAccessCodes(currentUser.permission_codes ?? []);
    return userInfo;
  }

  function $reset() {
    loginLoading.value = false;
  }

  return {
    $reset,
    authLogin,
    fetchUserInfo,
    loginLoading,
    logout,
  };
});
