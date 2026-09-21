import { defineConfig } from '@vben/vite-config';

export default defineConfig(async () => {
  return {
    application: {},
    vite: {
      server: {
        proxy: {
          // 代理到本地 FastAPI 后端。VITE_GLOB_API_URL 已经是 /api/v1，
          // 因此这里保留 /api 前缀直接转发，不做 rewrite。
          '/api': {
            changeOrigin: true,
            target: 'http://127.0.0.1:8888',
            ws: true,
          },
          // 后端根路径下的健康检查与指标接口
          '/health': {
            changeOrigin: true,
            target: 'http://127.0.0.1:8888',
          },
        },
      },
    },
  };
});
