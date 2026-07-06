import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import {
  getJobApiJobsJobIdGetOptions,
  listJobsApiJobsGetQueryKey,
  listRecipesApiRecipesGetQueryKey,
} from '../client/@tanstack/react-query.gen';
import type { JobOut } from '../client/types.gen';
import { isTerminalStatus, JOB_POLL_MS, statusLabel } from '../lib/job-status';

interface JobChipProps {
  initialJob: JobOut;
  /**
   * Called when the chip is done showing: on `stored` after the recipes list
   * has been invalidated and refetched (the "morph" — the chip leaves as the
   * card(s) arrive), or when a failed chip is dismissed.
   */
  onGone: (jobId: string) => void;
}

/**
 * Inline live-status chip for one extraction job, polling GET /api/jobs/{id}
 * every ~2.5 s while the job is non-terminal.
 */
export function JobChip({ initialJob, onGone }: JobChipProps) {
  const queryClient = useQueryClient();

  const jobQuery = useQuery({
    ...getJobApiJobsJobIdGetOptions({ path: { job_id: initialJob.id } }),
    initialData: initialJob,
    refetchInterval: (query) =>
      query.state.data && isTerminalStatus(query.state.data.status)
        ? false
        : JOB_POLL_MS,
  });

  const job = jobQuery.data ?? initialJob;
  const storedHandled = useRef(false);

  useEffect(() => {
    if (job.status !== 'stored' || storedHandled.current) return;
    storedHandled.current = true;
    void queryClient.invalidateQueries({
      queryKey: listJobsApiJobsGetQueryKey(),
    });
    // Remove the chip only once the fresh list (with the new card) is in.
    void queryClient
      .invalidateQueries({ queryKey: listRecipesApiRecipesGetQueryKey() })
      .then(() => onGone(job.id));
  }, [job.status, job.id, queryClient, onGone]);

  const label = job.url ?? job.canonical_id ?? 'uploaded file';

  if (job.status === 'failed') {
    return (
      <div
        role="status"
        className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-red-900/70 bg-red-950/30 px-3 py-2 text-sm"
      >
        <span className="max-w-64 truncate text-red-200">{label}</span>
        <span className="font-medium text-red-400">
          Failed{job.error_type ? ` — ${job.error_type}` : ''}
        </span>
        {job.error_detail && (
          <span className="max-w-96 truncate text-xs text-red-300/80">
            {job.error_detail}
          </span>
        )}
        <button
          type="button"
          onClick={() => onGone(job.id)}
          className="rounded-md border border-red-800 px-2 py-0.5 text-xs text-red-200 hover:border-red-600"
        >
          Dismiss
        </button>
      </div>
    );
  }

  return (
    <div
      role="status"
      className="flex items-center gap-3 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm"
    >
      <span
        aria-hidden="true"
        className="size-2 shrink-0 animate-pulse rounded-full bg-emerald-400"
      />
      <span className="max-w-64 truncate text-neutral-300">{label}</span>
      <span className="font-medium text-emerald-300">
        {statusLabel(job.status)}
      </span>
    </div>
  );
}
