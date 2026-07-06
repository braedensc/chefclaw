/**
 * Typed error for any non-2xx HTTP response.
 *
 * The generated hey-api client throws only the parsed error BODY on a non-2xx
 * response (`throw jsonError ?? textError`) — the status code is lost. The
 * error interceptor registered in api.ts wraps that bare body in this class so
 * callers can branch on `status`. Consequently, a thrown error that is NOT an
 * ApiError means the request never received an HTTP response at all (network
 * failure / API unreachable).
 */
export class ApiError extends Error {
  readonly status: number;
  /** The parsed error body the API returned (e.g. FastAPI's `{ detail }`). */
  readonly body: unknown;

  constructor(status: number, statusText: string, body: unknown) {
    super(
      `API request failed with status ${status}${statusText ? ` ${statusText}` : ''}`,
    );
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}
