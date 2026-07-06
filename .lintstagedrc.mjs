// lint-staged v17 runs every task from the repo root regardless of where a
// config file lives, so the frontend's eslint/prettier configs are pointed at
// explicitly. Flat-config `ignores` and .prettierignore entries resolve
// relative to their own file's location, so frontend/dist and
// frontend/src/client (the generated client — never hand-edited) stay
// excluded. --no-warn-ignored keeps explicitly-passed ignored files from
// erroring. Backend .py files are covered by ruff (CI + dev loop), not here.
export default {
  'frontend/**/*.{ts,tsx}': [
    'eslint --fix --no-warn-ignored --config frontend/eslint.config.js',
    'prettier --write --ignore-path frontend/.prettierignore --ignore-path .gitignore',
  ],
  'frontend/**/*.{css,html}':
    'prettier --write --ignore-path frontend/.prettierignore --ignore-path .gitignore',
};
