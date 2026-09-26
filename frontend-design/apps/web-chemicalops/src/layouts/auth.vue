<script lang="ts" setup>
import { computed } from 'vue';

import { AuthPageLayout } from '@vben/layouts';
import { preferences } from '@vben/preferences';

import { $t } from '#/locales';

const appName = computed(() => preferences.app.name);
const logo = computed(() => preferences.logo.source);
const logoDark = computed(() => preferences.logo.sourceDark);
</script>

<template>
  <AuthPageLayout
    class="chemicalops-auth"
    :app-name="appName"
    :logo="logo"
    :logo-dark="logoDark"
    :toolbar-list="['language', 'theme']"
  >
    <template #hero>
      <div class="chemicalops-hero">
        <div class="chemicalops-hero-content">
          <h2>{{ $t('authentication.pageTitle') }}</h2>
          <p>{{ $t('authentication.pageDesc') }}</p>
          <div class="chemicalops-capabilities" aria-hidden="true">
            <span>{{ $t('authentication.production') }}</span>
            <span>{{ $t('authentication.equipment') }}</span>
            <span>{{ $t('authentication.safety') }}</span>
          </div>
        </div>
      </div>
    </template>
  </AuthPageLayout>
</template>

<style scoped>
.chemicalops-auth {
  min-height: 100dvh;
}

.chemicalops-auth :deep(.auth-hero) {
  flex: 0 0 55%;
}

.chemicalops-auth :deep(.auth-form-panel) {
  width: 45%;
  min-width: 0;
  background: #f8fafc;
}

.chemicalops-auth :deep(.auth-brand) {
  color: #fff;
}

.chemicalops-auth :deep(.auth-brand > div) {
  margin: 28px 0 0 42px;
  padding: 10px 16px 10px 10px;
  border: 1px solid #e3eaf2;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 8px 24px rgb(3 22 44 / 22%);
  color: #102b49;
}

.chemicalops-auth :deep(.auth-brand p) {
  color: #102b49;
  font-weight: 650;
  letter-spacing: -0.025em;
}

.chemicalops-hero {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: flex-end;
  padding: clamp(44px, 5vw, 78px);
  color: #fff;
  background:
    linear-gradient(180deg, rgb(6 24 44 / 18%) 26%, rgb(6 24 44 / 84%) 100%),
    url('/chemical-plant-login.png') center / cover,
    #0b2038;
}

.chemicalops-hero-content {
  max-width: 680px;
}

.chemicalops-hero h2 {
  margin: 0;
  font-size: clamp(34px, 3.6vw, 56px);
  font-weight: 650;
  letter-spacing: -0.055em;
  line-height: 1.2;
}

.chemicalops-hero p {
  margin: 16px 0 0;
  color: #d0e3f4;
  font-size: clamp(16px, 1.25vw, 19px);
  line-height: 1.6;
}

.chemicalops-capabilities {
  display: flex;
  gap: 0;
  margin-top: 48px;
  color: #d0e3f4;
  font-size: 13px;
}

.chemicalops-capabilities span + span {
  margin-left: 22px;
  padding-left: 22px;
  border-left: 1px solid rgb(208 227 244 / 40%);
}

.chemicalops-auth :deep(.side-content) {
  max-width: 440px;
  color: #102b49;
}

.chemicalops-auth :deep(.side-content label) {
  color: #29435d;
}

.chemicalops-auth :deep(.chemicalops-login-heading) {
  margin-bottom: 38px;
}

.chemicalops-auth :deep(.chemicalops-login-heading h1) {
  color: #102b49;
  font-size: 38px;
  font-weight: 700;
  letter-spacing: -0.04em;
  line-height: 1.2;
}

.chemicalops-auth :deep(.chemicalops-login-heading > p:last-child) {
  margin-top: 12px;
  color: #667b91;
  font-size: 15px;
}

.chemicalops-auth :deep(.side-content input) {
  min-height: 48px;
  border-color: #cdd9e6;
  background: #fff;
  color: #102b49;
}

.chemicalops-auth :deep(.side-content input::placeholder) {
  color: #8496a9;
}

.chemicalops-auth :deep(.side-content button[aria-label='login']) {
  min-height: 48px;
  background: #0b417b;
  font-weight: 650;
}

.chemicalops-auth :deep(.side-content button[aria-label='login']:hover) {
  background: #08345f;
}

.chemicalops-auth :deep(.side-content :focus-visible) {
  outline: 2px solid #2b78c1;
  outline-offset: 2px;
}

.chemicalops-auth.dark :deep(.auth-form-panel) {
  background: #0d1b2c;
}

.chemicalops-auth.dark :deep(.side-content),
.chemicalops-auth.dark :deep(.side-content label),
.chemicalops-auth.dark :deep(.chemicalops-login-heading h1) {
  color: #eef5fb;
}

.chemicalops-auth.dark :deep(.chemicalops-login-heading > p:last-child) {
  color: #afc1d3;
}

.chemicalops-auth.dark :deep(.side-content input) {
  border-color: #3a5068;
  background: #172b42;
  color: #eef5fb;
}

.chemicalops-auth.dark :deep(.side-content input::placeholder) {
  color: #9db0c3;
}

@media (max-width: 1023px) {
  .chemicalops-auth :deep(.auth-form-panel) {
    width: 100%;
  }

  .chemicalops-auth :deep(.auth-brand > div),
  .chemicalops-auth :deep(.auth-brand p) {
    color: #102b49;
  }

  .chemicalops-auth :deep(.auth-brand > div) {
    margin: 20px 0 0 20px;
  }

}

@media (max-width: 640px) {
  .chemicalops-auth :deep(.auth-form-panel) {
    padding-inline: 24px;
  }

  .chemicalops-auth :deep(.chemicalops-login-heading h1) {
    font-size: 32px;
  }
}
</style>
