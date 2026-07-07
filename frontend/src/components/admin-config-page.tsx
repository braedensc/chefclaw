import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { ApiError } from '../api-error';
import { useAuth } from '../auth-context';
import {
  getConfigApiAdminConfigGetOptions,
  getConfigApiAdminConfigGetQueryKey,
  patchConfigApiAdminConfigPatchMutation,
} from '../client/@tanstack/react-query.gen';
import type { RuntimeConfigItem } from '../client/types.gen';
import { CYAN_BTN } from '../lib/button-styles';

const CATEGORY_ORDER = ['covers', 'models', 'budget'] as const;
const CATEGORY_LABEL: Record<string, string> = {
  covers: 'Covers',
  models: 'Model tier',
  budget: 'Budget',
};

const fieldClasses =
  'rounded-field border-line-bright bg-night text-ink placeholder:text-ink-faint focus:border-gold h-10 border px-3 text-sm focus:outline-none';

/** The server's typed 422 body ({ error_type, detail }) carries a per-field
 * message; surface it verbatim so an invalid value (or a resolution ceiling not
 * above the base) is explained inline. */
function patchErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const body = error.body as { detail?: string } | null;
    if (body?.detail) return body.detail;
    return `Could not save (HTTP ${error.status}).`;
  }
  return 'Could not reach the API.';
}

/**
 * Admin runtime-policy config (/admin/config, ADR admin-config-panel). COSMETIC-
 * gated on me.is_admin — every /api/admin/* route enforces admin server-side.
 * Edits the closed allowlist of runtime-policy flags (cover mode, model tier,
 * budget); changes take effect on the NEXT job, no restart. Secrets are shown as
 * STATUS ONLY (never a value); deploy/infra is read-only.
 */
