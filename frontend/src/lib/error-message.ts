import { ApiError } from '../api-error';

/**
 * Human-readable message for a failed request. ApiError carries the HTTP
 * status and the typed `{ error_type, detail }` body (see api-error.ts); any
 * other error means the API never answered at all.
 */
export function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const body = error.body as {
      error_type?: unknown;
      detail?: unknown;
    } | null;
    if (typeof body?.detail === 'string') {
      return typeof body.error_type === 'string'
        ? `${body.error_type}: ${body.detail}`
        : body.detail;
    }
    return `Request failed (HTTP ${error.status})`;
  }
  return 'Could not reach the API — is the stack running?';
}
