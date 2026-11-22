// ESLint: JavaScript and TypeScript rules, plus React's Rules of Hooks.
import js from '@eslint/js';
import { defineConfig, globalIgnores } from 'eslint/config';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default defineConfig(
  globalIgnores(['dist', 'playwright-report', 'test-results', 'src/api/schema.ts']),
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    rules: {
      'no-empty': ['error', { allowEmptyCatch: true }],
      // `_name` marks something unused on purpose; `{ a: _a, ...rest }` drops a field.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', ignoreRestSiblings: true },
      ],
    },
  },
  {
    // The browser code.
    files: ['src/**/*.{ts,tsx}'],
    extends: [reactHooks.configs.flat.recommended],
    languageOptions: { globals: globals.browser },
  },
  {
    // Node: configs, the mock backend, scripts, e2e tests.
    files: ['*.{js,ts}', 'mock/**', 'scripts/**', 'e2e/**', 'src/design/*.mjs'],
    languageOptions: { globals: globals.node },
  },
);
