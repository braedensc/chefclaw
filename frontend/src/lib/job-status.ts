// Job-status vocabulary shared by the chips and the jobs drawer. The status
// strings mirror backend JobStatus (backend/src/chefclaw/models.py) and the
// error_type strings mirror the typed taxonomy (backend/src/chefclaw/errors.py)
// — the API contract the UI maps onto actions (plan §7 screen 3).

/** Poll cadence for non-terminal jobs (chips + open drawer). */
export const JOB_POLL_MS = 2500;

export function isTerminalStatus(status: string): boolean {
  return status === 'stored' || status === 'failed';
}

/**
 * error_type values whose action is a Retry button (re-POST the job's url).
 * cookies_expired / budget_exceeded / config_error get text guidance instead
 * — retrying them without operator action would just fail again.
 */
export const RETRYABLE_ERROR_TYPES: ReadonlySet<string> = new Set([
  'interrupted',
  'download_failed',
  'extraction_failed',
  'rate_limited',
]);

const STATUS_LABELS: Record<string, string> = {
  pending: 'Queued',
  downloading: 'Downloading',
  extracting: 'Extracting',
  validating: 'Validating',
  stored: 'Stored',
  failed: 'Failed',
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}
