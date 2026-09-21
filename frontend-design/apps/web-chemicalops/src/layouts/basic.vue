<script lang="ts" setup>
import type { NotificationItem } from '@vben/layouts';

import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { AuthenticationLoginExpiredModal } from '@vben/common-ui';
import { useWatermark } from '@vben/hooks';
import { BasicLayout, LockScreen, Notification, UserDropdown } from '@vben/layouts';
import { preferences, usePreferences } from '@vben/preferences';
import { useAccessStore, useUserStore } from '@vben/stores';

import {
  getNotificationListApi,
  getUnreadCountApi,
  markAllNotificationsReadApi,
  markNotificationReadApi,
} from '#/api';
import { useAuthStore } from '#/store';
import LoginForm from '#/views/_core/authentication/login.vue';

const router = useRouter();
const userStore = useUserStore();
const authStore = useAuthStore();
const accessStore = useAccessStore();
const { destroyWatermark, updateWatermark } = useWatermark();
const { isDark } = usePreferences();

const notifications = ref<NotificationItem[]>([]);
const unreadCount = ref(0);

const showDot = computed(() => unreadCount.value > 0);

/** 顶部用户菜单：只保留与当前系统相关的入口 */
const menus = computed(() => [
  {
    handler: () => {
      router.push({ name: 'Overview' });
    },
    icon: 'lucide:layout-dashboard',
    text: '运营总览',
  },
  {
    handler: () => {
      router.push({ name: 'NotificationCenter' });
    },
    icon: 'lucide:bell',
    text: '站内通知',
  },
]);

const avatar = computed(
  () => userStore.userInfo?.avatar || preferences.app.defaultAvatar,
);

/** 展示当前用户的主要角色，便于确认登录身份 */
const roleText = computed(() => {
  const roles = userStore.userRoles ?? [];
  return roles.length > 0 ? roles.join(' / ') : '';
});

async function handleLogout() {
  await authStore.logout(false);
}

/** 把后端通知转成布局组件需要的结构 */
async function loadNotifications() {
  try {
    const [list, count] = await Promise.all([
      getNotificationListApi({ page: 1, page_size: 10 }),
      getUnreadCountApi(),
    ]);
    unreadCount.value = count.unread_count;
    notifications.value = list.items.map((item) => ({
      // 后端通知没有头像，布局组件要求该字段存在，传空串走默认样式
      avatar: '',
      date: item.created_at,
      id: item.id,
      isRead: item.is_read === 1,
      message: item.content,
      title: item.title,
    }));
  } catch {
    // 通知加载失败不影响主流程
  }
}

async function markRead(id: number | string) {
  const numericId = Number(id);
  try {
    await markNotificationReadApi(numericId);
    const item = notifications.value.find((entry) => entry.id === numericId);
    if (item) {
      item.isRead = true;
    }
    unreadCount.value = Math.max(unreadCount.value - 1, 0);
  } catch {
    // 忽略单条已读失败
  }
}

async function handleMakeAll() {
  try {
    await markAllNotificationsReadApi();
    notifications.value.forEach((item) => (item.isRead = true));
    unreadCount.value = 0;
  } catch {
    // 忽略
  }
}

function remove(id: number | string) {
  // 后端不提供删除通知接口，这里只从当前列表移除
  notifications.value = notifications.value.filter(
    (item) => item.id !== id,
  );
}

function handleNoticeClear() {
  notifications.value = [];
}

function viewAll() {
  router.push({ name: 'NotificationCenter' });
}

const handleClick = (item: NotificationItem) => {
  if (item.link) {
    router.push({ path: item.link });
  }
};

onMounted(loadNotifications);

watch(
  () => ({
    content: preferences.app.watermarkContent,
    enable: preferences.app.watermark,
    isDark: isDark.value,
  }),
  async ({ content, enable, isDark: isDarkValue }) => {
    if (enable) {
      const watermarkColor = isDarkValue
        ? 'rgba(255, 255, 255, 0.12)'
        : 'rgba(0, 0, 0, 0.12)';

      await updateWatermark({
        advancedStyle: {
          colorStops: [
            { color: watermarkColor, offset: 0 },
            { color: watermarkColor, offset: 1 },
          ],
          type: 'linear',
        },
        content:
          content ||
          `${userStore.userInfo?.username ?? ''} - ${userStore.userInfo?.realName ?? ''}`,
      });
    } else {
      destroyWatermark();
    }
  },
  { immediate: true },
);
</script>

<template>
  <BasicLayout
    :avatar
    :text="userStore.userInfo?.realName"
    @clear-preferences-and-logout="handleLogout"
    @logout="handleLogout"
  >
    <template #user-dropdown>
      <UserDropdown
        :avatar
        :menus
        :text="userStore.userInfo?.realName"
        :description="roleText"
        @clear-preferences-and-logout="handleLogout"
        @logout="handleLogout"
      />
    </template>
    <template #notification>
      <Notification
        :dot="showDot"
        :notifications="notifications"
        @clear="handleNoticeClear"
        @make-all="handleMakeAll"
        @read="(item) => item.id && markRead(item.id)"
        @remove="(item) => item.id && remove(item.id)"
        @on-click="handleClick"
        @view-all="viewAll"
      />
    </template>
    <template #extra>
      <AuthenticationLoginExpiredModal
        v-model:open="accessStore.loginExpired"
        :avatar
      >
        <LoginForm />
      </AuthenticationLoginExpiredModal>
    </template>
    <template #lock-screen>
      <LockScreen :avatar @to-login="handleLogout" />
    </template>
  </BasicLayout>
</template>
