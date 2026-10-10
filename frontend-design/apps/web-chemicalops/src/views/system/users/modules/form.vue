<script lang="ts" setup>
import type { SystemUserApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenDrawer } from '@vben/common-ui';
import { useUserStore } from '@vben/stores';

import { useVbenForm } from '#/adapter/form';
import { createUserApi, updateUserApi } from '#/api';

import { useCreateFormSchema, useUpdateFormSchema } from '../data';

const { hasAccessByCodes } = useAccess();
const canConfirm = computed(() => hasAccessByCodes(['system.users.write']));
const emit = defineEmits(['success']);

const id = ref<number>();
const isCurrentUser = ref(false);
const userStore = useUserStore();

/**
 * 新增与编辑使用不同的表单结构：
 * 新增必须填账号名和初始密码；编辑时账号名只读、密码留空即不修改。
 */
const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: [],
  showDefaultActions: false,
  wrapperClass: 'grid-cols-1 sm:grid-cols-2',
});

const [Drawer, drawerApi] = useVbenDrawer<null | SystemUserApi.SystemUser>({
  async onConfirm() {
    if (!canConfirm.value) return;
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    const values = await formApi.getValues();
    drawerApi.lock();
    try {
      if (id.value) {
        // 后端未返回用户已有的角色，因此留空时不提交 role_ids，
        // 否则会被 replace_user_roles 清空；密码同理。
        const payload: Record<string, any> = { ...values };
        if (!payload.password) {
          delete payload.password;
        }
        if (
          !Array.isArray(payload.role_ids) ||
          payload.role_ids.length === 0
        ) {
          delete payload.role_ids;
        }
        await updateUserApi(id.value, payload);
      } else {
        await createUserApi(values as SystemUserApi.UserPayload);
      }
      emit('success');
      drawerApi.close();
    } catch {
      // 请求层已统一弹出后端返回的中文错误，这里保持弹窗打开，
      // 让用户修正后重新提交；不吞掉异常会导致未捕获的 Promise 拒绝。
    } finally {
      drawerApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    const data = drawerApi.getData();
    id.value = data?.id;
    isCurrentUser.value = data?.id === Number(userStore.userInfo?.userId);
    // schema 随模式切换，切换后需要重置校验状态
    formApi.setState({
      schema: data ? useUpdateFormSchema(isCurrentUser.value) : useCreateFormSchema(),
    });
    formApi.reset();

    await nextTick();
    if (data) {
      formApi.setValues({
        department_id: data.department_id ?? undefined,
        display_name: data.display_name,
        email: data.email ?? undefined,
        phone: data.phone ?? undefined,
        // 详情接口返回已绑定角色，回填后用户可增删；留空提交仍保持不变
        role_ids: data.role_ids?.length ? data.role_ids : undefined,
        status: data.status,
        username: data.username,
      });
    }
  },
});

const title = computed(() => (id.value ? '编辑用户' : '新增用户'));

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :show-confirm-button="canConfirm" :title="title" class="w-[680px] max-w-[100vw]">
    <div
      v-if="id"
      class="bg-accent text-muted-foreground mb-4 rounded-md px-3 py-2 text-xs"
    >
      角色留空表示保持原有角色不变；密码留空表示不修改密码。<template v-if="isCurrentUser">当前账号的角色和启用状态不能在此修改。</template>
    </div>
    <Form />
  </Drawer>
</template>
