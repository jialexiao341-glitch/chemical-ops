<script lang="ts" setup>
import type { VbenFormSchema } from '@vben/common-ui';
import type { RegistrationPayload } from '#/api';

import { markRaw, ref } from 'vue';
import { useRouter } from 'vue-router';

import { AuthenticationRegister, z } from '@vben/common-ui';
import { message, Modal } from 'antdv-next';

import { getRegistrationRolesApi, registerApi } from '#/api';
import AvatarPicker from '#/components/avatar-picker.vue';

defineOptions({ name: 'Register' });
const router = useRouter();
const loading = ref(false);
const registrationRules = z.object({
  username: z.string().regex(/^(?=.*[A-Z])(?=.*[a-z])[A-Za-z0-9_]{8,16}$/, '账号名须为 8–16 位，仅含字母、数字或下划线，并同时包含大写和小写字母'),
  password: z.string().min(8, '密码须为 8–16 位，并同时包含大写和小写字母').max(16, '密码须为 8–16 位，并同时包含大写和小写字母')
    .regex(/[A-Z]/, '密码须为 8–16 位，并同时包含大写和小写字母').regex(/[a-z]/, '密码须为 8–16 位，并同时包含大写和小写字母'),
  display_name: z.string().trim().min(1, '请输入姓名').max(100, '姓名不能超过 100 字'),
  role_code: z.string().min(1, '请选择申请角色'),
  email: z.union([z.string().email('请输入有效邮箱'), z.literal('')]),
  phone: z.string().max(32, '手机号不能超过 32 位'),
});
const formSchema: VbenFormSchema[] = [
  { component: markRaw(AvatarPicker), fieldName: 'avatar_base64', label: '头像', modelPropName: 'value' },
  { component: 'VbenInput', fieldName: 'username', label: '账号名',
    componentProps: { 'aria-label': '账号名', autocomplete: 'username', placeholder: '请输入账号名' } },
  { component: 'VbenInput', fieldName: 'display_name', label: '姓名',
    componentProps: { 'aria-label': '姓名', autocomplete: 'name', placeholder: '请输入姓名', maxlength: 100 } },
  { component: 'VbenInputPassword', fieldName: 'password', label: '密码',
    componentProps: { 'aria-label': '密码', autocomplete: 'new-password', placeholder: '请输入密码' } },
  { component: 'VbenInputPassword', fieldName: 'confirm_password', label: '确认密码',
    componentProps: { 'aria-label': '确认密码', autocomplete: 'new-password', placeholder: '请再次输入密码' } },
  { component: 'ApiSelect', fieldName: 'role_code', label: '申请角色',
    componentProps: { api: getRegistrationRolesApi, labelField: 'role_name', valueField: 'role_code',
      'aria-label': '申请角色', class: 'w-full', showSearch: true, optionFilterProp: 'label', placeholder: '请选择申请角色（管理员除外）' } },
  { component: 'VbenInput', fieldName: 'email', label: '邮箱',
    componentProps: { 'aria-label': '邮箱', autocomplete: 'email', placeholder: '邮箱（选填）', maxlength: 255 } },
  { component: 'VbenInput', fieldName: 'phone', label: '手机号',
    componentProps: { 'aria-label': '手机号', autocomplete: 'tel', placeholder: '手机号（选填）', maxlength: 32 } },
];

async function submit(values: Record<string, any>) {
  if (loading.value) return;
  const parsed = registrationRules.safeParse({ username: values.username || '', password: values.password || '',
    display_name: values.display_name || '', role_code: values.role_code || '',
    email: values.email || '', phone: values.phone || '' });
  if (!parsed.success) {
    Modal.warning({ title: '注册信息不符合要求', content: [...new Set(parsed.error.issues.map((issue) => issue.message))].join('；') });
    return;
  }
  if (values.password !== values.confirm_password) {
    Modal.warning({ title: '请确认密码', content: '两次输入的密码不一致，请重新输入。' });
    return;
  }
  loading.value = true;
  try {
    await registerApi({ ...parsed.data, avatar_base64: values.avatar_base64 || undefined,
      email: parsed.data.email || undefined, phone: parsed.data.phone || undefined } as RegistrationPayload);
    message.success('注册申请已提交，管理员审批通过后即可登录', 6);
    await router.push('/auth/login');
  } catch {
    // 请求层展示错误，保留表单供修正。
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthenticationRegister :form-schema="formSchema" :loading="loading"
    sub-title="选择申请角色，管理员审批通过后即可登录。供应商门户账号获批后由管理员绑定供应商。"
    submit-button-text="提交注册申请" @submit="submit">
    <template #title>注册申请</template>
  </AuthenticationRegister>
</template>
