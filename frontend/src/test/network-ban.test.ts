// Pins the setup.ts testing-honesty guard (docs/TESTING.md): real network
// I/O out of a unit/component test must FAIL loudly, never silently pend or
// reach a live server — the daily-driver stack on 127.0.0.1 is production
// data. If this test starts failing, the guard in src/test/setup.ts was
// weakened or removed.

import { describe, expect, it } from 'vitest';

describe('unit-test network ban (setup.ts)', () => {
  it('rejects an escaped fetch with the mocking hint', async () => {
    await expect(
      Promise.resolve().then(() => fetch('http://127.0.0.1:9/api/none')),
    ).rejects.toThrow(/escaped a unit test/);
  });

  it('rejects XMLHttpRequest construction', () => {
    expect(() => new XMLHttpRequest()).toThrow(/escaped a unit test/);
  });
});
