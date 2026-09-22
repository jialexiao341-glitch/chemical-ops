<script lang="ts" setup>
import type { OperationExceptionApi } from '#/api';

import { computed, ref } from 'vue';

import { useVbenDrawer, useVbenModal } from '@vben/common-ui';

import {
  Alert,
  Button,
  Descriptions,
  DescriptionsItem,
  Empty,
  Input,
  message,
  Modal,
  Select,
  Spin,
  Table,
  Tag,
} from 'antdv-next';

import {
  createCommentApi,
  getCommentListApi,
  getExceptionApi,
  getTaskListApi,
  getUserListApi,
  updateExceptionApi,
  updateTaskApi,
} from '#/api';
import {
  EXCEPTION_SEVERITY_DICT,
  EXCEPTION_STATUS_DICT,
  EXCEPTION_TYPE_DICT,
  PRIORITY_DICT,
  TASK_STATUS_DICT,
} from '#/constants/dictionary';
import { formatDateTime } from '#/utils/format';

import TaskForm from './task-form.vue';

const emit = defineEmits(['success']);

/**
 * 运营异常详情：基本信息 + 状态推进 + 指派 + 处理任务与处理记录。
 *
 * 状态流转按后端规则渲染可用按钮：
 *   OPEN → PROCESSING/CANCELLED；PROCESSING → RESOLVED/CANCELLED；
 *   RESOLVED → CLOSED（必填关闭说明）/PROCESSING；终态无操作。
 */
const detail = ref<OperationExceptionApi.Exception>();
const tasks = ref<OperationExceptionApi.Task[]>([]);
const loading = ref(false);
const acting = ref(false);
const userOptions = ref<Array<{ label: string; value: number }>>([]);
const ownerId = ref<number>();

// 任务处理记录面板
const selectedTask = ref<OperationExceptionApi.Task>();
const comments = ref<OperationExceptionApi.Comment[]>([]);
const commentsLoading = ref(false);
const commentText = ref('');

// 关闭异常 / 完成任务的说明输入
const noteVisible = ref(false);
const noteKind = ref<'close-exception' | 'complete-task'>('close-exception');
const noteText = ref('');
const noteTargetTask = ref<OperationExceptionApi.Task>();

const [TaskFormModal, taskFormApi] = useVbenModal({
  connectedComponent: TaskForm,
  destroyOnClose: true,
});

const [Drawer, drawerApi] = useVbenDrawer<
  null | OperationExceptionApi.Exception
>({
  footer: false,
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    const data = drawerApi.getData();
    detail.value = undefined;
    tasks.value = [];
    selectedTask.value = undefined;
    comments.value = [];
    noteVisible.value = false;
    if (!data?.id) {
      return;
    }
    loading.value = true;
    try {
      const exception = await reload(data.id);
      ownerId.value = exception?.owner_id ?? undefined;
      // 负责人下拉按需加载一次
      if (userOptions.value.length === 0) {
        const users = await getUserListApi({ page: 1, page_size: 100 });
        userOptions.value = users.items
          .filter((item) => !item.status || item.status === 'ACTIVE')
          .map((item) => ({
            label: `${item.display_name || item.username}（${item.username}）`,
            value: item.id,
          }));
      }
    } finally {
      loading.value = false;
    }
  },
});

async function reload(id?: number): Promise<OperationExceptionApi.Exception | undefined> {
  const exceptionId = id ?? detail.value?.id;
  if (!exceptionId) {
    return undefined;
  }
  const [exception, taskPage] = await Promise.all([
    getExceptionApi(exceptionId),
    getTaskListApi(exceptionId, { page: 1, page_size: 100 }),
  ]);
  detail.value = exception;
  tasks.value = taskPage.items;
  return exception;
}

/** 当前状态下可用的状态操作（与后端 service.update_exception 流转规则一致） */
const statusActions = computed<Array<{ label: string; status: string }>>(
  () => {
    const current = detail.value?.status ?? '';
    const targets: Record<string, Array<{ label: string; status: string }>> = {
      OPEN: [
        { label: '开始处理', status: 'PROCESSING' },
        { label: '取消异常', status: 'CANCELLED' },
      ],
      PROCESSING: [
        { label: '标记解决', status: 'RESOLVED' },
        { label: '取消异常', status: 'CANCELLED' },
      ],
      RESOLVED: [
        { label: '关闭异常', status: 'CLOSED' },
        { label: '重新打开', status: 'PROCESSING' },
      ],
    };
    return targets[current] ?? [];
  },
);

