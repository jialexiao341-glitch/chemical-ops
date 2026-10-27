import { mergeConfig } from 'vitest/config';
import base from './vitest.config.ts';
export default mergeConfig(base, {
  test: {
    include: ['**/create-real-controls.case.ts'],
    server: { deps: { inline: [/antdv-next/, /@v-c/] } },
  },
});
