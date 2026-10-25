<script lang="ts" setup>
import type { NotificationApi } from '#/api';

import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';
import { useAccess } from '@vben/access';

import { Button, Card, Empty, message, Spin, Switch, Table, Tag } from 'antdv-next';

import {
  getNotificationListApi,
  markAllNotificationsReadApi,
  markNotificationReadApi,
} from '#/api';
import { formatDateTime } from '#/utils/format';

defineOptions({ name: 'NotificationCenter' });
const router = useRouter();
const { hasAccessByCodes } = useAccess();
const canWriteNotifications = computed(() => hasAccessByCodes(['system.notifications.write']));
const canUseAiWorkspace = computed(() => hasAccessByCodes(['ai.workspace.read']));

const items = ref<NotificationApi.Notification[]>([]);
const total = ref(0);
const unreadOnly = ref(false);
const loading = ref(false);
const page = ref(1);
const pageSize = ref(20);

const unreadCount = computed(
  () => items.value.filter((item) => item.is_read !== 1).length,
);

async function load() {
  loading.value = true;
  try {
    const res = await getNotificationListApi({
      page: page.value,
      page_size: pageSize.value,
      unread_only: unreadOnly.value || undefined,
    });
    items.value = res.items;
    total.value = res.total;
  } finally {
    loading.value = false;
  }
}

async function onRead(row: NotificationApi.Notification) {
  if (!canWriteNotifications.value) return;
  if (row.is_read === 1) {
    return;
  }
  await markNotificationReadApi(row.id);
  await load();
}

async function onReadAll() {
  if (!canWriteNotifications.value) return;
  const res = await markAllNotificationsReadApi();
  message.success(`已标记 ${res.updated_count} 条通知为已读`);
  await load();
}

function onToggleUnread(value: boolean | string | number) {
  unreadOnly.value = Boolean(value);
  page.value = 1;
  load();
}

function onUseSuggestion(row: NotificationApi.Notification) {
  if (!canUseAiWorkspace.value) {
    message.warning('当前账号没有 AI 工作台权限');
    return;
  }
  const instruction = row.content.match(/建议指令：([\s\S]+)$/)?.[1]?.trim() || row.content;
  void router.push({ path: '/ai/workspace', query: { prompt: instruction } });
}

const columns = [
  { key: 'title', title: '标题', minWidth: 220 },
  { key: 'content', title: '内容', minWidth: 320 },
  { key: 'notification_type', title: '类型', width: 140 },
  { key: 'created_at', title: '时间', width: 170 },
  { key: 'is_read', title: '状态', width: 90 },
  { key: '__action', title: '操作', width: 100 },
];

onMounted(load);
</script>

<template>
  <Page auto-content-height>
    <Card>
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-3">
          <span class="text-base font-semibold">站内通知</span>
          <Tag v-if="unreadCount > 0" color="error">
            {{ unreadCount }} 条未读
          </Tag>
        </div>
        <div class="flex items-center gap-4">
          <label class="flex items-center gap-2 text-sm">
            <Switch :checked="unreadOnly" size="small" @change="onToggleUnread" />
            只看未读
          </label>
          <Button v-if="canWriteNotifications" :disabled="unreadCount === 0" @click="onReadAll">
            全部标记已读
          </Button>
        </div>
      </div>

      <Spin :spinning="loading">
        <Empty v-if="items.length === 0 && !loading" description="暂无通知" />
        <Table
          v-else
          :columns="columns"
          :data-source="items"
          :pagination="{
            current: page,
            pageSize,
            total,
            onChange: (p: number) => ((page = p), load()),
          }"
          row-key="id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'content'">
              <span class="text-muted-foreground">{{ record.content }}</span>
            </template>
            <template v-else-if="column.key === 'notification_type'">
              <Tag>{{ record.notification_type === 'OPERATION_SUGGESTION' ? '运营建议' : record.notification_type }}</Tag>
            </template>
            <template v-else-if="column.key === 'created_at'">
              {{ formatDateTime(record.created_at) }}
            </template>
            <template v-else-if="column.key === 'is_read'">
              <Tag :color="record.is_read === 1 ? 'default' : 'error'">
                {{ record.is_read === 1 ? '已读' : '未读' }}
              </Tag>
            </template>
            <template v-else-if="column.key === '__action'">
              <Button
                v-if="record.notification_type === 'OPERATION_SUGGESTION' && canUseAiWorkspace"
                size="small"
                type="link"
                @click="onUseSuggestion(record)"
              >
                让 Agent 处理
              </Button>
              <Button
                v-if="canWriteNotifications"
                :disabled="record.is_read === 1"
                size="small"
                type="link"
                @click="onRead(record)"
              >
                标记已读
              </Button>
            </template>
          </template>
        </Table>
      </Spin>
    </Card>
  </Page>
</template>
