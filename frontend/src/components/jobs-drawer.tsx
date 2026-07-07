import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  extractRecipeApiRecipesExtractPostMutation,
  listJobsApiJobsGetOptions,
  listJobsApiJobsGetQueryKey,
  regenerateIllustrationApiRecipesRecipeIdIllustrationPostMutation,
} from '../client/@tanstack/react-query.gen';
import type { JobOut } from '../client/types.gen';
import { apiErrorMessage } from '../lib/error-message';
import {
  isTerminalStatus,
  JOB_POLL_MS,
  RETRYABLE_ERROR_TYPES,
  statusLabel,
} from '../lib/job-status';
import { STRIP_LIGHT } from './brand/platform-accents';
import { SteamWisps } from './brand/steam-wisps';
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

  const invalidateJobs = () =>
    void queryClient.invalidateQueries({
      queryKey: listJobsApiJobsGetQueryKey(),
    });

  // Extract/upload jobs retry by re-POSTing the pasted url; illustration jobs
  // retry by re-enqueueing an illustration job for their recipe.
  const retry = useMutation({
    ...extractRecipeApiRecipesExtractPostMutation(),
    onSuccess: invalidateJobs,
  });
  const retryIllustration = useMutation({
    ...regenerateIllustrationApiRecipesRecipeIdIllustrationPostMutation(),
    onSuccess: invalidateJobs,
  });

  const sorted = [...(jobs.data ?? [])].sort((a, b) => {
    const aTerminal = isTerminalStatus(a.status) ? 1 : 0;
    const bTerminal = isTerminalStatus(b.status) ? 1 : 0;
    if (aTerminal !== bTerminal) return aTerminal - bTerminal; // active first
    return b.updated_at.localeCompare(a.updated_at); // then newest activity
  });

  return (
    <>
      {/* Tap-scrim — mobile only (the ≥sm right rail keeps its scrim-less look).
          Dismisses the sheet on a tap outside it. */}
      <button
        type="button"
        aria-hidden="true"
        tabIndex={-1}
        onClick={onClose}
        className="scrim-in fixed inset-0 z-30 bg-night/70 backdrop-blur-sm sm:hidden"
      />
      <aside
        aria-label="Jobs"
        className="jobs-enter fixed inset-x-0 bottom-0 top-auto z-40 flex max-h-[85vh] flex-col rounded-t-card border-t border-line bg-panel shadow-2xl shadow-black sm:inset-y-0 sm:right-0 sm:left-auto sm:max-h-none sm:w-full sm:max-w-md sm:rounded-t-none sm:border-t-0 sm:border-l"
      >
        {/* neon strip light along the top of the stall (B's paste-bar ::before) */}
        <div
          aria-hidden="true"
          className="h-px shrink-0 rounded-t-card opacity-80 sm:rounded-none"
          style={{ background: STRIP_LIGHT }}
        />
        {/* bottom-sheet grab handle — mobile only; a second tap-to-close target
            in thumb reach at the top of the sheet. */}
        <button
          type="button"
          aria-hidden="true"
          tabIndex={-1}
          onClick={onClose}
          className="mx-auto mt-2 h-1.5 w-10 shrink-0 rounded-full bg-line-bright sm:hidden"
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
            className="tap-target rounded-field border border-line-bright px-3 py-1 font-display text-[11px] font-semibold tracking-[0.16em] text-ink-dim uppercase transition hover:border-cyan/55 hover:text-cyan"
          >
            Close
          </button>
        </div>

        <div className="flex-1 overflow-y-auto overscroll-contain p-4">
          {(retry.isError || retryIllustration.isError) && (
            <p
              role="alert"
              className="mb-3 rounded-field border border-chili/40 bg-chili/5 p-2.5 text-xs text-chili-bright"
            >
              Retry failed —{' '}
              {apiErrorMessage(retry.error ?? retryIllustration.error)}
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
                  retryPending={retry.isPending || retryIllustration.isPending}
                  onRetry={(url) => retry.mutate({ body: { url } })}
                  onRetryIllustration={(recipeId) =>
                    retryIllustration.mutate({ path: { recipe_id: recipeId } })
                  }
                />
              ))}
            </ul>
          )}
        </div>
      </aside>
    </>
  );
}

/** Simmering-pot accent for active rows — wisps animate reduced-motion-guarded. */
function SteamAccent() {
  // The viewBox frames the shared 64-space trio at the same on-screen size,
  // position, and stroke weight the old hand-drawn 24-space copy had.
  return (
    <svg
      viewBox="14 -6 36 36"
      aria-hidden="true"
      className="size-4 shrink-0 text-warm"
    >
      <SteamWisps
        stroke="currentColor"
        strokeWidth={3}
        opacities={[0.45, 0.65, 0.45]}
      />
    </svg>
  );
}

