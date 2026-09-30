<script lang="ts" setup>
import { computed, watch } from 'vue';

import { useAntdDesignTokens } from '@vben/hooks';
import { usePreferences } from '@vben/preferences';

import { App, ConfigProvider, StyleProvider, theme } from 'antdv-next';

import { antdLocale } from '#/locales';

defineOptions({ name: 'App' });

const { isDark } = usePreferences();
const { tokens } = useAntdDesignTokens();

const tokenTheme = computed(() => {
  const algorithm = isDark.value
    ? [theme.darkAlgorithm]
    : [theme.defaultAlgorithm];

  return {
    algorithm,
    token: {
      ...tokens,
      fontFamily: "'Segoe UI', 'Microsoft YaHei', 'PingFang SC', Arial, sans-serif",
      fontSize: 14,
      controlHeight: 32,
      borderRadius: 6,
    },
    components: {
      Table: {
        cellPaddingBlock: 10,
        cellPaddingInline: 12,
        cellPaddingBlockSM: 8,
        cellPaddingInlineSM: 12,
        headerBorderRadius: 6,
      },
      Button: { fontWeight: 400 },
    },
  };
});

watch(
  [tokenTheme, antdLocale],
  ([themeConfig, locale]) => {
    ConfigProvider.config({ theme: themeConfig, locale });
  },
  { immediate: true },
);
</script>

<template>
  <!-- layer: antd 组件样式注入 @layer antd，让 Tailwind 工具类可以覆盖组件样式 -->
  <StyleProvider layer>
    <ConfigProvider
      :locale="antdLocale"
      :theme="tokenTheme"
      :button="{ autoInsertSpace: false }"
    >
      <App>
        <RouterView />
      </App>
    </ConfigProvider>
  </StyleProvider>
</template>
