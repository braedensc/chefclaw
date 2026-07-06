import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  extractRecipeApiRecipesExtractPostMutation,
  listJobsApiJobsGetOptions,
  listJobsApiJobsGetQueryKey,
} from '../client/@tanstack/react-query.gen';
import type { JobOut } from '../client/types.gen';
import { apiErrorMessage } from '../lib/error-message';
import {
  isTerminalStatus,
  JOB_POLL_MS,
  RETRYABLE_ERROR_TYPES,
  statusLabel,
} from '../lib/job-status';
import { PlatformBadge } from './platform-badge';

interface JobsDrawerProps {
  onClose: () => void;
}

/**
 * Screen 3 (plan §7): the jobs panel — GET /api/jobs, active jobs first, with
 * the typed-error actions (retry / runbook pointer / budget & config notices).
 * Status text stays the sober statusLabel() vocabulary (the golden suite
 * asserts it) — the playful cooking microcopy lives on the chips only.
 */
export function JobsDrawer({ onClose }: JobsDrawerProps) {
  const queryClient = useQueryClient();

  const jobs = useQuery({
    ...listJobsApiJobsGetOptions(),
    refetchInterval: JOB_POLL_MS,
  });

  const retry = useMutation({
    ...extractRecipeApiRecipesExtractPostMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: listJobsApiJobsGetQueryKey(),
      });
    },
  });

  const sorted = [...(jobs.data ?? [])].sort((a, b) => {
    const aTerminal = isTerminalStatus(a.status) ? 1 : 0;
    const bTerminal = isTerminalStatus(b.status) ? 1 : 0;
    if (aTerminal !== bTerminal) return aTerminal - bTerminal; // active first
    return b.updated_at.localeCompare(a.updated_at); // then newest activity
  });

  return (
    <aside
      aria-label="Jobs"
      className="fixed inset-y-0 right-0 z-30 flex w-full max-w-md flex-col border-l border-line bg-panel shadow-2xl shadow-black"
    >
      {/* neon strip light along the top of the stall (B's paste-bar ::before) */}
      <div
        aria-hidden="true"
        className="h-px shrink-0 bg-[linear-gradient(90deg,transparent,var(--color-chili)_22%,var(--color-gold)_50%,var(--color-cyan)_78%,transparent)] opacity-80"
      />
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="flex items-baseline gap-2">
          <h2 className="font-display text-[15px] font-bold tracking-[0.24em] text-warm uppercase glow-text-warm">
            Jobs
          </h2>
          <span lang="zh" className="text-xs font-medium text-gold">
            订单
          </span>
        </span>
        <button
          type="button"
          onClick={onClose}
          className="rounded-field border border-line-bright px-3 py-1 font-display text-[11px] font-semibold tracking-[0.16em] text-ink-dim uppercase transition hover:border-cyan/55 hover:text-cyan"
        >
          Close
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {retry.isError && (
          <p
            role="alert"
            className="mb-3 rounded-field border border-chili/40 bg-chili/5 p-2.5 text-xs text-chili-bright"
          >
            Retry failed — {apiErrorMessage(retry.error)}
          </p>
        )}
        {jobs.isPending && (
          <p className="text-sm text-ink-dim">Loading jobs…</p>
        )}
        {jobs.isError && (
          <p role="alert" className="text-sm text-chili-bright">
            Could not load jobs.
          </p>
        )}
        {jobs.isSuccess && sorted.length === 0 && (
          <p className="text-sm text-ink-faint">No jobs yet.</p>
        )}
        {sorted.length > 0 && (
          <ul className="space-y-3">
            {sorted.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                retryPending={retry.isPending}
                onRetry={(url) => retry.mutate({ body: { url } })}
              />
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

/** Simmering-pot accent for active rows — wisps animate reduced-motion-guarded. */
function SteamAccent() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="size-4 shrink-0 text-warm"
    >
      <g
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
      >
        <path
          className="steam-wisp"
          d="M7 19 C5.5 15.5 9 13 7 9"
          opacity=".45"
        />
        <path
          className="steam-wisp steam-wisp-2"
          d="M12 20 C10.5 16 14 13.5 12 8.5"
          opacity=".65"
        />
        <path
          className="steam-wisp steam-wisp-3"
          d="M17 19 C15.5 15.5 19 13 17 9"
          opacity=".45"
        />
      </g>
    </svg>
  );
}

interface JobRowProps {
  job: JobOut;
  retryPending: boolean;
  onRetry: (url: string) => void;
}

function JobRow({ job, retryPending, onRetry }: JobRowProps) {
  const active = !isTerminalStatus(job.status);
  const statusClass =
    job.status === 'failed'
      ? 'text-chili-bright'
      : job.status === 'stored'
        ? 'text-warm'
        : 'text-gold glow-text-gold';

  return (
    <li
      className={`rounded-card border bg-panel-deep p-3.5 text-sm ${
        active ? 'border-gold/40 glow-gold' : 'border-line'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          {job.platform != null && <PlatformBadge platform={job.platform} />}
          <span className="truncate font-mono text-xs text-ink-dim">
            {job.canonical_id ?? '—'}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {active && <SteamAccent />}
          <span
            className={`font-display text-[11.5px] font-bold tracking-[0.18em] uppercase ${statusClass}`}
          >
            {statusLabel(job.status)}
          </span>
        </span>
      </div>
      {job.url != null && (
        <p className="mt-1.5 truncate font-mono text-xs text-ink-faint">
          {job.url}
        </p>
      )}
      {job.status === 'failed' && job.error_type != null && (
        <div className="mt-2.5 rounded-field border border-chili/40 bg-chili/5 p-2.5 text-xs">
          <p className="text-chili-bright">
            <span className="font-mono">{job.error_type}</span>
            {job.error_detail ? ` — ${job.error_detail}` : ''}
          </p>
          <JobErrorAction
            job={job}
            errorType={job.error_type}
            retryPending={retryPending}
            onRetry={onRetry}
          />
        </div>
      )}
    </li>
  );
}

interface JobErrorActionProps {
  job: JobOut;
  errorType: string;
  retryPending: boolean;
  onRetry: (url: string) => void;
}

/** Maps the typed error taxonomy onto UI actions (plan §7 screen 3). */
function JobErrorAction({
  job,
  errorType,
  retryPending,
  onRetry,
}: JobErrorActionProps) {
  if (RETRYABLE_ERROR_TYPES.has(errorType)) {
    // Upload jobs cannot be re-queued from a link: their url is either a
    // local:// placeholder (no source adapter matches — a guaranteed 400) or
    // a provenance URL, and re-POSTing that would silently turn the §16.10
    // zero-platform-risk upload path into a platform fetch. Either way the
    // staged file is gone once the job is terminal — re-upload is the retry.
    if (job.type === 'upload') {
      return (
        <p className="mt-1.5 text-ink-dim">
          Upload jobs can't be retried from a link — re-upload the video file
          from the paste bar.
        </p>
      );
    }
    return (
      <button
        type="button"
        disabled={job.url == null || retryPending}
        onClick={() => {
          if (job.url != null) onRetry(job.url);
        }}
        className="mt-2 rounded-field border border-cyan/60 bg-cyan/10 px-3.5 py-1.5 font-display text-[11px] font-bold tracking-[0.16em] text-cyan uppercase glow-cyan transition hover:bg-cyan/20 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Retry
      </button>
    );
  }
  if (errorType === 'cookies_expired') {
    return (
      <p className="mt-1.5 text-ink-dim">
        The Rednote cookie has expired — follow the cookie-refresh runbook
        (docs/RUNBOOK.md §1).
      </p>
    );
  }
  if (errorType === 'budget_exceeded') {
    return (
      <p className="mt-1.5 text-ink-dim">
        Budget cap reached — extraction pauses until the monthly budget or daily
        attempt cap resets.
      </p>
    );
  }
  if (errorType === 'config_error') {
    return (
      <p className="mt-1.5 text-ink-dim">
        Check server configuration (budget and adapter settings).
      </p>
    );
  }
  return null;
}