interface JobRowProps {
  job: JobOut;
  retryPending: boolean;
  onRetry: (url: string) => void;
  onRetryIllustration: (recipeId: string) => void;
}

function JobRow({
  job,
  retryPending,
  onRetry,
  onRetryIllustration,
}: JobRowProps) {
  const active = !isTerminalStatus(job.status);
  const isIllustration = job.type === 'illustration';
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
            {isIllustration ? 'Cover illustration' : (job.canonical_id ?? '—')}
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
            onRetryIllustration={onRetryIllustration}
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
  onRetryIllustration: (recipeId: string) => void;
}

/**
 * Human, actionable copy for every error_type — no bare "Error"/"Try again".
 * Retryable types render this line ABOVE a Retry button; non-retryable types
 * render it as the sole guidance. error_type strings mirror the backend
 * taxonomy (backend/src/chefclaw/errors.py); the substrings the jobs-drawer
 * tests + golden contract pin (docs/RUNBOOK.md, "Budget cap reached", "Check
 * server configuration") are preserved verbatim.
 */
const ERROR_GUIDANCE: Record<string, string> = {
  // ── retryable (transient) — a Retry button follows this line ──────────────
  download_failed:
    "Couldn't download the video — a network hiccup, or the post may be private or region-locked. Retry to try again.",
  extraction_failed:
    'The video downloaded but the recipe extraction failed. This is usually transient — retry to try again.',
  rate_limited:
    'The platform or AI service throttled us. Give it a moment, then retry.',
  interrupted:
    'The server restarted while this job was running — nothing was charged. Retry to pick it back up.',
  illustration_failed:
    "The cover illustration couldn't be generated. The recipe is already saved — retry just the cover.",
  // ── non-retryable — retrying would fail identically, so guidance only ─────
  cookies_expired:
    'The Rednote session has expired — refresh the cookie per the runbook (docs/RUNBOOK.md §1), then paste the link again.',
  budget_exceeded:
    'Budget cap reached — extraction pauses until the monthly budget or daily attempt cap resets.',
  config_error:
    'Check server configuration (budget caps, API keys, and adapter settings) — the server refused to run a paid call.',
  unsupported_url:
    "That link isn't a supported cooking video. chefclaw reads Bilibili and Rednote (Xiaohongshu) video links — double-check the URL and paste a video link.",
  image_note_unsupported:
    'This Rednote post is an image gallery (图文), not a video. chefclaw reads recipes from cooking videos — paste a video post instead.',
  validation_failed:
    "chefclaw read the video but the result didn't form a valid recipe — it may not be a cooking video, or the layout was unusual. Nothing was saved.",
  upload_too_large:
    'That file is over the upload size limit. Trim or compress the video, then upload it again.',
};

const GENERIC_GUIDANCE =
  'Something went wrong on the server. Check the server logs; if it keeps happening, it may be a bug.';

function GuidanceLine({ errorType }: { errorType: string }) {
  return (
    <p className="mt-1.5 text-ink-dim">
      {ERROR_GUIDANCE[errorType] ?? GENERIC_GUIDANCE}
    </p>
  );
}

/** Maps the typed error taxonomy onto UI actions (plan §7 screen 3). */
function JobErrorAction({
  job,
  errorType,
  retryPending,
  onRetry,
  onRetryIllustration,
}: JobErrorActionProps) {
  if (RETRYABLE_ERROR_TYPES.has(errorType)) {
    // Illustration jobs retry by re-enqueueing an illustration job for their
    // recipe (never re-POSTing an extract url — they have none).
    if (job.type === 'illustration') {
      const recipeId = job.recipe_ids?.[0];
      return (
        <>
          <GuidanceLine errorType={errorType} />
          <button
            type="button"
            disabled={recipeId == null || retryPending}
            onClick={() => {
              if (recipeId != null) onRetryIllustration(recipeId);
            }}
            className="tap-target mt-2 rounded-field border border-cyan/60 bg-cyan/10 px-3.5 py-1.5 font-display text-[11px] font-bold tracking-[0.16em] text-cyan uppercase glow-cyan transition hover:bg-cyan/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Retry
          </button>
        </>
      );
    }
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
      <>
        <GuidanceLine errorType={errorType} />
        <button
          type="button"
          disabled={job.url == null || retryPending}
          onClick={() => {
            if (job.url != null) onRetry(job.url);
          }}
          className="tap-target mt-2 rounded-field border border-cyan/60 bg-cyan/10 px-3.5 py-1.5 font-display text-[11px] font-bold tracking-[0.16em] text-cyan uppercase glow-cyan transition hover:bg-cyan/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Retry
        </button>
      </>
    );
  }
  // Every non-retryable type gets a specific, actionable line (falling back to
  // GENERIC_GUIDANCE for an unrecognized type) — never a bare error string.
  return <GuidanceLine errorType={errorType} />;
}
