<script lang="ts" setup>
import type { AuthApi } from '#/api/core/auth';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { IconifyIcon } from '@vben/icons';

import {
  Button,
  Card,
  Input,
  message,
  Modal,
  Spin,
  Tag,
} from 'antdv-next';

import {
  changePasswordApi,
  getCurrentUserApi,
  getDepartmentApi,
  updateProfileApi,
} from '#/api';
import { USER_STATUS_DICT } from '#/constants/dictionary';
import AvatarPicker from '#/components/avatar-picker.vue';
import { useAuthStore } from '#/store';
import { formatDateTime } from '#/utils/format';

defineOptions({ name: 'UserProfile' });

const authStore = useAuthStore();
const currentUser = ref<AuthApi.CurrentUser>();
const departmentName = ref('');
const loading = ref(false);
const saving = ref(false);
const avatarUploading = ref(false);

// 可编辑资料字段
const displayName = ref('');
const email = ref('');
const phone = ref('');

// 修改密码
const passwordVisible = ref(false);
const changingPassword = ref(false);
const oldPassword = ref('');
const newPassword = ref('');
const confirmPassword = ref('');
const avatarInitial = computed(() =>
  (currentUser.value?.display_name || currentUser.value?.username || '用')
    .slice(0, 1)
    .toUpperCase(),
);

async function load() {
  loading.value = true;
  try {
    currentUser.value = await getCurrentUserApi();
    displayName.value = currentUser.value.display_name;
    email.value = currentUser.value.email ?? '';
    phone.value = currentUser.value.phone ?? '';
    departmentName.value = currentUser.value.department_id
      ? `部门 #${currentUser.value.department_id}`
      : '未分配部门';
    if (
      currentUser.value.department_id &&
      currentUser.value.permission_codes.includes('system.departments.read')
    ) {
      try {
        const department = await getDepartmentApi(currentUser.value.department_id);
        departmentName.value = department.department_name;
      } catch {
        // 部门可能已停用或权限发生变化，保留编号作为可靠的回退展示。
      }
    }
  } finally {
    loading.value = false;
  }
}

async function onAvatarChange(value: null | string) {
  avatarUploading.value = true;
  try {
    currentUser.value = await updateProfileApi({ avatar_base64: value });
    await authStore.fetchUserInfo();
    message.success(value ? '头像已更新' : '头像已移除');
  } catch {
    // 请求层已展示错误，保留原头像。
  } finally {
    avatarUploading.value = false;
  }
}

async function onSaveProfile() {
  if (!displayName.value.trim()) {
    message.warning('昵称不能为空');
    return;
  }
  saving.value = true;
  try {
    currentUser.value = await updateProfileApi({
      display_name: displayName.value.trim(),
      email: email.value.trim() || null,
      phone: phone.value.trim() || null,
    });
    // 同步顶栏昵称与水印等派生展示
    await authStore.fetchUserInfo();
    message.success('资料已保存');
  } catch {
    // 请求层已统一弹出后端错误，这里保持页面状态供修正
  } finally {
    saving.value = false;
  }
}

function openPasswordModal() {
  oldPassword.value = '';
  newPassword.value = '';
  confirmPassword.value = '';
  passwordVisible.value = true;
}

async function onChangePassword() {
  if (!oldPassword.value) {
    message.warning('请输入原密码');
    return;
  }
  if (newPassword.value.length < 8) {
    message.warning('新密码至少 8 位');
    return;
  }
  if (newPassword.value !== confirmPassword.value) {
    message.warning('两次输入的新密码不一致');
    return;
  }
  changingPassword.value = true;
  try {
    await changePasswordApi({
      new_password: newPassword.value,
      old_password: oldPassword.value,
    });
    passwordVisible.value = false;
    message.success('密码已修改，请使用新密码重新登录', 5);
    await authStore.logout(true, false);
  } catch {
    // 原密码错误等由请求层提示，弹窗保持打开
  } finally {
    changingPassword.value = false;
  }
}

onMounted(load);
</script>

