import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { ApiError } from '../api-error';
import {
  getSpendApiSpendGetOptions,
  healthApiHealthGetOptions,
} from '../client/@tanstack/react-query.gen';
import type { HealthResponse } from '../client/types.gen';
import { useTokenActions } from '../token-context';

/**
 * Poll cadence for the health readout. The interval lives on THIS query's
 * observer, so polling runs only while the settings route is mounted —
 * navigating away stops it.
 */
export const HEALTH_POLL_MS = 15_000;

/** Spend-history window requested from GET /api/spend (V2-A). */
export const SPEND_HISTORY_DAYS = 30;

/**
 * Screen 4 (plan §7): Settings/health — which extractor/model is live,
 * month-to-date spend against the REAL configured budget (V2-A: the cap
 * comes from /api/health; null means the fail-closed config refuses paid
 * calls), a spend history (GET /api/spend), sidecar + tiered cookie posture
 * (Rednote access), and backup staleness (Backups).
 *
 * Failure handling is absorbed from the Phase-1 HealthPanel: 401 → clear the
 * token; other non-2xx → show the status; no response → the stack is down.
 */
export function SettingsPage() {
  const { clearToken } = useTokenActions();
  const health = useQuery({
    ...healthApiHealthGetOptions(),
    refetchInterval: HEALTH_POLL_MS,
  });

  const status = health.error instanceof ApiError ? health.error.status : null;

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-lg font-semibold text-neutral-100">Settings</h1>

      {health.isPending && (
        <p className="mt-4 text-sm text-neutral-400">Checking API health…</p>
      )}

      {health.isError && (
        <div className="mt-4 rounded-md border border-red-900 bg-red-950/40 p-4">
          {status === 401 ? (
            <>
              <p className="text-sm text-red-300">
                Token rejected (401) — clear the token and re-enter it.
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={clearToken}
                  className="rounded-md bg-red-800 px-3 py-1.5 text-xs font-medium text-red-100 hover:bg-red-700"
                >
                  Clear token & re-enter
                </button>
                <button
                  type="button"
                  onClick={() => void health.refetch()}
                  className="rounded-md border border-red-800 px-3 py-1.5 text-xs text-red-200 hover:border-red-600"
                >
                  Retry
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-red-300">
                {status !== null
                  ? `The API responded with an unexpected error (HTTP ${status}). Retry, or check the api container logs.`
                  : 'Could not reach the API — is the stack running (docker compose up)?'}
              </p>
              <button
                type="button"
                onClick={() => void health.refetch()}
                className="mt-3 rounded-md bg-red-800 px-3 py-1.5 text-xs font-medium text-red-100 hover:bg-red-700"
              >
                Retry
              </button>
            </>
          )}
        </div>
      )}

      {health.isSuccess && (
        <div className="mt-4 space-y-4">
          <ApiSection health={health.data} />
          <ExtractionSection health={health.data} />
          <SpendHistorySection />
          <RednoteSection health={health.data} />
          <BackupsSection health={health.data} />
        </div>
      )}
    </div>
  );
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section
      aria-label={label}
      className="rounded-xl border border-neutral-800 bg-neutral-900 p-5"
    >
      <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-300">
        {label}
      </h2>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-neutral-400">{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

const OK_CLASS = 'font-medium text-emerald-400';
const WARN_CLASS = 'font-medium text-amber-400';
const BAD_CLASS = 'font-medium text-red-400';
const NEUTRAL_CLASS = 'text-neutral-300';

/** Overall status + db — the Phase-1 HealthPanel readout, plus the V2-A
 * worker-aliveness and error-tracking rows. */
function ApiSection({ health }: { health: HealthResponse }) {
  const worker = health.worker ?? 'not_running';
  return (
    <Section label="API">
      <dl className="mt-3 grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
        <Row label="status">
          <span className={health.status === 'ok' ? OK_CLASS : WARN_CLASS}>
            {health.status}
          </span>
        </Row>
        <Row label="db">
          <span className={health.db === 'ok' ? OK_CLASS : BAD_CLASS}>
            {health.db}
          </span>
        </Row>
        <Row label="worker">
          {worker === 'alive' ? (
            <span className={OK_CLASS}>alive</span>
          ) : worker === 'dead' ? (
            <div>
              <span className={BAD_CLASS}>dead</span>
              <p className="mt-1 text-xs text-neutral-400">
                The job worker crashed — no extraction will run. Restart the api
                container (docker compose restart api).
              </p>
            </div>
          ) : (
            <span className={NEUTRAL_CLASS}>not running</span>
          )}
        </Row>
        <Row label="error tracking">
          {health.sentry_enabled ? (
            <span className={OK_CLASS}>Sentry enabled</span>
          ) : (
            <span className={NEUTRAL_CLASS}>
              not configured (set SENTRY_DSN to enable)
            </span>
          )}
        </Row>
      </dl>
    </Section>
  );
}

