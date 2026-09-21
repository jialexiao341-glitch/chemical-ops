<script lang="ts" setup>
/**
 * 通用明细行编辑器。
 *
 * 采购申请、询价单等单据都包含「表头 + 若干明细行」的结构，
 * 这里把可编辑明细表抽成通用组件，各页面只描述列与新增行的默认值。
 */
import { computed, onMounted, ref, watch } from 'vue';

import { IconifyIcon } from '@vben/icons';

import {
  Button,
  DatePicker,
  Empty,
  Input,
  InputNumber,
  Select,
  Table,
  Tooltip,
} from 'antdv-next';
import { Plus } from '@vben/icons';

/** 明细列定义 */
export interface ItemsEditorColumn {
  /** 列宽 */
  width?: number | string;
  /** 编辑控件类型 */
  component: 'date' | 'input' | 'number' | 'select' | 'textarea';
  /** 控件属性 */
  componentProps?: Record<string, any>;
  /** 字段名 */
  field: string;
  /** 表头 */
  label: string;
  /** 选项，传函数可异步加载 */
  options?: Array<{ label: string; value: any }> | (() => Promise<any[]>);
  /** 是否必填，仅用于展示星号提示 */
  required?: boolean;
}

const props = withDefaults(
  defineProps<{
    columns: ItemsEditorColumn[];
    /** 新增行的默认值 */
    createRow: () => Record<string, any>;
    maxRows?: number;
    minRows?: number;
    modelValue: Record<string, any>[];
  }>(),
  {
    maxRows: 100,
    minRows: 1,
  },
);

const emit = defineEmits(['update:modelValue']);

/** 行唯一键字段，由组件内部维护，页面无需关心 */
const ROW_KEY = '__rowId';
let rowSeed = 0;

function nextRowId() {
  rowSeed += 1;
  return `row-${rowSeed}`;
}

/** 异步选项加载结果 */
const asyncOptions = ref<Record<string, Array<{ label: string; value: any }>>>(
  {},
);
const loadingOptions = ref(false);

/**
 * 表格数据源。
 *
 * 直接暴露外部传入的数组，不能在这里做「补齐 __rowId」这类产生新对象的转换：
 * 该 getter 每次渲染都会被调用，若返回新对象，`v-model` 的写入会落到被丢弃的
 * 副本上，父组件的数据永远不会更新（表现为初始行填了值却仍提示缺字段）。
 */
const rows = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
});

/**
 * 就地补齐 __rowId。
 *
 * 直接改写行对象的属性而不复制，保证与父组件持有的是同一份引用；
 * 随后 emit 一次新数组，让父组件的数组本身也刷新。
 */
watch(
  () => props.modelValue,
  (list) => {
    let mutated = false;
    for (const row of list) {
      if (!row[ROW_KEY]) {
        row[ROW_KEY] = nextRowId();
        mutated = true;
      }
    }
    if (mutated) {
      emit('update:modelValue', [...list]);
    }
  },
  { deep: true, immediate: true },
);

/** 解析每列的选项：同步数组直接用，函数则先加载 */
function optionsOf(column: ItemsEditorColumn) {
  if (Array.isArray(column.options)) {
    return column.options;
  }
  return asyncOptions.value[column.field] ?? [];
}

function addRow() {
  if (rows.value.length >= props.maxRows) {
    return;
  }
  rows.value = [
    ...rows.value,
    { ...props.createRow(), [ROW_KEY]: nextRowId() },
  ];
}

function removeRow(index: number) {
  if (rows.value.length <= props.minRows) {
    return;
  }
  const next = [...rows.value];
  next.splice(index, 1);
  rows.value = next;
}

const tableColumns = computed(() => [
  { key: '__index', title: '#', width: 50 },
  ...props.columns.map((column) => ({
    key: column.field,
    title: column.label,
    width: column.width,
  })),
  { key: '__action', title: '操作', width: 70 },
]);

onMounted(async () => {
  const asyncColumns = props.columns.filter(
    (column) => typeof column.options === 'function',
  );
  if (asyncColumns.length === 0) {
    return;
  }
  loadingOptions.value = true;
  try {
    const results = await Promise.all(
      asyncColumns.map(async (column) => {
        const options = await (
          column.options as () => Promise<any[]>
        )();
        return [column.field, options] as const;
      }),
    );
    asyncOptions.value = Object.fromEntries(results);
  } finally {
    loadingOptions.value = false;
  }
});
</script>

<template>
  <div class="space-y-3">
    <Empty
      v-if="rows.length === 0"
      description="还没有明细，点击下方按钮添加"
    />
    <Table
      v-else
      :columns="tableColumns"
      :data-source="rows"
      :loading="loadingOptions"
      :pagination="false"
      :row-key="ROW_KEY"
      size="small"
    >
      <template #bodyCell="{ column, index, record }">
        <template v-if="column.key === '__index'">
          {{ index + 1 }}
        </template>
        <template v-else-if="column.key === '__action'">
          <Tooltip title="删除该行">
            <Button
              :disabled="rows.length <= minRows"
              danger
              size="small"
              type="text"
              @click="removeRow(index)"
            >
              <IconifyIcon icon="lucide:trash-2" class="size-4" />
            </Button>
          </Tooltip>
        </template>
        <template v-else>
          <template
            v-for="editorColumn in columns.filter(
              (item) => item.field === column.key,
            )"
            :key="editorColumn.field"
          >
            <InputNumber
              v-if="editorColumn.component === 'number'"
              v-model:value="record[editorColumn.field]"
              v-bind="editorColumn.componentProps"
              class="w-full"
            />
            <Select
              v-else-if="editorColumn.component === 'select'"
              v-model:value="record[editorColumn.field]"
              :options="optionsOf(editorColumn)"
              v-bind="editorColumn.componentProps"
              class="w-full"
              show-search
            />
            <DatePicker
              v-else-if="editorColumn.component === 'date'"
              v-model:value="record[editorColumn.field]"
              v-bind="editorColumn.componentProps"
              class="w-full"
              value-format="YYYY-MM-DD"
            />
            <Input.TextArea
              v-else-if="editorColumn.component === 'textarea'"
              v-model:value="record[editorColumn.field]"
              v-bind="editorColumn.componentProps"
              :rows="2"
            />
            <Input
              v-else
              v-model:value="record[editorColumn.field]"
              v-bind="editorColumn.componentProps"
            />
          </template>
        </template>
      </template>
    </Table>

    <Button :disabled="rows.length >= maxRows" block type="dashed" @click="addRow">
      <Plus class="size-4" />
      添加明细
    </Button>
  </div>
</template>