/** 异常是否已进入终态 */
const isTerminal = computed(() =>
  ['CANCELLED', 'CLOSED'].includes(detail.value?.status ?? ''),
);

async function patchException(data: OperationExceptionApi.ExceptionUpdate) {
  if (!detail.value?.id) {
    return;
  }
  acting.value = true;
  try {
    await updateExceptionApi(detail.value.id, data);
    message.success('异常已更新');
    await reload();
    emit('success');
  } catch {
    // 请求层已弹出错误
  } finally {
    acting.value = false;
  }
}

function onStatusAction(action: { label: string; status: string }) {
  if (action.status === 'CLOSED') {
    // 关闭必须填写关闭说明
    noteKind.value = 'close-exception';
    noteText.value = '';
    noteVisible.value = true;
    return;
  }
  if (action.status === 'CANCELLED') {
    Modal.confirm({
      content: `确认取消异常 ${detail.value?.exception_no ?? ''}？取消后不可再处理。`,
      okText: '取消异常',
      onOk: async () => {
        await patchException({ status: 'CANCELLED' });
      },
      title: '取消异常',
    });
    return;
  }
  void patchException({ status: action.status });
}

function onNoteConfirm() {
  if (!noteText.value.trim()) {
    message.warning(
      noteKind.value === 'close-exception' ? '请填写关闭说明' : '请填写完成说明',
    );
    return;
  }
  noteVisible.value = false;
  if (noteKind.value === 'close-exception') {
    void patchException({
      closing_note: noteText.value.trim(),
      status: 'CLOSED',
    });
    return;
  }
  const task = noteTargetTask.value;
  if (task) {
    void patchTask(task.id, {
      completion_note: noteText.value.trim(),
      status: 'COMPLETED',
    });
  }
}

async function onAssignOwner() {
  await patchException({ owner_id: ownerId.value ?? null });
}

async function patchTask(
  taskId: number,
  data: OperationExceptionApi.TaskUpdate,
) {
  if (!detail.value?.id) {
    return;
  }
  try {
    await updateTaskApi(detail.value.id, taskId, data);
    message.success('任务已更新');
    await reload();
    if (selectedTask.value?.id === taskId) {
      await loadComments(taskId);
    }
    emit('success');
  } catch {
    // 请求层已弹出错误
  }
}

function onTaskAction(
  task: OperationExceptionApi.Task,
  action: 'cancel' | 'complete' | 'reopen' | 'start',
) {
  if (action === 'complete') {
    noteKind.value = 'complete-task';
    noteText.value = task.completion_note ?? '';
    noteTargetTask.value = task;
    noteVisible.value = true;
    return;
  }
  if (action === 'cancel') {
    Modal.confirm({
      content: `确认取消任务「${task.title}」？`,
      okText: '取消任务',
      onOk: async () => {
        await patchTask(task.id, { status: 'CANCELLED' });
      },
      title: '取消任务',
    });
    return;
  }
  // start（OPEN→PROCESSING）与 reopen（COMPLETED→PROCESSING）目标一致
  void patchTask(task.id, { status: 'PROCESSING' });
}

async function loadComments(taskId: number) {
  if (!detail.value?.id) {
    return;
  }
  commentsLoading.value = true;
  try {
    const res = await getCommentListApi(detail.value.id, taskId, {
      page: 1,
      page_size: 100,
    });
    comments.value = res.items;
  } finally {
    commentsLoading.value = false;
  }
}

async function onSelectTask(task: OperationExceptionApi.Task) {
  selectedTask.value = task;
  commentText.value = '';
  await loadComments(task.id);
}

async function onAddComment() {
  if (!detail.value?.id || !selectedTask.value) {
    return;
  }
  if (!commentText.value.trim()) {
    message.warning('请填写处理记录');
    return;
  }
  try {
    await createCommentApi(
      detail.value.id,
      selectedTask.value.id,
      commentText.value.trim(),
    );
    message.success('处理记录已追加');
    commentText.value = '';
    await loadComments(selectedTask.value.id);
  } catch {
    // 请求层已弹出错误
  }
}