<template>
  <Page auto-content-height>
    <Spin :spinning="loading">
      <div class="profile-page mx-auto max-w-6xl space-y-5 pb-6">
        <section
          class="profile-hero rounded-2xl bg-[#102a49] p-7 text-white sm:p-8"
          style="background-image: linear-gradient(115deg, #102a49, #123b68 65%, #0b2746)"
        >
          <div class="profile-hero-pattern" aria-hidden="true"></div>
          <div class="relative flex flex-wrap items-center gap-5">
            <img
              v-if="currentUser?.avatar"
              :src="currentUser.avatar"
              alt="个人头像"
              class="size-20 rounded-2xl border-2 border-white/70 object-cover shadow-lg"
            />
            <div
              v-else
              class="flex size-20 items-center justify-center rounded-2xl border border-white/30 bg-white/15 text-3xl font-semibold text-white"
            >
              {{ avatarInitial }}
            </div>
            <div class="min-w-0 flex-1">
              <h1 class="m-0 text-2xl font-semibold text-white sm:text-3xl">
                {{ currentUser?.display_name || '个人中心' }}
              </h1>
              <p class="mt-2 text-sm text-slate-200">
                @{{ currentUser?.username || '-' }}
                <span class="mx-2 text-white/40">/</span>
                {{ departmentName }}
              </p>
            </div>
            <Tag :color="USER_STATUS_DICT.color(currentUser?.status)">
              {{ USER_STATUS_DICT.label(currentUser?.status) }}
            </Tag>
          </div>
          <div class="profile-hero-meta relative mt-7 flex flex-wrap gap-x-8 gap-y-2 border-t border-white/20 pt-4 text-xs text-slate-200">
            <span>账号编号 #{{ currentUser?.id ?? '-' }}</span>
            <span>角色 {{ currentUser?.role_codes?.length ?? 0 }} 个</span>
            <span>权限 {{ currentUser?.permission_codes?.length ?? 0 }} 项</span>
          </div>
        </section>

        <div class="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.8fr)]">
        <!-- 个人信息 -->
        <Card class="profile-card" title="基本资料">
          <div class="space-y-6">
            <AvatarPicker :value="currentUser?.avatar" :loading="avatarUploading" @update:value="onAvatarChange" />

            <div class="profile-facts grid gap-4 rounded-xl p-4 sm:grid-cols-2">
              <div>
                <div class="profile-fact-label">账号名</div>
                <div class="font-medium">{{ currentUser?.username ?? '-' }}</div>
              </div>
              <div>
                <div class="profile-fact-label">所属部门</div>
                <div class="font-medium">{{ departmentName }}</div>
              </div>
              <div class="sm:col-span-2">
                <div class="profile-fact-label">已分配角色</div>
                <div v-if="currentUser?.role_codes?.length" class="flex flex-wrap gap-1">
                  <Tag v-for="role in currentUser.role_codes" :key="role" color="blue">
                    {{ role }}
                  </Tag>
                </div>
                <div v-else class="font-medium">暂无角色</div>
              </div>
            </div>

            <div class="space-y-3">
              <div>
                <div class="mb-1 text-sm">
                  昵称 <span class="text-red-500">*</span>
                </div>
                <Input
                  v-model:value="displayName"
                  :maxlength="100"
                  placeholder="展示在顶栏与水印"
                />
              </div>
              <div>
                <div class="mb-1 text-sm">邮箱</div>
                <Input
                  v-model:value="email"
                  :maxlength="255"
                  placeholder="选填"
                />
              </div>
              <div>
                <div class="mb-1 text-sm">手机号</div>
                <Input
                  v-model:value="phone"
                  :maxlength="32"
                  placeholder="选填"
                />
              </div>
              <Button :loading="saving" type="primary" @click="onSaveProfile">
                保存资料
              </Button>
            </div>
          </div>
        </Card>

        <div class="space-y-5">
          <Card class="profile-card" title="账户安全">
            <div class="space-y-5">
              <div class="flex items-start gap-3 rounded-xl bg-sky-50 p-4 dark:bg-sky-950/40">
                <IconifyIcon icon="lucide:shield-check" class="mt-0.5 size-5 shrink-0 text-sky-700 dark:text-sky-300" />
                <div>
                  <div class="font-medium">登录密码</div>
                  <p class="text-muted-foreground mt-1 text-sm leading-6">
                    建议定期更新密码。修改时需验证当前密码，完成后请重新登录。
                  </p>
                </div>
              </div>
              <Button type="primary" @click="openPasswordModal">修改密码</Button>
              <p class="text-muted-foreground m-0 text-xs">
                忘记原密码时，请联系管理员重置。
              </p>
            </div>
          </Card>
          <Card class="profile-card" title="账户概览">
            <dl class="profile-overview m-0 space-y-4 text-sm">
              <div class="flex justify-between gap-4">
                <dt>创建时间</dt><dd>{{ formatDateTime(currentUser?.created_at) }}</dd>
              </div>
              <div class="flex justify-between gap-4">
                <dt>资料更新</dt><dd>{{ formatDateTime(currentUser?.updated_at) }}</dd>
              </div>
              <div class="flex justify-between gap-4">
                <dt>联系信息</dt><dd>{{ currentUser?.email || currentUser?.phone ? '已填写' : '待完善' }}</dd>
              </div>
            </dl>
          </Card>
        </div>
        </div>
      </div>

      <!-- 修改密码弹窗 -->
      <Modal
        v-model:open="passwordVisible"
        cancel-text="取消"
        ok-text="确认修改"
        title="修改登录密码"
        @ok="onChangePassword"
      >
        <div class="space-y-3 py-2">
          <div>
            <div class="mb-1 text-sm">
              原密码 <span class="text-red-500">*</span>
            </div>
            <Input.Password
              v-model:value="oldPassword"
              :maxlength="128"
              autocomplete="current-password"
              placeholder="当前登录密码"
            />
          </div>
          <div>
            <div class="mb-1 text-sm">
              新密码 <span class="text-red-500">*</span>
            </div>
            <Input.Password
              v-model:value="newPassword"
              :maxlength="128"
              autocomplete="new-password"
              placeholder="至少 8 位"
            />
          </div>
          <div>
            <div class="mb-1 text-sm">
              确认新密码 <span class="text-red-500">*</span>
            </div>
            <Input.Password
              v-model:value="confirmPassword"
              :maxlength="128"
              autocomplete="new-password"
              placeholder="再次输入新密码"
            />
          </div>
        </div>
      </Modal>
    </Spin>
  </Page>
