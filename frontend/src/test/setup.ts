import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// globals: false (kit convention) — RTL does not auto-cleanup without a
// global afterEach, so wire it explicitly here.
afterEach(() => {
  cleanup();
  localStorage.clear();
});