function ExtractionSection({ health }: { health: HealthResponse }) {
  const spend = health.spend_month_usd ?? null;
  const budget = health.budget_monthly_usd ?? null;
  const attemptsToday = health.attempts_today ?? null;
  const dailyCap = health.daily_attempt_cap ?? null;
  return (
    <Section label="Extraction">
      <dl className="mt-3 grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
        <Row label="extractor">
          <span className={NEUTRAL_CLASS}>{health.extractor ?? 'unknown'}</span>
        </Row>
        <Row label="model">
          <span className="font-mono text-xs text-neutral-300">
            {health.model ?? 'unknown'}
          </span>
        </Row>
        {attemptsToday !== null && dailyCap !== null && (
          <Row label="attempts today">
            <span className={NEUTRAL_CLASS}>
              {attemptsToday} of {dailyCap}
            </span>
          </Row>
        )}
      </dl>
      {budget === null ? (
        // Fail-closed truth (§16.8): no budget config means NO paid calls —
        // say so loudly instead of rendering a bar against an invented cap.
        <p className="mt-3 rounded-md border border-amber-900 bg-amber-950/40 p-3 text-sm text-amber-300">
          Budget is not configured — extraction is disabled (fail-closed). Set
          MONTHLY_LLM_BUDGET_USD and MAX_EXTRACTION_ATTEMPTS_PER_DAY in the
          server environment.
        </p>
      ) : spend === null ? (
        // Honest null state: null means "could not read the ledger", not $0.
        <p className="mt-3 text-sm text-neutral-400">
          Month-to-date spend is unavailable — the spend ledger could not be
          read (is the database up?).
        </p>
      ) : (
        <SpendBar spendUsd={spend} budgetUsd={budget} />
      )}
    </Section>
  );
}

function SpendBar({
  spendUsd,
  budgetUsd,
}: {
  spendUsd: number;
  budgetUsd: number;
}) {
  const fraction = spendUsd / budgetUsd;
  const widthPct = Math.min(100, Math.max(0, fraction * 100));
  const barClass =
    fraction >= 1
      ? 'bg-red-500'
      : fraction >= 0.8
        ? 'bg-amber-400'
        : 'bg-emerald-500';
  return (
    <div className="mt-3">
      <p className="text-sm text-neutral-300">
        Month-to-date spend:{' '}
        <span className="font-medium">${spendUsd.toFixed(2)}</span>
        <span className="text-neutral-500">
          {' '}
          of ${budgetUsd.toFixed(2)} budget
        </span>
      </p>
      <div
        role="progressbar"
        aria-label="Month-to-date spend against budget"
        aria-valuemin={0}
        aria-valuemax={budgetUsd}
        aria-valuenow={spendUsd}
        className="mt-2 h-2 w-full overflow-hidden rounded-full bg-neutral-800"
      >
        <div
          className={`h-full ${barClass}`}
          style={{ width: `${widthPct}%` }}
        />
      </div>
    </div>
  );
}

/**
 * Spend history (GET /api/spend): one row per UTC day with activity, newest
 * first, with the per-model split inline. Its own query — the history is
 * heavier than /api/health and does not need the 15 s poll.
 */
