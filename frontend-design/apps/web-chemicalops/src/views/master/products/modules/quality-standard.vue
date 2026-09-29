<script lang="ts" setup>
import type { ProductApi } from '#/api';

import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';
import { Alert, Button, Input, InputNumber, Select, Spin, Tag, message } from 'antdv-next';

import { createProductQualityStandardApi, getProductQualityStandardsApi } from '#/api';

type CriterionDraft = Omit<ProductApi.QualityCriterion, 'aliases' | 'maximum' | 'minimum'> & {
  aliases_text: string;
  maximum: null | number;
  minimum: null | number;
};

const product = ref<null | ProductApi.Product>(null);
const versions = ref<ProductApi.QualityStandard[]>([]);
const sourceReference = ref('');
const criteria = ref<CriterionDraft[]>([]);
const loading = ref(false);
const title = computed(() => `检测标准 · ${product.value?.product_name ?? ''}`);

/** 生成供新增检测项目使用的空白表单数据。 */
function emptyCriterion(): CriterionDraft {
  return { name: '', aliases_text: '', kind: 'NUMERIC', unit: null, minimum: null, maximum: null, expected_text: null };
}

/** 以现行版本填充草稿，保留旧版本供创建新版本时参考。 */
function useLatestAsDraft() {
  const latest = versions.value[0];
  sourceReference.value = latest?.source_reference ?? '';
  criteria.value = latest
    ? latest.criteria.map((item) => ({
        name: item.name,
        aliases_text: item.aliases.join('、'),
        kind: item.kind,
        unit: item.unit,
        minimum: item.minimum == null ? null : Number(item.minimum),
        maximum: item.maximum == null ? null : Number(item.maximum),
        expected_text: item.expected_text,
      }))
    : [emptyCriterion()];
}

