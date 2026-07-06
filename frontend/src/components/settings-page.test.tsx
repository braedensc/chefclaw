import { fireEvent, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api-error';
import { healthResponse } from '../test/fixtures';
import { genState, resetGenState } from '../test/gen-mock';
import { renderApp } from '../test/render-app';

// Mock the generated query-options module — component tests never real-fetch.
vi.mock('../client/@tanstack/react-query.gen', async () =>
  (await import('../test/gen-mock')).genMockModule(),
);

async function findSection(name: string) {
  return within(await screen.findByRole('region', { name }));
}

describe('SettingsPage', () => {
  beforeEach(() => {
    resetGenState();
  });

  it('is reachable from the app-shell Settings header link', async () => {
    renderApp('/');

    fireEvent.click(await screen.findByRole('link', { name: 'Settings' }));

    expect(
      await screen.findByRole('heading', { name: 'Settings' }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole('region', { name: 'Extraction' }),
    ).toBeInTheDocument();
  });

  describe('Extraction section', () => {
    it('shows the live extractor and model with spend against the $10 budget', async () => {
      genState.health = healthResponse({
        extractor: 'gemini',
        model: 'gemini-2.5-flash',
        spend_month_usd: 2.5,
      });

      renderApp('/settings');
      const section = await findSection('Extraction');

      expect(section.getByText('gemini')).toBeInTheDocument();
      expect(section.getByText('gemini-2.5-flash')).toBeInTheDocument();
      expect(section.getByText('$2.50')).toBeInTheDocument();
      expect(section.getByText(/of \$10\.00 budget/)).toBeInTheDocument();
      const bar = section.getByRole('progressbar', {
        name: 'Month-to-date spend against budget',
      });
      expect(bar).toHaveAttribute('aria-valuenow', '2.5');
      expect(bar).toHaveAttribute('aria-valuemax', '10');
    });

    it('renders zero spend as a real $0.00 bar, not the unavailable state', async () => {
      genState.health = healthResponse({ spend_month_usd: 0 });

      renderApp('/settings');
      const section = await findSection('Extraction');

      expect(section.getByText('$0.00')).toBeInTheDocument();
      expect(
        section.getByRole('progressbar', {
          name: 'Month-to-date spend against budget',
        }),
      ).toHaveAttribute('aria-valuenow', '0');
      expect(
        section.queryByText(/month-to-date spend is unavailable/i),
      ).not.toBeInTheDocument();
    });

    it('reports over-budget spend truthfully with the bar clamped to full', async () => {
      genState.health = healthResponse({ spend_month_usd: 12.34 });

      renderApp('/settings');
      const section = await findSection('Extraction');

      // The NUMBER stays truthful (over the cap), only the bar visual clamps.
      expect(section.getByText('$12.34')).toBeInTheDocument();
      const bar = section.getByRole('progressbar', {
        name: 'Month-to-date spend against budget',
      });
      expect(bar).toHaveAttribute('aria-valuenow', '12.34');
      const fill = bar.firstElementChild as HTMLElement;
      expect(fill.style.width).toBe('100%');
      expect(fill.className).toContain('bg-red-500');
    });

    it('is honest when spend is null: unavailable, not $0, no bar', async () => {
      genState.health = healthResponse({ spend_month_usd: null });

      renderApp('/settings');
      const section = await findSection('Extraction');

      expect(
        section.getByText(/month-to-date spend is unavailable/i),
      ).toBeInTheDocument();
      expect(section.queryByRole('progressbar')).not.toBeInTheDocument();
      expect(section.queryByText(/\$0\.00/)).not.toBeInTheDocument();
    });
  });

  describe('Rednote access section', () => {
    it('presents guest tier (no cookie) as a healthy state, not an error', async () => {
      genState.health = healthResponse({
        sidecar: 'ok',
        cookie_freshness: 'not_configured',
        cookie_set_date: null,
      });

      renderApp('/settings');
      const section = await findSection('Rednote access');

      expect(
        section.getByText('guest tier (no cookie configured)'),
      ).toBeInTheDocument();
      expect(
        section.getByText(/a healthy state, not an error/i),
      ).toBeInTheDocument();
      // Healthy posture: no runbook pointer in this section.
      expect(section.queryByText(/RUNBOOK/)).not.toBeInTheDocument();
    });

    it('shows a fresh cookie with its set-date and no runbook pointer', async () => {
      genState.health = healthResponse({
        cookie_freshness: 'fresh',
        cookie_set_date: '2026-07-01',
      });

      renderApp('/settings');
      const section = await findSection('Rednote access');

      expect(section.getByText('fresh — set 2026-07-01')).toBeInTheDocument();
      expect(section.queryByText(/RUNBOOK/)).not.toBeInTheDocument();
    });

    it('shows an aging cookie with its set-date and the runbook pointer', async () => {
      genState.health = healthResponse({
        cookie_freshness: 'aging',
        cookie_set_date: '2026-06-20',
      });

      renderApp('/settings');
      const section = await findSection('Rednote access');

      expect(section.getByText('aging — set 2026-06-20')).toBeInTheDocument();
      expect(section.getByText(/refresh it soon/i)).toBeInTheDocument();
      expect(section.getByText(/docs\/RUNBOOK\.md/)).toBeInTheDocument();
    });

    it('shows a stale cookie with its set-date and the runbook pointer', async () => {
      genState.health = healthResponse({
        cookie_freshness: 'stale',
        cookie_set_date: '2026-05-01',
      });

      renderApp('/settings');
      const section = await findSection('Rednote access');

      expect(section.getByText('stale — set 2026-05-01')).toBeInTheDocument();
      expect(section.getByText(/refresh it now/i)).toBeInTheDocument();
      expect(section.getByText(/docs\/RUNBOOK\.md/)).toBeInTheDocument();
    });

    it('reports an unreachable sidecar', async () => {
      genState.health = healthResponse({ sidecar: 'unreachable' });

      renderApp('/settings');
      const section = await findSection('Rednote access');

      expect(
        section.getByText(/unreachable — check the xhs/),
      ).toBeInTheDocument();
    });

    it('reports a not-configured sidecar as disabled, not broken', async () => {
      genState.health = healthResponse({ sidecar: 'not_configured' });

      renderApp('/settings');
      const section = await findSection('Rednote access');

      expect(
        section.getByText(/not configured \(Rednote source disabled\)/),
      ).toBeInTheDocument();
    });
  });

  describe('Backups section', () => {
    it('points not_configured at scripts/backup.sh and the runbook in plain words', async () => {
      genState.health = healthResponse({
        backup: 'not_configured',
        backup_finished_at: null,
      });

      renderApp('/settings');
      const section = await findSection('Backups');

      expect(
        section.getByText(/no backups are configured yet/i),
      ).toBeInTheDocument();
      expect(section.getByText(/scripts\/backup\.sh/)).toBeInTheDocument();
      expect(section.getByText(/docs\/RUNBOOK\.md/)).toBeInTheDocument();
    });

    it('shows a fresh backup with its finished-at timestamp', async () => {
      genState.health = healthResponse({
        backup: 'fresh',
        backup_finished_at: '2026-07-06T03:30:00+00:00',
      });

      renderApp('/settings');
      const section = await findSection('Backups');

      expect(section.getByText('fresh')).toBeInTheDocument();
      expect(
        section.getByText('2026-07-06T03:30:00+00:00'),
      ).toBeInTheDocument();
    });

    it('warns on a stale backup with the last recorded run and runbook pointer', async () => {
      genState.health = healthResponse({
        backup: 'stale',
        backup_finished_at: '2026-07-01T03:30:00+00:00',
      });

      renderApp('/settings');
      const section = await findSection('Backups');

      expect(section.getByText('stale')).toBeInTheDocument();
      expect(
        section.getByText('2026-07-01T03:30:00+00:00'),
      ).toBeInTheDocument();
      expect(section.getByText(/docs\/RUNBOOK\.md/)).toBeInTheDocument();
    });

    it('handles a stale backup with no readable timestamp honestly', async () => {
      genState.health = healthResponse({
        backup: 'stale',
        backup_finished_at: null,
      });

      renderApp('/settings');
      const section = await findSection('Backups');

      expect(
        section.getByText(/unknown \(state file unreadable/),
      ).toBeInTheDocument();
    });
  });

  describe('failure states (absorbed from the Phase-1 HealthPanel)', () => {
    it('offers clear-token-and-re-enter on a 401 and returns to the token gate', async () => {
      genState.healthError = new ApiError(401, 'Unauthorized', {
        detail: 'Invalid token',
      });

      renderApp('/settings');

      expect(
        await screen.findByText(/token rejected \(401\)/i),
      ).toBeInTheDocument();

      fireEvent.click(
        screen.getByRole('button', { name: 'Clear token & re-enter' }),
      );
      expect(
        await screen.findByText(/paste your CHEFCLAW_API_TOKEN/i),
      ).toBeInTheDocument();
    });

    it('shows the status code on any other non-2xx with a retry affordance', async () => {
      genState.healthError = new ApiError(503, 'Service Unavailable', {
        detail: 'db down',
      });

      renderApp('/settings');

      expect(await screen.findByText(/http 503/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    });

    it('shows the stack-down message on a network failure', async () => {
      genState.healthError = new TypeError('Failed to fetch');

      renderApp('/settings');

      expect(
        await screen.findByText(/could not reach the api/i),
      ).toBeInTheDocument();
      expect(screen.getByText(/docker compose up/i)).toBeInTheDocument();
    });
  });
});