const taskColumns = [
  { key: 'title', title: '任务', minWidth: 200 },
  { key: 'priority', title: '优先级', width: 90 },
  {
    key: 'status',
    title: '状态',
    width: 100,
  },
  { key: 'due_at', title: '截止时间', width: 160 },
  { key: '__action', title: '操作', width: 200 },
];

function taskActions(task: OperationExceptionApi.Task) {
  const actions: Array<{ label: string; value: string }> = [];
  if (task.status === 'OPEN') {
    actions.push({ label: '开始处理', value: 'start' });
    actions.push({ label: '取消', value: 'cancel' });
  } else if (task.status === 'PROCESSING') {
    actions.push({ label: '完成', value: 'complete' });
    actions.push({ label: '取消', value: 'cancel' });
  } else if (task.status === 'COMPLETED') {
    actions.push({ label: '重新处理', value: 'reopen' });
  }
  return actions;
}

const titleText = computed(
  () => `异常详情 · ${detail.value?.exception_no ?? ''}`,
);

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="titleText" class="w-[1000px]">
    <TaskFormModal @success="reload()" />
    <Spin :spinning="loading">
      <Empty v-if="!detail && !loading" description="未找到该异常" />
      <div v-else-if="detail" class="space-y-5">
        <!-- 状态推进 -->
        <Alert
          :message="
            detail.status === 'OPEN'
              ? '异常待处理：可指派负责人并开始处理。'
              : detail.status === 'PROCESSING'
                ? '处理中：解决后请填写处理结论并标记解决。'
                : detail.status === 'RESOLVED'
                  ? '已解决：确认后关闭异常（关闭需填写关闭说明）。'
                  : '该异常已进入终态，不能再推进状态。'
          "
          :type="
            detail.status === 'OPEN'
              ? 'warning'
              : detail.status === 'PROCESSING'
                ? 'info'
                : detail.status === 'RESOLVED'
                  ? 'success'
                  : 'info'
          "
          show-icon
        />
        <div v-if="statusActions.length > 0" class="flex flex-wrap gap-2">
          <Button
            v-for="action in statusActions"
            :key="action.status"
            :danger="action.status === 'CANCELLED'"
            :loading="acting"
            :type="
              action.status === 'PROCESSING' || action.status === 'CLOSED'
                ? 'primary'
                : 'default'
            "
            @click="onStatusAction(action)"
          >
            {{ action.label }}
          </Button>
        </div>

        <Descriptions bordered :column="2" size="small">
          <DescriptionsItem label="异常编号">
            {{ detail.exception_no }}
          </DescriptionsItem>
          <DescriptionsItem label="状态">
            <Tag :color="EXCEPTION_STATUS_DICT.color(detail.status)">
              {{ EXCEPTION_STATUS_DICT.label(detail.status) }}
            </Tag>
          </DescriptionsItem>
          <DescriptionsItem label="类型">
            <Tag :color="EXCEPTION_TYPE_DICT.color(detail.exception_type)">
              {{ EXCEPTION_TYPE_DICT.label(detail.exception_type) }}
            </Tag>
          </DescriptionsItem>
          <DescriptionsItem label="严重级别">
            <Tag :color="EXCEPTION_SEVERITY_DICT.color(detail.severity)">
              {{ EXCEPTION_SEVERITY_DICT.label(detail.severity) }}
            </Tag>
          </DescriptionsItem>
          <DescriptionsItem label="来源">
            {{ detail.source_type }} #{{ detail.source_id }}
          </DescriptionsItem>
          <DescriptionsItem label="截止时间">
            {{ formatDateTime(detail.due_at) }}
          </DescriptionsItem>
          <DescriptionsItem :span="2" label="描述">
            {{ detail.description }}
          </DescriptionsItem>
          <DescriptionsItem
            v-if="detail.closing_note"
            :span="2"
            label="关闭说明"
          >
            {{ detail.closing_note }}
          </DescriptionsItem>
        </Descriptions>

        <!-- 指派负责人 -->
        <div
          v-if="!isTerminal"
          class="flex flex-wrap items-end gap-3 rounded-md border p-3"
        >
          <div class="min-w-[260px] flex-1">
            <div class="mb-2 text-sm">负责人</div>
            <Select
              v-model:value="ownerId"
              :options="userOptions"
              allow-clear
              class="w-full"
              placeholder="选择异常负责人"
              show-search
            />
          </div>
          <Button :loading="acting" @click="onAssignOwner">保存指派</Button>
          <Button type="primary" @click="taskFormApi.setData({ id: detail.id }).open()">
            新建处理任务
          </Button>
        </div>

        <!-- 处理任务 -->
        <div>
          <div class="mb-3 flex items-center justify-between">
            <span class="font-medium">
              处理任务（{{ tasks.length }}）
            </span>
            <span class="text-muted-foreground text-xs">
              点击任务查看处理记录
            </span>
          </div>
          <Empty v-if="tasks.length === 0" description="暂无处理任务" />
          <Table
            v-else
            :columns="taskColumns"
            :data-source="tasks"
            :pagination="false"
            row-key="id"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'priority'">
                <Tag :color="PRIORITY_DICT.color(record.priority)">
                  {{ PRIORITY_DICT.label(record.priority) }}
                </Tag>
              </template>
              <template v-else-if="column.key === 'status'">
                <Tag :color="TASK_STATUS_DICT.color(record.status)">
                  {{ TASK_STATUS_DICT.label(record.status) }}
                </Tag>
              </template>
              <template v-else-if="column.key === 'due_at'">
                {{ formatDateTime(record.due_at) }}
              </template>
              <template v-else-if="column.key === '__action'">
                <div class="flex flex-wrap gap-1">
                  <Button
                    size="small"
                    type="link"
                    @click.stop="onSelectTask(record)"
                  >
                    处理记录
                  </Button>
                  <Button
                    v-for="action in taskActions(record)"
                    :key="action.value"
                    :danger="action.value === 'cancel'"
                    size="small"
                    type="link"
                    @click.stop="onTaskAction(record, action.value as any)"
                  >
                    {{ action.label }}
                  </Button>
                </div>
              </template>
            </template>
          </Table>
        </div>

        <!-- 选中任务的处理记录 -->
        <div v-if="selectedTask" class="rounded-md border p-3">
          <div class="mb-3 flex items-center justify-between">
            <span class="font-medium">
              处理记录 · {{ selectedTask.title }}
            </span>
            <Button size="small" type="text" @click="selectedTask = undefined">
              收起
            </Button>
          </div>
          <Spin :spinning="commentsLoading">
            <Empty
              v-if="comments.length === 0"
              description="还没有处理记录"
            />
            <ul v-else class="mb-3 space-y-2">
              <li
                v-for="comment in comments"
                :key="comment.id"
                class="border-b border-dashed pb-2 text-sm last:border-0"
              >
                <div class="text-muted-foreground text-xs">
                  #{{ comment.commenter_id }} ·
                  {{ formatDateTime(comment.created_at) }}
                </div>
                <div class="mt-1 whitespace-pre-wrap">
                  {{ comment.content }}
                </div>
              </li>
            </ul>
            <div class="flex gap-2">
              <Input.TextArea
                v-model:value="commentText"
                :maxlength="2000"
                :rows="2"
                placeholder="追加处理记录（必填）"
              />
              <Button type="primary" @click="onAddComment">追加</Button>
            </div>
          </Spin>
        </div>

        <!-- 关闭说明 / 完成说明 输入弹窗 -->
        <Modal
          v-model:open="noteVisible"
          cancel-text="取消"
          ok-text="确认"
          :title="noteKind === 'close-exception' ? '关闭异常' : '完成任务'"
          @ok="onNoteConfirm"
        >
          <div class="py-2">
            <Alert
              :message="
                noteKind === 'close-exception'
                  ? '关闭异常必须填写关闭说明。'
                  : '完成任务必须填写完成说明。'
              "
              class="mb-3"
              show-icon
              type="info"
            />
            <Input.TextArea
              v-model:value="noteText"
              :maxlength="2000"
              :rows="4"
              :placeholder="
                noteKind === 'close-exception'
                  ? '请说明异常的处理结果与关闭原因'
                  : '请说明任务的完成情况'
              "
            />
          </div>
        </Modal>
      </div>
    </Spin>
  </Drawer>
</template>