const [Drawer, drawerApi] = useVbenDrawer<null | ProductApi.Product>({
  /** 打开抽屉时加载该产品的标准版本并准备编辑草稿。 */
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    product.value = drawerApi.getData() ?? null;
    versions.value = [];
    if (!product.value) return;
    loading.value = true;
    try {
      versions.value = await getProductQualityStandardsApi(product.value.id);
      useLatestAsDraft();
    } finally {
      loading.value = false;
    }
  },
  /** 校验草稿内容，保存为新版本并更新版本列表。 */
  async onConfirm() {
    if (!product.value) return;
    const source = sourceReference.value.trim();
    if (!source || !criteria.value.length) {
      message.warning('请填写标准来源和至少一个检测项目');
      return;
    }
    const rows: ProductApi.QualityCriterion[] = criteria.value.map((item) => ({
      name: item.name.trim(),
      aliases: item.aliases_text.split(/[、,，;；]/).map((name) => name.trim()).filter(Boolean),
      kind: item.kind,
      unit: item.kind === 'NUMERIC' ? item.unit?.trim() || null : null,
      minimum: item.kind === 'NUMERIC' && item.minimum != null ? String(item.minimum) : null,
      maximum: item.kind === 'NUMERIC' && item.maximum != null ? String(item.maximum) : null,
      expected_text: item.kind === 'TEXT' ? item.expected_text?.trim() || null : null,
    }));
    if (rows.some((item) => !item.name || (item.kind === 'NUMERIC' && (!item.unit || (item.minimum == null && item.maximum == null))) || (item.kind === 'TEXT' && !item.expected_text))) {
      message.warning('请补齐每项的名称、单位和限值，或文本预期值');
      return;
    }
    if (versions.value[0]?.source_reference === source && JSON.stringify(versions.value[0]?.criteria) === JSON.stringify(rows)) {
      message.info('内容与现行版本相同，无需创建新版本');
      return;
    }
    drawerApi.lock();
    try {
      const created = await createProductQualityStandardApi(product.value.id, { source_reference: source, criteria: rows });
      versions.value.unshift(created);
      message.success(`检测标准第 ${created.version_no} 版已保存`);
      drawerApi.close();
    } catch {
      // 请求层已显示校验或权限错误。
    } finally {
      drawerApi.unlock();
    }
  },
});

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[860px] max-w-[100vw]">
    <Spin :spinning="loading">
    <div class="space-y-5 pb-4">
      <Alert type="info" show-icon message="由产品维护人员录入经审核的标准" description="每次保存生成新版本。报告核对将引用当时的版本；检测标准不会自动放行库存。" />
      <div v-if="versions.length" class="rounded-lg border border-border px-4 py-3 text-sm">
        <div class="flex flex-wrap items-center gap-2">
          <span class="font-medium">现行版本</span>
          <Tag color="blue">第 {{ versions[0]?.version_no }} 版</Tag>
          <span class="text-muted-foreground">{{ versions[0]?.source_reference }}</span>
        </div>
        <p class="mt-2 text-xs text-muted-foreground">已保存 {{ versions.length }} 个版本。下方以现行版本为基础创建新版本，旧版本不会被覆盖。</p>
        <details class="mt-3 border-t border-border pt-2">
          <summary class="cursor-pointer text-xs font-medium">查看历史版本</summary>
          <div v-for="version in versions" :key="version.id" class="mt-2 border-t border-border pt-2 text-xs first:border-0">
            <div class="font-medium">第 {{ version.version_no }} 版 · {{ version.source_reference }}</div>
            <div class="mt-1 text-muted-foreground">{{ version.criteria.map((item) => item.name).join('、') }}</div>
          </div>
        </details>
      </div>
      <div>
        <label class="mb-1 block text-sm font-medium" for="standard-source">标准来源与版本号</label>
        <Input id="standard-source" v-model:value="sourceReference" :maxlength="255" placeholder="例如：经审核的产品技术协议编号及版本" />
      </div>
      <section class="space-y-3" aria-label="检测项目">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold">检测项目</h3>
          <Button size="small" @click="criteria.push(emptyCriterion())">添加项目</Button>
        </div>
        <div v-for="(item, index) in criteria" :key="index" class="rounded-lg border border-border p-4">
          <div class="grid gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block text-xs text-muted-foreground">项目名称</label>
              <Input v-model:value="item.name" :maxlength="100" :aria-label="`第 ${index + 1} 项名称`" placeholder="如：纯度" />
            </div>
            <div>
              <label class="mb-1 block text-xs text-muted-foreground">报告中的其他叫法</label>
              <Input v-model:value="item.aliases_text" :aria-label="`第 ${index + 1} 项别名`" placeholder="多个名称用顿号分隔" />
            </div>
            <div>
              <label class="mb-1 block text-xs text-muted-foreground">判定类型</label>
              <Select v-model:value="item.kind" class="w-full" :aria-label="`第 ${index + 1} 项判定类型`" :options="[{ label: '数值范围', value: 'NUMERIC' }, { label: '文本一致', value: 'TEXT' }]" />
            </div>
            <template v-if="item.kind === 'NUMERIC'">
              <div>
                <label class="mb-1 block text-xs text-muted-foreground">单位</label>
                <Input v-model:value="item.unit" :aria-label="`第 ${index + 1} 项单位`" placeholder="如：%" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-muted-foreground">下限（可留空）</label>
                <InputNumber v-model:value="item.minimum" class="w-full" :precision="6" :aria-label="`第 ${index + 1} 项下限`" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-muted-foreground">上限（可留空）</label>
                <InputNumber v-model:value="item.maximum" class="w-full" :precision="6" :aria-label="`第 ${index + 1} 项上限`" />
              </div>
            </template>
            <div v-else>
              <label class="mb-1 block text-xs text-muted-foreground">预期文本</label>
              <Input v-model:value="item.expected_text" :aria-label="`第 ${index + 1} 项预期文本`" placeholder="如：无色透明" />
            </div>
          </div>
          <div class="mt-3 flex justify-end"><Button size="small" danger @click="criteria.splice(index, 1)">移除项目</Button></div>
        </div>
      </section>
      <p class="text-xs text-muted-foreground">数值单位需与报告写法一致；系统暂不自动换算。单位或项目无法识别时，验收页会提示人工核对。</p>
    </div>
    </Spin>
  </Drawer>
</template>
