<script lang="ts" setup>
import { ref } from 'vue';

import { IconifyIcon } from '@vben/icons';
import { Button, Modal } from 'antdv-next';

withDefaults(defineProps<{ disabled?: boolean; loading?: boolean; value?: null | string }>(), {
  disabled: false, loading: false, value: null,
});
const emit = defineEmits<{ 'update:value': [null | string] }>();
const avatarInput = ref<HTMLInputElement>();
const processing = ref(false);
const AVATAR_MAX_EDGE = 256;
const AVATAR_PICK_LIMIT = 10 * 1024 * 1024;

function readImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => { URL.revokeObjectURL(url); resolve(image); };
    image.onerror = () => { URL.revokeObjectURL(url); reject(new Error('图片解码失败')); };
    image.src = url;
  });
}

async function onAvatarFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  if (!['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(file.type)) {
    Modal.warning({ title: '头像格式不符合要求', content: '请选择 JPG、PNG、GIF 或 WebP 图片。' });
    return;
  }
  if (file.size > AVATAR_PICK_LIMIT) {
    Modal.warning({ title: '头像过大', content: '请选择不超过 10MB 的图片。' });
    return;
  }
  processing.value = true;
  try {
    const image = await readImage(file);
    const scale = Math.min(1, AVATAR_MAX_EDGE / Math.max(image.width, image.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.width * scale));
    canvas.height = Math.max(1, Math.round(image.height * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('无法处理图片，请重试');
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    emit('update:value', canvas.toDataURL('image/jpeg', 0.85));
  } catch (error) {
    Modal.warning({ title: '无法使用该头像', content: error instanceof Error ? error.message : '请选择其他图片' });
  } finally { processing.value = false; }
}
</script>

<template>
  <div class="flex items-center gap-4">
    <img v-if="value" :src="value" alt="头像" class="border-border size-16 rounded-full border object-cover" />
    <div v-else class="bg-accent text-muted-foreground flex size-16 items-center justify-center rounded-full">
      <IconifyIcon icon="lucide:user" class="size-7" />
    </div>
    <div class="min-w-0 space-y-1.5">
      <div class="text-muted-foreground text-xs">支持 JPG/PNG/GIF/WebP，最大 10MB，上传后自动压缩到 {{ AVATAR_MAX_EDGE }}px</div>
      <div class="flex gap-2">
        <Button :loading="loading || processing" :disabled="disabled" size="small" @click="avatarInput?.click()">{{ value ? '更换头像' : '上传头像' }}</Button>
        <Button v-if="value" danger size="small" :disabled="disabled || loading || processing" @click="emit('update:value', null)">移除</Button>
      </div>
    </div>
    <input ref="avatarInput" accept="image/jpeg,image/png,image/gif,image/webp" class="hidden" type="file" :disabled="disabled || loading || processing" @change="onAvatarFile" />
  </div>
</template>
