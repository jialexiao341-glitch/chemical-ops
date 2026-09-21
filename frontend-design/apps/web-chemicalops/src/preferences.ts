import { defineOverridesPreferences } from '@vben/preferences';

/**
 * @description 项目配置文件
 * 只需要覆盖项目中的一部分配置，不需要的配置不用覆盖，会自动使用默认配置
 * !!! 更改配置后请清空缓存，否则可能不生效
 */
export const overridesPreferences = defineOverridesPreferences({
  /** 左上角与登录页展示的系统名称 */
  app: {
    name: import.meta.env.VITE_APP_TITLE,
  },
  /** 默认 logo 指向 vben 官方 CDN，这里换成项目自带的图标 */
  logo: {
    source: '/logo.svg',
  },
  /** 版权信息改为本项目，不显示 vben 的默认备案信息 */
  copyright: {
    companyName: 'ChemicalOps',
    companySiteLink: '',
    date: '2026',
    enable: false,
    icp: '',
    icpLink: '',
    settingShow: false,
  },
});
