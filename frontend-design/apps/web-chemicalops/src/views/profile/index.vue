<script lang="ts" setup>
import type { AuthApi } from '#/api/core/auth';

import { onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Button,
  Card,
  Descriptions,
  DescriptionsItem,
  Input,
  message,
  Modal,
  Spin,
  Tag,
} from 'antdv-next';

import {
  changePasswordApi,
  getCurrentUserApi,
  updateProfileApi,
} from '#/api';
import { USER_STATUS_DICT } from '#/constants/dictionary';
import { useAuthStore } from '#/store';

defineOptions({ name: 'UserProfile' });

const authStore = useAuthStore();
const currentUser = ref<AuthApi.CurrentUser>();
const loading = ref(false);
const saving = ref(false);

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

async function load() {
  loading.value = true;
  try {
    currentUser.value = await getCurrentUserApi();
    displayName.value = currentUser.value.display_name;
    email.value = currentUser.value.email ?? '';
    phone.value = currentUser.value.phone ?? '';
  } finally {
    loading.value = false;
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
    message.success('密码已修改，旧令牌到期前仍有效，建议退出重新登录', 5);
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
      <div class="mx-auto grid max-w-5xl grid-cols-1 gap-4 md:grid-cols-2">
        <!-- 个人信息 -->
        <Card title="个人信息">
          <div class="space-y-5">
            <Descriptions bordered :column="1" size="small">
              <DescriptionsItem label="用户名">
                {{ currentUser?.username ?? '-' }}
              </DescriptionsItem>
              <DescriptionsItem label="状态">
                <Tag
                  :color="USER_STATUS_DICT.color(currentUser?.status)"
                >
                  {{ USER_STATUS_DICT.label(currentUser?.status) }}
                </Tag>
              </DescriptionsItem>
              <DescriptionsItem label="部门">
                {{
                  currentUser?.department_id
                    ? `#${currentUser.department_id}`
                    : '未分配'
                }}
              </DescriptionsItem>
              <DescriptionsItem label="角色">
                <template
                  v-if="(currentUser?.role_codes ?? []).length > 0"
                >
                  <Tag
                    v-for="role in currentUser?.role_codes"
                    :key="role"
                    color="blue"
                  >
                    {{ role }}
                  </Tag>
                </template>
                <span v-else>-</span>
              </DescriptionsItem>
              <DescriptionsItem label="权限数">
                {{ currentUser?.permission_codes?.length ?? 0 }} 项
              </DescriptionsItem>
            </Descriptions>

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

        <!-- 安全设置 -->
        <Card title="安全设置">
          <div class="space-y-4">
            <div class="text-muted-foreground text-sm leading-6">
              <p>· 登录密码至少 8 位，修改需验证原密码</p>
              <p>· 系统使用无状态 JWT：修改成功后，旧令牌在到期前仍可使用</p>
              <p>· 忘记原密码时，请联系管理员在「用户管理」中重置</p>
            </div>
            <Button type="primary" @click="openPasswordModal">
              修改密码
            </Button>
          </div>
        </Card>
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