function SpendHistorySection() {
  const spend = useQuery(
    getSpendApiSpendGetOptions({ query: { days: SPEND_HISTORY_DAYS } }),
  );
  return (
    <Section label="Spend history">
      {spend.isPending && (
        <p className="mt-3 text-sm text-neutral-400">Loading spend history…</p>
      )}
      {spend.isError && (
        <p className="mt-3 text-sm text-neutral-400">
          Spend history is unavailable (could not read the ledger).
        </p>
      )}
      {spend.isSuccess && spend.data.days.length === 0 && (
        <p className="mt-3 text-sm text-neutral-400">
          No extraction attempts in the last {spend.data.period_days} days.
        </p>
      )}
      {spend.isSuccess && spend.data.days.length > 0 && (
        <>
          <p className="mt-3 text-sm text-neutral-300">
            Last {spend.data.period_days} days:{' '}
            <span className="font-medium">
              ${spend.data.total_usd.toFixed(2)}
            </span>
            <span className="text-neutral-500">
              {' '}
              · month to date ${spend.data.month_to_date_usd.toFixed(2)}
            </span>
          </p>
          <ul className="mt-3 space-y-2 text-sm">
            {spend.data.days.map((day) => (
              <li
                key={day.date}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1"
              >
                <span className="font-mono text-xs text-neutral-400">
                  {day.date}
                </span>
                <span className="font-medium text-neutral-200">
                  ${day.cost_usd.toFixed(2)}
                </span>
                <span className="text-neutral-500">
                  {day.attempts} attempt{day.attempts === 1 ? '' : 's'}
                </span>
                <span className="font-mono text-xs text-neutral-500">
                  {day.models
                    .map((m) => `${m.model} $${m.cost_usd.toFixed(2)}`)
                    .join(' · ')}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  );
}

function RednoteSection({ health }: { health: HealthResponse }) {
  const sidecar = health.sidecar ?? 'not_configured';
  return (
    <Section label="Rednote access">
      <dl className="mt-3 grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
        <Row label="sidecar">
          {sidecar === 'ok' ? (
            <span className={OK_CLASS}>ok</span>
          ) : sidecar === 'unreachable' ? (
            <span className={BAD_CLASS}>
              unreachable — check the xhs container
            </span>
          ) : (
            <span className={NEUTRAL_CLASS}>
              not configured (Rednote source disabled)
            </span>
          )}
        </Row>
        <Row label="cookie">
          <CookieStatus health={health} />
        </Row>
      </dl>
    </Section>
  );
}

/**
 * Cookie copy reflects the TIERED access posture (plan §16.10): guest —
 * no cookie at all — is the DEFAULT and a healthy state, not an error. A
 * configured cookie (tier-1 throwaway only, never the main account) gets the
 * freshness buckets with its set-date, and a runbook pointer once it ages.
 */
function CookieStatus({ health }: { health: HealthResponse }) {
  const freshness = health.cookie_freshness ?? 'not_configured';
  const setDate = health.cookie_set_date ?? null;

  if (freshness === 'not_configured') {
    return (
      <div>
        <span className={OK_CLASS}>guest tier (no cookie configured)</span>
        <p className="mt-1 text-xs text-neutral-500">
          The default posture: Rednote is fetched without an account. A
          throwaway cookie is only needed for content the guest tier can't reach
          — this is a healthy state, not an error.
        </p>
      </div>
    );
  }

  const setDateSuffix = setDate !== null ? ` — set ${setDate}` : '';
  if (freshness === 'fresh') {
    return <span className={OK_CLASS}>{`fresh${setDateSuffix}`}</span>;
  }
  return (
    <div>
      <span className={freshness === 'aging' ? WARN_CLASS : BAD_CLASS}>
        {`${freshness}${setDateSuffix}`}
      </span>
      <p className="mt-1 text-xs text-neutral-400">
        {freshness === 'aging'
          ? 'Refresh it soon — Rednote cookies last 2–4 weeks. '
          : 'Refresh it now — the cookie has likely expired. '}
        Follow the cookie-refresh runbook (docs/RUNBOOK.md).
      </p>
    </div>
  );
}

function BackupsSection({ health }: { health: HealthResponse }) {
  const backup = health.backup ?? 'not_configured';
  const finishedAt = health.backup_finished_at ?? null;
  return (
    <Section label="Backups">
      <div className="mt-3 text-sm">
        {backup === 'not_configured' && (
          <p className="text-neutral-300">
            No backups are configured yet — recipes are irreplaceable. Schedule
            scripts/backup.sh (daily launchd job) and see docs/RUNBOOK.md for
            the setup and restore procedure.
          </p>
        )}
        {backup === 'fresh' && (
          <p>
            <span className={OK_CLASS}>fresh</span>
            <span className="text-neutral-400">
              {' '}
              — last backup finished{' '}
              <span className="font-mono text-xs">{finishedAt}</span>
            </span>
          </p>
        )}
        {backup === 'stale' && (
          <div>
            <p>
              <span className={BAD_CLASS}>stale</span>
              <span className="text-neutral-400">
                {' '}
                — last recorded run:{' '}
                {finishedAt !== null ? (
                  <span className="font-mono text-xs">{finishedAt}</span>
                ) : (
                  'unknown (state file unreadable or run failed)'
                )}
              </span>
            </p>
            <p className="mt-1 text-xs text-neutral-400">
              Check the launchd job and see docs/RUNBOOK.md.
            </p>
          </div>
        )}
      </div>
    </Section>
  );
}
