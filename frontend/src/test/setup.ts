import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// globals: false (kit convention) — RTL does not auto-cleanup without a
// global afterEach, so wire it explicitly here.
afterEach(() => {
  cleanup();
  localStorage.clear();
});

// Testing-honesty guard (docs/TESTING.md): unit/component tests mock the
// generated query layer (src/test/gen-mock.ts) and must NEVER perform real
// network I/O — the daily-driver stack on 127.0.0.1 is production data. Any
// request that escapes the mocks fails the test loudly instead of silently
// pending or reaching a live server.
function banNetwork(api: string): never {
  throw new Error(
    `${api} escaped a unit test — real network I/O is banned here; ` +
      'mock the generated query layer (src/test/gen-mock.ts).',
  );
}

vi.stubGlobal('fetch', (input: unknown) =>
  banNetwork(`fetch(${String(input)})`),
);
vi.stubGlobal('XMLHttpRequest', function XMLHttpRequest() {
  banNetwork('XMLHttpRequest');
});
