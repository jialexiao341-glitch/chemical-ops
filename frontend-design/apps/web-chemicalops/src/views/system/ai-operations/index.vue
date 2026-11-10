<script lang="ts" setup>
import { Page } from '@vben/common-ui';

import CostDashboard from './CostDashboard.vue';
import FeedbackDashboard from './FeedbackDashboard.vue';
import QualityDashboard from './QualityDashboard.vue';
import RegressionCases from './RegressionCases.vue';

defineOptions({ name: 'SystemAiOperations' });
</script>

<template>
  <Page auto-content-height>
    <div class="flex h-full flex-col gap-3 overflow-y-auto">
      <QualityDashboard />
      <RegressionCases />
      <FeedbackDashboard />
      <CostDashboard />
    </div>
  </Page>
</template>
