import js from '@eslint/js';
import prettier from 'eslint-config-prettier/flat';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  // Generated client and build/test artifacts are not linted. Patterns are
  // **-anchored because this config is invoked from two base paths: frontend/
  // (npm run lint) and the repo root (lint-staged --config, where relative
  // ignores rebase to the cwd).
  {
    ignores: [
      '**/dist',
      '**/src/client',
      '**/test-results',
      '**/playwright-report',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  // eslint-config-prettier LAST so it disables every stylistic rule.
  prettier,
);
