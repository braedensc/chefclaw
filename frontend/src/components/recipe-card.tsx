import { Link } from '@tanstack/react-router';

import type { RecipeSummary } from '../client/types.gen';
import { PlatformBadge } from './platform-badge';

// Deliberately no thumbnails in Phase 3 (no cover pipeline yet) — the card is
// a text-on-gradient tile keyed to the platform accent instead.
const CARD_GRADIENTS: Record<string, string> = {
  bilibili: 'from-sky-950/50 via-neutral-900 to-neutral-900',
  rednote: 'from-rose-950/50 via-neutral-900 to-neutral-900',
  local: 'from-neutral-800/50 via-neutral-900 to-neutral-900',
};

const FALLBACK_GRADIENT = 'from-neutral-800/50 via-neutral-900 to-neutral-900';

/** One library-grid tile: bilingual dish name + platform badge + tags. */
export function RecipeCard({ recipe }: { recipe: RecipeSummary }) {
  const gradient = CARD_GRADIENTS[recipe.platform] ?? FALLBACK_GRADIENT;

  return (
    <Link
      to="/recipes/$id"
      params={{ id: recipe.id }}
      className={`block h-full rounded-xl border border-neutral-800 bg-gradient-to-br p-4 transition hover:border-neutral-500 ${gradient}`}
    >
      <div className="flex items-start justify-between gap-2">
        <PlatformBadge platform={recipe.platform} />
        {recipe.dish_index > 0 && (
          <span className="text-xs text-neutral-500">
            dish {recipe.dish_index + 1}
          </span>
        )}
      </div>
      <h3 className="mt-3 text-base font-semibold text-neutral-100">
        {recipe.title_en ?? recipe.title_original ?? 'Untitled dish'}
      </h3>
      {recipe.title_en != null && recipe.title_original != null && (
        <p lang="zh" className="mt-1 text-sm text-neutral-400">
          {recipe.title_original}
        </p>
      )}
      {recipe.tags.length > 0 && (
        <p className="mt-3 flex flex-wrap gap-1.5">
          {recipe.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full bg-neutral-800/80 px-2 py-0.5 text-xs text-neutral-300"
            >
              {tag}
            </span>
          ))}
        </p>
      )}
    </Link>
  );
}
