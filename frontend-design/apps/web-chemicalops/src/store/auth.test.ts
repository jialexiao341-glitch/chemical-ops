import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
const mocks = vi.hoisted(() => {
  const access = { accessToken: null as null | string, accessCodes: [] as string[], loginExpired: false,
    setAccessToken(value: null | string) { this.accessToken = value; },
    setAccessCodes(value: string[]) { this.accessCodes = value; },
    setLoginExpired(value: boolean) { this.loginExpired = value; } };
  const user = { userInfo: null as unknown, setUserInfo(value: unknown) { this.userInfo = value; } };
  return { access, user, replace: vi.fn(), getCurrentUserApi: vi.fn(), loginApi: vi.fn(), logoutApi: vi.fn() };
});
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: mocks.replace, push: vi.fn(), currentRoute: { value: { fullPath: '/dashboard' } } }) }));
vi.mock('@vben/constants', () => ({ LOGIN_PATH: '/auth/login' }));
vi.mock('@vben/preferences', () => ({ preferences: { app: { defaultHomePath: '/dashboard' } } }));
vi.mock('@vben/stores', () => ({ useAccessStore: () => mocks.access, useUserStore: () => mocks.user,
  resetAllStores: () => { mocks.access.accessToken = null; mocks.access.accessCodes = []; mocks.user.userInfo = null; } }));
vi.mock('antdv-next', () => ({ notification: { success: vi.fn() } }));
vi.mock('#/api', () => mocks);
vi.mock('#/locales', () => ({ $t: (key: string) => key }));
import { useAuthStore } from './auth';

describe('半登录状态清理', () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); mocks.access.accessToken = 'old'; mocks.access.accessCodes = ['old-permission']; mocks.user.userInfo = { username: 'old' }; });
  it('JWT 成功但用户信息失败时清 token、权限和用户资料', async () => {
    mocks.loginApi.mockResolvedValue({ access_token: 'new' });
    mocks.getCurrentUserApi.mockRejectedValue(new Error('me failed'));
    const store = useAuthStore();
    await expect(store.authLogin({ username: 'test', password: 'test' })).rejects.toThrow('me failed');
    expect(mocks.access.accessToken).toBeNull(); expect(mocks.access.accessCodes).toEqual([]);
    expect(mocks.user.userInfo).toBeNull(); expect(store.loginLoading).toBe(false);
    expect(mocks.replace).toHaveBeenCalledWith({ path: '/auth/login', query: {} });
  });
  it('刷新恢复失败同样退出，不保留旧权限', async () => {
    mocks.getCurrentUserApi.mockRejectedValue(new Error('network'));
    await expect(useAuthStore().fetchUserInfo()).rejects.toThrow('network');
    expect(mocks.access.accessToken).toBeNull(); expect(mocks.access.accessCodes).toEqual([]);
    expect(mocks.logoutApi).not.toHaveBeenCalled();
  });
});