</template>

<style scoped>
.profile-hero {
  position: relative;
  overflow: hidden;
  border-radius: 16px;
  padding: 28px 32px 24px;
  background: linear-gradient(115deg, #102a49, #123b68 65%, #0b2746);
  box-shadow: 0 14px 34px rgb(15 42 73 / 12%);
}

.profile-hero-pattern {
  position: absolute;
  inset: 0;
  opacity: 0.35;
  background:
    linear-gradient(90deg, transparent 97%, rgb(255 255 255 / 14%) 100%) 0 0 / 42px 42px,
    linear-gradient(0deg, transparent 97%, rgb(255 255 255 / 14%) 100%) 0 0 / 42px 42px,
    radial-gradient(circle at 86% 12%, rgb(40 156 220 / 48%), transparent 34%);
  pointer-events: none;
}

.profile-hero-meta {
  border-top: 1px solid rgb(255 255 255 / 17%);
  padding-top: 16px;
  color: #bcd2e8;
  font-size: 12px;
}

.profile-page :deep(.profile-card) {
  border-color: #e1e8f0;
  border-radius: 14px;
  box-shadow: 0 6px 24px rgb(21 48 78 / 4%);
}

.profile-page :deep(.profile-card .ant-card-head) {
  min-height: 56px;
  border-color: #edf1f6;
}

.profile-page :deep(.profile-card .ant-card-head-title) {
  color: #173452;
  font-size: 17px;
  font-weight: 650;
}

.profile-facts {
  background: #f4f8fc;
}

.profile-fact-label {
  margin-bottom: 5px;
  color: #69809a;
  font-size: 12px;
}

.profile-overview dt {
  color: #69809a;
}

.profile-overview dd {
  margin: 0;
  color: #173452;
  font-weight: 500;
  text-align: right;
}

:global(.dark) .profile-page :deep(.profile-card) {
  border-color: #29415a;
}

:global(.dark) .profile-page :deep(.profile-card .ant-card-head-title),
:global(.dark) .profile-overview dd {
  color: #e9f2fb;
}

:global(.dark) .profile-facts {
  background: #182b40;
}

@media (max-width: 640px) {
  .profile-hero {
    padding: 24px;
  }
}
</style>
