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
      className="fixed inset-y-0 right-0 z-30 flex w-full max-w-md flex-col border-l border-neutral-800 bg-neutral-900 shadow-2xl"
    >
      <div className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
        <h2 className="text-base font-semibold text-neutral-100">Jobs</h2>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-neutral-700 px-3 py-1 text-xs text-neutral-300 hover:border-neutral-500 hover:text-neutral-100"
        >
          Close
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {retry.isError && (
          <p
            role="alert"
            className="mb-3 rounded-md border border-red-900/60 bg-red-950/30 p-2 text-xs text-red-300"
          >
            Retry failed — {apiErrorMessage(retry.error)}
          </p>
        )}
        {jobs.isPending && (
          <p className="text-sm text-neutral-400">Loading jobs…</p>
        )}
        {jobs.isError && (
          <p role="alert" className="text-sm text-red-400">
            Could not load jobs.
          </p>
        )}
        {jobs.isSuccess && sorted.length === 0 && (
          <p className="text-sm text-neutral-500">No jobs yet.</p>
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

interface JobRowProps {
  job: JobOut;
  retryPending: boolean;
  onRetry: (url: string) => void;
}

function JobRow({ job, retryPending, onRetry }: JobRowProps) {
  return (
    <li className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          {job.platform != null && <PlatformBadge platform={job.platform} />}
          <span className="truncate font-mono text-xs text-neutral-400">
            {job.canonical_id ?? '—'}
          </span>
        </span>
        <span
          className={
            job.status === 'failed'
              ? 'font-medium text-red-400'
              : job.status === 'stored'
                ? 'font-medium text-emerald-400'
                : 'font-medium text-amber-300'
          }
        >
          {statusLabel(job.status)}
        </span>
      </div>
      {job.url != null && (
        <p className="mt-1 truncate text-xs text-neutral-500">{job.url}</p>
      )}
      {job.status === 'failed' && job.error_type != null && (
        <div className="mt-2 rounded-md border border-red-900/60 bg-red-950/30 p-2 text-xs">
          <p className="text-red-300">
            {job.error_type}
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
        <p className="mt-1 text-red-200">
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
        className="mt-2 rounded-md bg-red-800 px-3 py-1 font-medium text-red-100 hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Retry
      </button>
    );
  }
  if (errorType === 'cookies_expired') {
    return (
      <p className="mt-1 text-red-200">
        The Rednote cookie has expired — follow the cookie-refresh runbook
        (docs/RUNBOOK.md §1).
      </p>
    );
  }
  if (errorType === 'budget_exceeded') {
    return (
      <p className="mt-1 text-red-200">
        Budget cap reached — extraction pauses until the monthly budget or daily
        attempt cap resets.
      </p>
    );
  }
  if (errorType === 'config_error') {
    return (
      <p className="mt-1 text-red-200">
        Check server configuration (budget and adapter settings).
      </p>
    );
  }
  return null;
}
