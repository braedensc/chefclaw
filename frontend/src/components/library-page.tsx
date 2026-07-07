import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo, useState } from 'react';

import { ApiError } from '../api-error';
import { listRecipesApiRecipesGetOptions } from '../client/@tanstack/react-query.gen';
import type { JobOut, RecipeSummary } from '../client/types.gen';
import { CHILI_BTN } from '../lib/button-styles';
import { useDebouncedValue } from '../lib/use-debounced-value';
import { useAuth } from '../auth-context';
import { PuppyChef } from './brand/puppy-chef';
import { JobChip } from './job-chip';
import { PasteBar } from './paste-bar';
import { RecipeCard } from './recipe-card';
import type { SiblingInfo } from './recipe-card';

const SEARCH_DEBOUNCE_MS = 300;

/**
 * Multi-dish videos share platform+canonical_id — map each grouped recipe id
 * to its "same video · ①/②" ticket (only groups with 2+ visible cards; a
 * card whose siblings are filtered/paged out falls back to its dish_index
 * inside RecipeCard, so the multi-dish mark never disappears).
 */
function computeSiblings(items: RecipeSummary[]): Map<string, SiblingInfo> {
  const groups = new Map<string, RecipeSummary[]>();
  for (const item of items) {
    const key = `${item.platform}\u0000${item.canonical_id}`;
    const group = groups.get(key);
    if (group) group.push(item);
    else groups.set(key, [item]);
  }
  const siblings = new Map<string, SiblingInfo>();
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    const ordered = [...group].sort((a, b) => a.dish_index - b.dish_index);
    ordered.forEach((item, index) => {
      siblings.set(item.id, { index, count: ordered.length });
    });
  }
  return siblings;
}

/**
 * Screen 1 (plan §7): the core loop on one page. Paste bar pinned at top,
 * live job chips inline above the grid, card grid from GET /api/recipes with
 * server-driven search + platform/tag filters — dressed as direction B's
 * night market: neon stall front, marquee tickets, tonight's menu board.
 */
export function LibraryPage() {
  const { signOut } = useAuth();

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

  const recipesData = recipes.data;
  const siblings = useMemo(
    () =>
      recipesData === undefined
        ? new Map<string, SiblingInfo>()
        : computeSiblings(recipesData.items),
    [recipesData],
  );

  // A faint always-on cyan hairline keeps the filter row gently lit at rest
  // (the paste strip, headings, and cards all carry ambient neon — the search
  // chrome shouldn't read as dead); focus still brightens it to cyan/60.
  const fieldClasses =
    'tap-field rounded-field border border-cyan/15 bg-panel px-3.5 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-cyan/60 focus:outline-none';

  return (
    <div>
      {/* top offset matches AppShell's h-14 header */}
      <div className="sticky top-14 z-10 -mx-4 bg-night/95 px-4 py-3 backdrop-blur">
        <PasteBar onJob={addChip} />
      </div>

      {chipJobs.length > 0 && (
        <ul aria-label="Extraction jobs" className="mt-4 flex flex-col gap-3">
          {chipJobs.map((job) => (
            <li key={job.id}>
              <JobChip initialJob={job} onGone={removeChip} />
            </li>
          ))}
        </ul>
      )}

      <div className="mt-5 flex flex-col gap-2.5 sm:flex-row">
        <label className="sr-only" htmlFor="library-search">
          Search recipes
        </label>
        <input
          id="library-search"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search dishes"
          className={`min-w-0 flex-1 ${fieldClasses}`}
        />
        <label className="sr-only" htmlFor="library-platform">
          Platform filter
        </label>
        <select
          id="library-platform"
          value={platform}
          onChange={(event) => setPlatform(event.target.value)}
          className={`${fieldClasses} text-ink-dim`}
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
          className={`${fieldClasses} sm:w-44`}
        />
      </div>

      <section aria-label="Recipe library" className="mt-7">
        {recipes.isPending && (
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <PuppyChef size={110} animated />
            <p className="text-sm text-ink-dim">
              firing up the stalls… <span lang="zh">开火中</span>
            </p>
          </div>
        )}

        {recipes.isError && (
          <div
            role="alert"
            className="glow-chili rounded-card border border-chili/40 bg-chili/5 p-5 text-sm"
          >
            {status === 401 ? (
              <>
                <p className="text-chili-bright">
                  Your session ended (401) — sign in again to continue.
                </p>
                <button
                  type="button"
                  onClick={signOut}
                  className={`mt-3 ${CHILI_BTN}`}
                >
                  Sign in again
                </button>
              </>
            ) : (
              <>
                <p className="text-chili-bright">
                  {status !== null
                    ? `Could not load the library (HTTP ${status}).`
                    : 'Could not reach the API — is the stack running?'}
                </p>
                <button
                  type="button"
                  onClick={() => void recipes.refetch()}
                  className={`mt-3 ${CHILI_BTN}`}
                >
                  Retry
                </button>
              </>
            )}
          </div>
        )}

        {recipes.isSuccess &&
          (recipes.data.items.length === 0 ? (
            <div className="rounded-card border border-line bg-panel-deep px-6 py-10 text-center">
              <PuppyChef size={150} animated className="neon-flicker mx-auto" />
              <p className="glow-text-warm mt-3 font-display text-[16.5px] font-extrabold tracking-[0.22em] text-warm uppercase">
                The stalls are dark{' '}
                <span
                  lang="zh"
                  className="font-body font-medium tracking-[0.1em]"
                >
                  · 还没开张
                </span>
              </p>
              <p className="mx-auto mt-2.5 max-w-xs text-[13px] leading-relaxed text-ink-dim">
                Your cookbook is hungry — paste your first cooking video and get
                that wok going.{' '}
                <span lang="zh" className="text-[#8a8272]">
                  夜市等你点灯。
                </span>
              </p>
              <button
                type="button"
                onClick={() => document.getElementById('paste-url')?.focus()}
                className={`glow-chili mt-5 ${CHILI_BTN}`}
              >
                Paste a link
              </button>
            </div>
          ) : (
            <>
              <div className="mb-4 flex flex-wrap items-baseline gap-3">
                <h2 className="glow-text-warm font-display text-lg font-extrabold tracking-[0.24em] text-warm uppercase">
                  Tonight&rsquo;s menu
                </h2>
                <span
                  lang="zh"
                  className="glow-text-gold text-[13.5px] font-medium tracking-[0.12em] text-gold"
                >
                  今晚的菜单
                </span>
                <span className="font-display text-[10.5px] font-semibold tracking-[0.24em] text-ink-faint uppercase">
                  {recipes.data.total}{' '}
                  {recipes.data.total === 1 ? 'dish' : 'dishes'} on the board
                </span>
                {/* night-market signage rule — a gold hairline trailing to the
                    right edge; hidden on narrow screens where the row wraps. */}
                <span
                  aria-hidden="true"
                  className="hidden h-px min-w-8 flex-1 self-center bg-gradient-to-r from-gold/35 to-transparent sm:block"
                />
              </div>
              <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {recipes.data.items.map((recipe) => (
                  <li key={recipe.id}>
                    <RecipeCard
                      recipe={recipe}
                      sibling={siblings.get(recipe.id)}
                    />
                  </li>
                ))}
              </ul>
            </>
          ))}
      </section>
    </div>
  );
}
