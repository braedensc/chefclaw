import { useQuery } from '@tanstack/react-query';
import { useCallback, useState } from 'react';

import { ApiError } from '../api-error';
import { listRecipesApiRecipesGetOptions } from '../client/@tanstack/react-query.gen';
import type { JobOut } from '../client/types.gen';
import { useDebouncedValue } from '../lib/use-debounced-value';
import { useTokenActions } from '../token-context';
import { JobChip } from './job-chip';
import { PasteBar } from './paste-bar';
import { RecipeCard } from './recipe-card';

const SEARCH_DEBOUNCE_MS = 300;

/**
 * Screen 1 (plan §7): the core loop on one page. Paste bar pinned at top,
 * live job chips inline above the grid, card grid from GET /api/recipes with
 * server-driven search + platform/tag filters.
 */
export function LibraryPage() {
  const { clearToken } = useTokenActions();

  // Jobs pasted/uploaded this session — each renders a polling chip until it
  // morphs into card(s) (stored) or is dismissed (failed).
  const [chipJobs, setChipJobs] = useState<JobOut[]>([]);
  const addChip = useCallback((job: JobOut) => {
    setChipJobs((prev) =>
      prev.some((existing) => existing.id === job.id) ? prev : [...prev, job],
    );
  }, []);
  const removeChip = useCallback((jobId: string) => {
    setChipJobs((prev) => prev.filter((job) => job.id !== jobId));
  }, []);

  const [search, setSearch] = useState('');
  const [platform, setPlatform] = useState('');
  const [tag, setTag] = useState('');
  const debouncedSearch = useDebouncedValue(search.trim(), SEARCH_DEBOUNCE_MS);
  const debouncedTag = useDebouncedValue(tag.trim(), SEARCH_DEBOUNCE_MS);

  const query: { q?: string; platform?: string; tag?: string } = {};
  if (debouncedSearch) query.q = debouncedSearch;
  if (platform) query.platform = platform;
  if (debouncedTag) query.tag = debouncedTag;

  const recipes = useQuery(
    listRecipesApiRecipesGetOptions(
      Object.keys(query).length > 0 ? { query } : undefined,
    ),
  );

  const status =
    recipes.error instanceof ApiError ? recipes.error.status : null;

  return (
    <div>
      <div className="sticky top-14 z-10 -mx-4 border-b border-neutral-800/80 bg-neutral-950/95 px-4 py-3 backdrop-blur">
        <PasteBar onJob={addChip} />
      </div>

      {chipJobs.length > 0 && (
        <ul aria-label="Extraction jobs" className="mt-4 flex flex-wrap gap-2">
          {chipJobs.map((job) => (
            <li key={job.id}>
              <JobChip initialJob={job} onGone={removeChip} />
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <label className="sr-only" htmlFor="library-search">
          Search recipes
        </label>
        <input
          id="library-search"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search dishes"
          className="min-w-0 flex-1 rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-sm text-neutral-100 placeholder:text-neutral-500 focus:border-emerald-500 focus:outline-none"
        />
        <label className="sr-only" htmlFor="library-platform">
          Platform filter
        </label>
        <select
          id="library-platform"
          value={platform}
          onChange={(event) => setPlatform(event.target.value)}
          className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-sm text-neutral-100 focus:border-emerald-500 focus:outline-none"
        >
          <option value="">All platforms</option>
          <option value="bilibili">bilibili</option>
          <option value="rednote">rednote</option>
          <option value="local">local</option>
        </select>
        <label className="sr-only" htmlFor="library-tag">
          Tag filter
        </label>
        <input
          id="library-tag"
          type="text"
          value={tag}
          onChange={(event) => setTag(event.target.value)}
          placeholder="Filter by tag"
          className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-sm text-neutral-100 placeholder:text-neutral-500 focus:border-emerald-500 focus:outline-none sm:w-44"
        />
      </div>

      <section aria-label="Recipe library" className="mt-6">
        {recipes.isPending && (
          <p className="text-sm text-neutral-400">Loading library…</p>
        )}

        {recipes.isError && (
          <div
            role="alert"
            className="rounded-md border border-red-900 bg-red-950/40 p-4 text-sm"
          >
            {status === 401 ? (
              <>
                <p className="text-red-300">
                  Token rejected (401) — clear the token and re-enter it.
                </p>
                <button
                  type="button"
                  onClick={clearToken}
                  className="mt-3 rounded-md bg-red-800 px-3 py-1.5 text-xs font-medium text-red-100 hover:bg-red-700"
                >
                  Clear token & re-enter
                </button>
              </>
            ) : (
              <>
                <p className="text-red-300">
                  {status !== null
                    ? `Could not load the library (HTTP ${status}).`
                    : 'Could not reach the API — is the stack running?'}
                </p>
                <button
                  type="button"
                  onClick={() => void recipes.refetch()}
                  className="mt-3 rounded-md bg-red-800 px-3 py-1.5 text-xs font-medium text-red-100 hover:bg-red-700"
                >
                  Retry
                </button>
              </>
            )}
          </div>
        )}

        {recipes.isSuccess &&
          (recipes.data.items.length === 0 ? (
            <p className="rounded-lg border border-dashed border-neutral-800 p-8 text-center text-sm text-neutral-500">
              No recipes yet — paste a cooking-video link above to start the
              library.
            </p>
          ) : (
            <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {recipes.data.items.map((recipe) => (
                <li key={recipe.id}>
                  <RecipeCard recipe={recipe} />
                </li>
              ))}
            </ul>
          ))}
      </section>
    </div>
  );
}
