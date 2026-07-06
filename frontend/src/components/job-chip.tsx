import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useRef } from 'react';

import {
  getJobApiJobsJobIdGetOptions,
  listJobsApiJobsGetQueryKey,
  listRecipesApiRecipesGetQueryKey,
} from '../client/@tanstack/react-query.gen';
import type { JobOut } from '../client/types.gen';
import { cookingStage } from '../lib/cooking-stages';
import { isTerminalStatus, JOB_POLL_MS } from '../lib/job-status';

interface JobChipProps {
  initialJob: JobOut;
  /**
   * Called when the chip is done showing: on `stored` after the recipes list
   * has been invalidated and refetched (the "morph" — the chip leaves as the
   * card(s) arrive), or when a failed chip is dismissed.
   */
  onGone: (jobId: string) => void;
}

// Marquee bulb rails (direction B .nn-job-rail / .nn-fail-rail): dashed tube
// segments in the accent hue. Static art; the pulse rides motion-safe.
const GOLD_RAIL =
  'repeating-linear-gradient(90deg, var(--color-gold) 0 8px, color-mix(in srgb, var(--color-gold) 14%, transparent) 8px 20px)';
const CHILI_RAIL =
  'repeating-linear-gradient(90deg, color-mix(in srgb, var(--color-chili) 75%, transparent) 0 8px, color-mix(in srgb, var(--color-chili) 12%, transparent) 8px 20px)';

/** Direction A's simmering pot, chip-sized: steam wisps ride .steam-wisp. */
function SimmeringPot() {
  const uid = useId();
  const pot = `${uid}-pot`;
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" className="size-11 flex-none">
      <defs>
        <linearGradient id={pot} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#4a3420" />
          <stop offset="100%" stopColor="#241709" />
        </linearGradient>
      </defs>
      <ellipse cx="32" cy="57.5" rx="15" ry="3.2" fill="#f5a623" />
      <g stroke="#f4e9d4" strokeWidth="2.4" strokeLinecap="round" fill="none">
        <path className="steam-wisp" d="M22 22 C20 18 24 15 22 10" />
        <path
          className="steam-wisp steam-wisp-2"
          d="M32 20 C30 16 34 13 32 7"
        />
        <path
          className="steam-wisp steam-wisp-3"
          d="M42 22 C40 18 44 15 42 10"
        />
      </g>
      <ellipse
        cx="32"
        cy="31"
        rx="20"
        ry="5.5"
        fill="#5a3d20"
        stroke="#3a2712"
        strokeWidth="2"
      />
      <rect x="8" y="33" width="7" height="5.5" rx="2.75" fill="#52381f" />
      <rect x="49" y="33" width="7" height="5.5" rx="2.75" fill="#52381f" />
      <path
        d="M14 33 H50 V45 A9 9 0 0 1 41 54 H23 A9 9 0 0 1 14 45 Z"
        fill={`url(#${pot})`}
        stroke="#3a2712"
        strokeWidth="2"
      />
      <path
        d="M18 38 Q32 41.5 46 38"
        stroke="#f5a623"
        strokeWidth="1.5"
        opacity=".3"
        fill="none"
      />
      <circle
        cx="32"
        cy="25"
        r="3.4"
        fill="#f5a623"
        stroke="#3a2712"
        strokeWidth="1.5"
      />
    </svg>
  );
}

/**
 * Inline live-status chip for one extraction job, polling GET /api/jobs/{id}
 * every ~2.5 s while the job is non-terminal — direction B's marquee ticket
 * housing direction A's simmering pot.
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

  // The job's source stays visible verbatim — the golden suite filters chips
  // by this URL text.
  const label = job.url ?? job.canonical_id ?? 'uploaded file';

  if (job.status === 'failed') {
    return (
      <div
        role="status"
        className="glow-chili overflow-hidden rounded-card border border-chili/40 bg-[#0a0709]"
      >
        <div
          aria-hidden="true"
          className="h-1 motion-safe:animate-pulse"
          style={{ background: CHILI_RAIL, backgroundSize: '20px 4px' }}
        />
        <div className="flex flex-col gap-1 px-4 py-3">
          <span className="glow-text-chili font-display text-[10.5px] font-bold tracking-[0.26em] text-chili-bright uppercase">
            Order dropped{' '}
            <span lang="zh" className="font-body font-medium tracking-[0.16em]">
              · 掉单了
            </span>
          </span>
          <span className="max-w-full truncate font-mono text-[11.5px] text-ink-faint">
            {label}
          </span>
          {job.error_type != null && (
            <span className="self-start rounded-chip border border-dashed border-gold/40 bg-gold/5 px-2 py-0.5 font-mono text-[10.5px] text-gold">
              {job.error_type}
            </span>
          )}
          {job.error_detail != null && (
            <span className="max-w-96 truncate text-xs text-ink-dim">
              {job.error_detail}
            </span>
          )}
          <p className="text-[12.5px] text-ink-dim">
            Nothing burned — the ticket above says why. Paste it again to give
            the wok another go.
          </p>
          <button
            type="button"
            onClick={() => onGone(job.id)}
            className="mt-1 self-start rounded-field border border-chili/50 px-3 py-1 font-display text-xs font-semibold tracking-[0.14em] text-chili-bright uppercase transition hover:bg-chili/10"
          >
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  const stage = cookingStage(job.status);

  return (
    <div
      role="status"
      className="glow-gold overflow-hidden rounded-card border border-gold/40 bg-[#09090b]"
    >
      <div
        aria-hidden="true"
        className="h-1 motion-safe:animate-pulse"
        style={{ background: GOLD_RAIL, backgroundSize: '20px 4px' }}
      />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <SimmeringPot />
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="glow-text-gold font-display text-[10.5px] font-bold tracking-[0.28em] text-gold uppercase">
            Wok&rsquo;s on{' '}
            <span lang="zh" className="font-body font-medium tracking-[0.18em]">
              · 火候到了
            </span>
          </span>
          <span className="max-w-64 truncate font-mono text-[11.5px] text-ink-faint">
            {label}
          </span>
          <span className="glow-text-cyan text-[13px] text-cyan">
            {stage.copy}
          </span>
        </div>
        {stage.step !== null && (
          <div className="ml-auto min-w-44 flex-none basis-full sm:basis-52">
            <div className="h-1.5 overflow-hidden rounded-full bg-[#141418]">
              <span
                className="block h-full rounded-full"
                style={{
                  width: `${(stage.step / stage.total) * 100}%`,
                  background:
                    'linear-gradient(90deg, var(--color-gold), var(--color-chili))',
                  boxShadow: '0 0 12px rgba(255, 120, 90, 0.7)',
                }}
              />
            </div>
            <span className="mt-1.5 block text-right font-display text-[9.5px] font-semibold tracking-[0.26em] text-ink-faint uppercase">
              Step {stage.step} / {stage.total}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
