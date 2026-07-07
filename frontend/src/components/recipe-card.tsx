import { Link } from '@tanstack/react-router';

import type { RecipeSummary } from '../client/types.gen';
import { CoverImage } from './brand/cover-image';
import { DifficultyScale } from './brand/difficulty-scale';
import { platformAccent } from './brand/platform-accents';
import { SpicinessScale } from './brand/spiciness-scale';
import { PlatformBadge } from './platform-badge';

/** Position of a card within a multi-dish video (only passed when count>1). */
export interface SiblingInfo {
  /** 0-based position among the video's dishes (ordered by dish_index). */
  index: number;
  /** Total dishes in the group, or null when unknown (filtered/paged view). */
  count: number | null;
}

const CIRCLED_DIGITS = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩'];

function circled(ordinal: number): string {
  return CIRCLED_DIGITS[ordinal - 1] ?? String(ordinal);
}

/**
 * One library-grid tile — direction B's card: cover art with the bilingual
 * titles on the baked-in scrim, platform badge + sibling ticket overlaid,
 * meta row projected verbatim from the document (absent fields render
 * nothing — Hard Rule 7, never invent food facts).
 */
export function RecipeCard({
  recipe,
  sibling,
}: {
  recipe: RecipeSummary;
  sibling?: SiblingInfo;
}) {
  const accent = platformAccent(recipe.platform);
  // A non-zero dish_index proves a multi-dish video even when filters or
  // paging hide the siblings — the ticket then renders without a total.
  const ticket =
    sibling ??
    (recipe.dish_index > 0
      ? { index: recipe.dish_index, count: null }
      : undefined);
  const zhTitle = recipe.title_original;
  const enTitle = recipe.title_en;
  const altTitle = enTitle ?? zhTitle ?? 'Untitled dish';
  const hasMeta =
    recipe.estimated_spiciness_level != null ||
    recipe.estimated_difficulty_level != null ||
    recipe.total_time_minutes != null ||
    recipe.ingredient_count != null;

  return (
    <Link
      to="/recipes/$id"
      params={{ id: recipe.id }}
      className={`block h-full overflow-hidden rounded-card border border-line bg-panel transition duration-300 motion-safe:hover:-translate-y-1 ${accent.cardHover}`}
    >
      <div className="relative">
        <CoverImage
          recipeId={recipe.id}
          hasImage={recipe.has_image ?? false}
          platform={recipe.platform}
          alt={altTitle}
          className="aspect-[16/10]"
        />
        <span className="absolute top-2.5 right-2.5">
          <PlatformBadge platform={recipe.platform} />
        </span>
        {ticket && (
          <span className="absolute top-2.5 left-2.5 rounded-chip border border-dashed border-gold/45 bg-night/70 px-2 py-0.5 font-display text-[9.5px] font-semibold tracking-[0.16em] text-[#a08d55] uppercase">
            same video ·{' '}
            <b className="glow-text-gold font-bold text-gold">
              {circled(ticket.index + 1)}
            </b>
            {ticket.count !== null && (
              <span className="text-[#5c5645]"> / {circled(ticket.count)}</span>
            )}
          </span>
        )}
        <div className="absolute right-4 bottom-2.5 left-4">
          {zhTitle != null ? (
            <>
              <h3
                lang="zh"
                className={`text-[22px] leading-tight font-semibold tracking-[0.04em] text-white ${accent.titleGlow}`}
              >
                {zhTitle}
              </h3>
              {enTitle != null && (
                <p className="mt-0.5 font-display text-[11.5px] font-semibold tracking-[0.19em] text-[#c9cad4] uppercase">
                  {enTitle}
                </p>
              )}
            </>
          ) : (
            <h3
              className={`font-display text-lg font-semibold tracking-[0.14em] text-white uppercase ${accent.titleGlow}`}
            >
              {enTitle ?? 'Untitled dish'}
            </h3>
          )}
        </div>
      </div>
      {hasMeta && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-3 pb-1 font-display text-[11px] font-semibold tracking-[0.14em] text-ink-dim uppercase">
          <SpicinessScale level={recipe.estimated_spiciness_level} />
          <DifficultyScale level={recipe.estimated_difficulty_level} />
          {recipe.total_time_minutes != null && (
            <span>{recipe.total_time_minutes} min</span>
          )}
          {recipe.ingredient_count != null && (
            <span>
              {recipe.ingredient_count}{' '}
              {recipe.ingredient_count === 1 ? 'ingredient' : 'ingredients'}
            </span>
          )}
        </div>
      )}
      {recipe.tags.length > 0 && (
        <p className="flex flex-wrap gap-1.5 px-4 pt-2 pb-4">
          {recipe.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full border border-line-bright bg-[#0e0e11] px-2.5 py-0.5 font-display text-[10.5px] font-semibold tracking-[0.12em] text-ink-dim uppercase"
            >
              {tag}
            </span>
          ))}
        </p>
      )}
      {/* breathing room when the card ends on the meta row */}
      {hasMeta && recipe.tags.length === 0 && <div className="pb-3" />}
    </Link>
  );
}