export function AdminConfigPage() {
  const { me } = useAuth();
  const config = useQuery(getConfigApiAdminConfigGetOptions());

  if (!me.is_admin) {
    return (
      <div className="mx-auto max-w-2xl">
        <h1 className="text-warm font-display text-[22px] font-extrabold tracking-[0.24em] uppercase">
          Config
        </h1>
        <p className="text-ink-dim mt-4 text-sm">
          You don't have access to configuration.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-warm glow-text-warm font-display text-[22px] font-extrabold tracking-[0.24em] uppercase">
        Config
      </h1>
      <p className="text-ink-faint mt-1 font-display text-[10px] font-semibold tracking-[0.3em] uppercase">
        runtime policy · takes effect next job, no restart
      </p>

      {config.isPending && (
        <p className="text-ink-dim mt-4 text-sm">Loading config…</p>
      )}
      {config.isError && (
        <p className="text-ink-dim mt-4 text-sm">
          Could not load config (are you signed in as an admin?).
        </p>
      )}
      {config.isSuccess && (
        <>
          {CATEGORY_ORDER.map((category) => (
            <RuntimeSection
              key={category}
              category={category}
              items={config.data.runtime_policy.filter(
                (item) => item.category === category,
              )}
            />
          ))}

          <section
            aria-label="Secrets"
            className="rounded-card border-line bg-panel mt-4 border p-5"
          >
            <h2 className="text-ink-faint font-display text-[11px] font-bold tracking-[0.28em] uppercase">
              Secrets (status only)
            </h2>
            <p className="text-ink-faint mt-1 text-xs">
              Server-only — never web-editable. Set in <code>.env.local</code>.
            </p>
            <ul className="mt-3 space-y-1.5 text-sm">
              {config.data.secrets.map((secret) => (
                <li
                  key={secret.key}
                  className="flex items-center justify-between gap-3"
                >
                  <code className="text-ink-dim text-xs">{secret.key}</code>
                  <span
                    className={
                      secret.configured ? 'text-cyan' : 'text-ink-faint'
                    }
                  >
                    {secret.configured ? 'configured' : 'not set'}
                  </span>
                </li>
              ))}
            </ul>
          </section>

          <section
            aria-label="Infrastructure"
            className="rounded-card border-line bg-panel mt-4 border p-5"
          >
            <h2 className="text-ink-faint font-display text-[11px] font-bold tracking-[0.28em] uppercase">
              Deploy / infra (read-only)
            </h2>
            <p className="text-ink-faint mt-1 text-xs">
              Env-only — needs a restart to change.
            </p>
            <ul className="mt-3 space-y-1.5 text-sm">
              {config.data.infra.map((item) => (
                <li
                  key={item.key}
                  className="flex flex-wrap items-center justify-between gap-x-3"
                >
                  <code className="text-ink-dim text-xs">{item.key}</code>
                  <span className="text-ink break-all">
                    {item.value || <span className="text-ink-faint">—</span>}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}

function RuntimeSection({
  category,
  items,
}: {
  category: string;
  items: RuntimeConfigItem[];
}) {
  if (items.length === 0) return null;
  return (
    <section
      aria-label={CATEGORY_LABEL[category] ?? category}
      className="rounded-card border-line bg-panel mt-4 border p-5"
    >
      <h2 className="text-ink-faint font-display text-[11px] font-bold tracking-[0.28em] uppercase">
        {CATEGORY_LABEL[category] ?? category}
      </h2>
      <div className="mt-3 space-y-5">
        {items.map((item) => (
          // Key by the persisted state so a successful save (which changes
          // source/override) remounts the row and re-seeds its input.
          <RuntimeRow
            key={`${item.key}:${item.source}:${item.override_value ?? ''}`}
            item={item}
          />
        ))}
      </div>
    </section>
  );
}

function RuntimeRow({ item }: { item: RuntimeConfigItem }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(item.effective_value);
  const inputId = `cfg-${item.key}`;

  const save = useMutation({
    ...patchConfigApiAdminConfigPatchMutation(),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: getConfigApiAdminConfigGetQueryKey(),
      }),
  });

  const dirty = value !== item.effective_value;
  const isOverride = item.source === 'override';

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label
          htmlFor={inputId}
          className="text-ink font-display text-xs font-semibold tracking-[0.06em] uppercase"
        >
          {item.key}
        </label>
        <span
          className={`font-display text-[9px] font-bold tracking-[0.2em] uppercase ${
            isOverride ? 'text-cyan' : 'text-ink-faint'
          }`}
        >
          {isOverride ? 'override' : 'env default'}
        </span>
      </div>
      <p className="text-ink-faint mt-1 text-xs">{item.description}</p>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {item.choices.length > 0 ? (
          <select
            id={inputId}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            className={`${fieldClasses} text-ink-dim`}
          >
            {item.choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice === '' ? 'off (empty)' : choice}
              </option>
            ))}
          </select>
        ) : (
          <input
            id={inputId}
            type="text"
            autoComplete="off"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="(empty)"
            className={`${fieldClasses} flex-1`}
          />
        )}
        <button
          type="button"
          aria-label={`Save ${item.key}`}
          disabled={!dirty || save.isPending}
          onClick={() =>
            save.mutate({ body: { updates: { [item.key]: value } } })
          }
          className={`${CYAN_BTN} disabled:opacity-40`}
        >
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
        {isOverride && (
          <button
            type="button"
            aria-label={`Reset ${item.key} to env default`}
            disabled={save.isPending}
            onClick={() =>
              save.mutate({ body: { updates: { [item.key]: null } } })
            }
            className="tap-target text-ink-faint hover:text-cyan text-xs underline"
          >
            reset to env
          </button>
        )}
      </div>

      {isOverride && (
        <p className="text-ink-faint mt-1 text-xs">
          env default:{' '}
          <span className="text-ink-dim">{item.env_value || '(empty)'}</span>
        </p>
      )}
      {save.isError && (
        <p className="text-chili-bright mt-1 text-xs">
          {patchErrorMessage(save.error)}
        </p>
      )}
    </div>
  );
}
