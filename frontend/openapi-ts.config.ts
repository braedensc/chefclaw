import { defaultPlugins, defineConfig } from '@hey-api/openapi-ts';

// Generates the committed typed client (src/client) from the backend's
// exported OpenAPI schema. Drift is checked in CI: regenerate + git diff.
export default defineConfig({
  input: '../backend/openapi.json',
  output: 'src/client',
  plugins: [
    ...defaultPlugins,
    '@hey-api/client-fetch',
    '@tanstack/react-query',
  ],
});
