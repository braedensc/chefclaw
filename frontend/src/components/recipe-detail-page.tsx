import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from '@tanstack/react-router';
import { Fragment, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';

import { ApiError } from '../api-error';
import {
  deleteRecipeApiRecipesRecipeIdDeleteMutation,
  getRecipeApiRecipesRecipeIdGetOptions,
  getRecipeApiRecipesRecipeIdGetQueryKey,
  listJobsApiJobsGetQueryKey,
  listRecipesApiRecipesGetOptions,
  listRecipesApiRecipesGetQueryKey,
  patchRecipeApiRecipesRecipeIdPatchMutation,
  regenerateIllustrationApiRecipesRecipeIdIllustrationPostMutation,
} from '../client/@tanstack/react-query.gen';
import type { RecipeDetail } from '../client/types.gen';
import { apiErrorMessage } from '../lib/error-message';
import { asRecipeDoc, englishQuantity } from '../lib/recipe-document';
import type { IngredientDoc, RecipeDoc, StepDoc } from '../lib/recipe-document';
import { CoverImage } from './brand/cover-image';
import { DIFFICULTY_WORDS, DifficultyScale } from './brand/difficulty-scale';
import {
  fallbackCoverGradient,
  platformAccent,
} from './brand/platform-accents';
import { PuppyChef } from './brand/puppy-chef';
import { SPICINESS_WORDS, SpicinessScale } from './brand/spiciness-scale';
import { PlatformBadge } from './platform-badge';

/**
 * Screen 2 (plan §7): full recipe — ingredients with the 原文 toggle, steps
 * with visual cues + technique notes, tips, source attribution, related
 * dishes from the same video, the raw-JSON drawer, tags/notes editing, and
 * hard delete. Styled to direction B (neon night-market): glow lives in
 * halo shadows on hairline borders, never flat neon fills.
 */
export function RecipeDetailPage() {
  const { id } = useParams({ from: '/recipes/$id' });
  const detailQuery = useQuery(
    getRecipeApiRecipesRecipeIdGetOptions({ path: { recipe_id: id } }),
  );

  if (detailQuery.isPending) {
    return (
      <div className="flex flex-col items-center gap-4 py-16 text-center">
        <PuppyChef variant="sleeping" size={150} />
        <p className="font-display text-[13px] font-semibold tracking-[0.24em] text-ink-dim uppercase">
          plating up…{' '}
          <span lang="zh" className="tracking-[0.1em] text-warm">
            上菜中
          </span>
        </p>
      </div>
    );
  }

  if (detailQuery.isError) {
    const status =
      detailQuery.error instanceof ApiError ? detailQuery.error.status : null;
    return (
      <div role="alert" className="mx-auto max-w-md py-12 text-center text-sm">
        <p className="text-chili-bright">
          {status === 404
            ? 'Recipe not found — it may have been deleted.'
            : apiErrorMessage(detailQuery.error)}
        </p>
        <Link
          to="/"
          className="mt-4 inline-block text-ink-dim underline decoration-line-bright underline-offset-4 transition hover:text-cyan"
        >
          Back to library
        </Link>
      </div>
    );
  }

  const detail = detailQuery.data;
  const doc = asRecipeDoc(detail.document);

  return (
    <article className="pb-16">
      <Link
        to="/"
        className="font-display text-[11.5px] font-semibold tracking-[0.2em] text-ink-faint uppercase transition hover:text-cyan"
      >
        ← Back to library
      </Link>

      <RecipeHero detail={detail} doc={doc} />

      <IngredientsSection ingredients={doc.ingredients} />

      {doc.equipment.length > 0 && (
        <p className="mt-6 text-sm text-ink-dim">
          <span className="mr-2 font-display text-[10.5px] font-bold tracking-[0.24em] text-ink-faint uppercase">
            Equipment
          </span>
          {doc.equipment.join(' · ')}
        </p>
      )}

      <StepsSection steps={doc.steps} />

      {doc.tips.length > 0 && (
        <section aria-label="Tips" className="mt-10">
          <SectionHeading en="From the chef" zh="小贴士" />
          <ul className="mt-4 space-y-3">
            {doc.tips.map((tip) => (
              <li
                key={tip}
                className="rounded-r-field border-l-2 border-warm/50 bg-warm/5 py-2.5 pr-3 pl-4 text-sm leading-relaxed text-ink-dim"
              >
                {tip}
              </li>
            ))}
          </ul>
        </section>
      )}

      <SourceSection detail={detail} doc={doc} />

      <RelatedDishes detail={detail} />

      <RawJsonDrawer detail={detail} />

      <MetaEditor key={detail.id} detail={detail} />

      <DeleteControl recipeId={detail.id} />
    </article>
  );
}

/** Section signage: tracked warm caps with the ZH sub in gold (direction B). */
function SectionHeading({ en, zh }: { en: string; zh?: string }) {
  return (
    <h2 className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
      <span className="font-display text-[15px] font-bold tracking-[0.22em] text-warm uppercase glow-text-warm">
        {en}
      </span>
      {zh != null && (
        <span lang="zh" className="text-[13px] font-medium text-gold">
          {zh}
        </span>
      )}
    </h2>
  );
}

function RecipeHero({ detail, doc }: { detail: RecipeDetail; doc: RecipeDoc }) {
  const zhTitle = detail.title_original;
  const enTitle = detail.title_en;
  // Platform-hued halo for the ZH display title (B's .nn-zht treatment) and
  // the no-cover header's corner tint (same hues CoverImage's fallback uses).
  const { titleGlow: glow, tint } = platformAccent(detail.platform);

  // One heading holds both languages: ZH leads with the platform halo, EN runs
  // as tracked condensed caps — so heading-by-EN-title selectors still match.
  const titleBlock = (
    <h1>
      {zhTitle != null && (
        <span
          lang="zh"
          className={`block font-display text-3xl leading-tight font-semibold text-white sm:text-4xl ${glow}`}
        >
          {zhTitle}
        </span>
      )}
      {enTitle != null ? (
        <span className="mt-1.5 block font-display text-sm font-semibold tracking-[0.19em] text-ink uppercase sm:text-base">
          {enTitle}
        </span>
      ) : (
        zhTitle == null && (
          <span className="block font-display text-lg font-semibold tracking-[0.19em] text-ink uppercase">
            Untitled dish
          </span>
        )
      )}
    </h1>
  );

  return (
    <header className="mt-4">
      {detail.has_image ? (
        <div className="relative overflow-hidden rounded-card border border-line">
          <CoverImage
            recipeId={detail.id}
            hasImage
            platform={detail.platform}
            alt={`${zhTitle ?? enTitle ?? 'Untitled dish'} — cover photo`}
            className="aspect-[21/9] w-full"
          />
          <span className="absolute top-3 right-3">
            <PlatformBadge platform={detail.platform} />
          </span>
          <div className="absolute inset-x-0 bottom-0 p-4 sm:p-6">
            {titleBlock}
          </div>
        </div>
      ) : (
        <div
          className="relative overflow-hidden rounded-card border border-line p-5 sm:p-7"
          style={{ background: fallbackCoverGradient(tint, 13) }}
        >
          <span className="mb-3 inline-block">
            <PlatformBadge platform={detail.platform} />
          </span>
          {titleBlock}
        </div>
      )}
      <HeroMeta detail={detail} doc={doc} />
      <RegenerateIllustration
        recipeId={detail.id}
        hasImage={detail.has_image ?? false}
      />
    </header>
  );
}

/**
 * Enqueue a fresh cover illustration (its own retriable job). The new image
 * appears once the worker processes the job — so this confirms the enqueue and
 * points at the Jobs drawer rather than optimistically swapping the cover.
 */
function RegenerateIllustration({
  recipeId,
  hasImage,
}: {
  recipeId: string;
  hasImage: boolean;
}) {
  const queryClient = useQueryClient();
  const regenerate = useMutation({
    ...regenerateIllustrationApiRecipesRecipeIdIllustrationPostMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: listJobsApiJobsGetQueryKey(),
      });
    },
  });

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
      <button
        type="button"
        disabled={regenerate.isPending}
        onClick={() => regenerate.mutate({ path: { recipe_id: recipeId } })}
        className="rounded-field border border-line-bright px-3.5 py-1.5 font-display text-[11px] font-semibold tracking-[0.16em] text-ink-dim uppercase transition hover:border-cyan/55 hover:text-cyan disabled:opacity-50"
      >
        {hasImage ? 'Regenerate illustration' : 'Generate illustration'}
      </button>
      {regenerate.isSuccess && !regenerate.isPending && (
        <span className="text-xs text-gold">
          Queued — the new cover appears once it&rsquo;s cooked. Track it in
          Jobs.
        </span>
      )}
      {regenerate.isError && (
        <span role="alert" className="text-xs text-chili-bright">
          {apiErrorMessage(regenerate.error)}
        </span>
      )}
    </div>
  );
}

/**
 * Letterspaced-caps meta pills — the spiciness/difficulty scales carry
 * recipe-level ESTIMATES (from `detail`, flagged estimated), time/serves/
 * cuisine come verbatim from the document; dot-separated.
 */
function HeroMeta({ detail, doc }: { detail: RecipeDetail; doc: RecipeDoc }) {
  // Once the owner has corrected the estimates (source "user") they are no
  // longer the model's guess, so the "(estimated)" affordance drops.
  const isEstimate = detail.estimated_source !== 'user';
  const items: ReactNode[] = [];
  if (detail.estimated_spiciness_level != null) {
    items.push(
      <SpicinessScale
        key="spiciness"
        level={detail.estimated_spiciness_level}
        estimated={isEstimate}
      />,
    );
  }
  if (detail.estimated_difficulty_level != null) {
    items.push(
      <DifficultyScale
        key="difficulty"
        level={detail.estimated_difficulty_level}
        estimated={isEstimate}
      />,
    );
  }
  if (doc.total_time_minutes != null) {
    items.push(<span key="time">{doc.total_time_minutes} min</span>);
  }
  if (doc.servings != null) {
    items.push(<span key="servings">serves {doc.servings}</span>);
  }
  if (doc.cuisine_type != null) {
    items.push(<span key="cuisine">{doc.cuisine_type}</span>);
  }
  if (items.length === 0) return null;

  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-2.5 gap-y-2 font-display text-[11.5px] font-semibold tracking-[0.14em] text-ink-dim uppercase">
      {items.map((item, index) => (
        <Fragment key={index}>
          {index > 0 && (
            <span aria-hidden="true" className="text-line-bright">
              ·
            </span>
          )}
          {item}
        </Fragment>
      ))}
    </div>
  );
}

function IngredientsSection({ ingredients }: { ingredients: IngredientDoc[] }) {
  const [showOriginal, setShowOriginal] = useState(false);

  return (
    <section aria-label="Ingredients" className="mt-10">
      <div className="flex items-center justify-between gap-4">
        <SectionHeading en="Ingredients" zh="食材" />
        <button
          type="button"
          lang="zh"
          aria-pressed={showOriginal}
          onClick={() => setShowOriginal((value) => !value)}
          className={`rounded-field border px-3.5 py-1.5 text-sm font-medium transition ${
            showOriginal
              ? 'border-cyan/70 text-cyan glow-cyan glow-text-cyan'
              : 'border-line-bright text-ink-dim hover:border-cyan/50 hover:text-cyan'
          }`}
        >
          原文
        </button>
      </div>
      <ul className="mt-4 divide-y divide-line">
        {ingredients.map((ingredient, index) => {
          // In EN mode, show English units when the source stated an
          // unambiguous value+unit ("两大勺" → "2 tbsp"); fall back to the
          // verbatim raw_text otherwise ("适量"). This is a faithful
          // translation of a stated amount, never a derived number — the 原文
          // toggle still shows the raw capture (Hard Rule 7 intact).
          const enAmount = ingredient.quantity
            ? englishQuantity(ingredient.quantity)
            : null;
          return (
            <li
              key={index}
              className="flex items-baseline justify-between gap-4 py-3"
            >
              {showOriginal ? (
                // Original names, with the source's raw_text captured verbatim.
                <>
                  <span lang="zh" className="text-base text-ink">
                    {ingredient.name.original ?? ingredient.name.en}
                  </span>
                  <span lang="zh" className="text-right text-base text-ink-dim">
                    {ingredient.raw_text}
                  </span>
                </>
              ) : (
                <>
                  <span className="flex min-w-0 items-baseline gap-2.5">
                    <span className="text-base text-ink">
                      {ingredient.name.en ?? ingredient.name.original}
                    </span>
                    {ingredient.prep_state != null && (
                      <span className="font-display text-[11px] tracking-[0.14em] text-ink-faint uppercase">
                        {ingredient.prep_state}
                      </span>
                    )}
                  </span>
                  {ingredient.quantity != null &&
                    (enAmount != null ? (
                      <span className="shrink-0 text-right text-base text-warm">
                        {enAmount}
                      </span>
                    ) : (
                      <span
                        lang="zh"
                        className="shrink-0 text-right text-base text-warm"
                      >
                        {ingredient.quantity.raw_text}
                      </span>
                    ))}
                </>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function StepsSection({ steps }: { steps: StepDoc[] }) {
  return (
    <section aria-label="Steps" className="mt-10">
      <SectionHeading en="Steps" zh="做法" />
      <ol className="mt-4 space-y-4">
        {steps.map((step) => (
          <li
            key={step.step_number}
            className="rounded-card border border-line bg-panel p-4 sm:p-5"
          >
            <div className="flex items-start gap-4">
              <span className="grid size-9 shrink-0 place-items-center rounded-full border border-gold/60 bg-gold/10 font-display text-base font-bold text-gold glow-gold glow-text-gold">
                {step.step_number}
              </span>
              <div className="min-w-0 flex-1">
                {/* countertop-legible: bigger body type than the rest of the page */}
                <p className="text-[15px] leading-relaxed text-ink sm:text-base">
                  {step.instruction}
                </p>
                {step.duration != null && (
                  <p className="mt-2 font-display text-[11px] font-semibold tracking-[0.2em] text-ink-faint uppercase">
                    Duration: {step.duration}
                  </p>
                )}
                {step.visual_cues != null && (
                  <div className="mt-3 rounded-r-field border-l-2 border-cyan/60 bg-cyan/5 py-2 pr-3 pl-3.5 text-sm text-ink-dim">
                    <span className="block font-display text-[10.5px] font-bold tracking-[0.24em] text-cyan uppercase glow-text-cyan">
                      Visual cue
                    </span>
                    <span className="mt-0.5 block">{step.visual_cues}</span>
                  </div>
                )}
                {step.technique_notes != null && (
                  <div className="mt-3 rounded-r-field border-l-2 border-gold/60 bg-gold/5 py-2 pr-3 pl-3.5 text-sm text-ink-dim">
                    <span className="block font-display text-[10.5px] font-bold tracking-[0.24em] text-gold uppercase glow-text-gold">
                      Technique
                    </span>
                    <span className="mt-0.5 block">{step.technique_notes}</span>
                  </div>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function SourceSection({
  detail,
  doc,
}: {
  detail: RecipeDetail;
  doc: RecipeDoc;
}) {
  return (
    <section
      aria-label="Source"
      className="mt-10 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-card border border-line bg-panel-deep px-4 py-3.5 text-sm"
    >
      <PlatformBadge platform={detail.platform} />
      {doc.source?.creator != null && (
        <span className="text-ink-dim">
          by <span className="text-ink">{doc.source.creator}</span>
        </span>
      )}
      <a
        href={detail.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="font-display text-xs font-semibold tracking-[0.16em] text-cyan uppercase underline decoration-cyan/40 underline-offset-4 transition hover:glow-text-cyan"
      >
        View original
      </a>
      <span className="min-w-0 flex-1 truncate text-right font-mono text-xs text-ink-faint">
        {detail.source_url}
      </span>
    </section>
  );
}

/**
 * Sibling dishes extracted from the same video: same platform + canonical_id,
 * different dish_index. The list endpoint has no canonical_id filter, so this
 * filters client-side over the platform slice (fine at MVP library sizes).
 */
function RelatedDishes({ detail }: { detail: RecipeDetail }) {
  const list = useQuery(
    listRecipesApiRecipesGetOptions({
      query: { platform: detail.platform, limit: 200 },
    }),
  );

  const siblings = (list.data?.items ?? []).filter(
    (item) =>
      item.canonical_id === detail.canonical_id && item.id !== detail.id,
  );

  if (siblings.length === 0) return null;

  return (
    <section aria-label="Related dishes" className="mt-10">
      <SectionHeading en="Related dishes" zh="同一条视频" />
      <p className="mt-1 text-xs text-ink-faint">
        Extracted from the same video
      </p>
      <ul className="mt-3 flex flex-wrap gap-2.5">
        {siblings.map((sibling) => (
          <li key={sibling.id}>
            {/* ticket-stub link — dashed gold rim, B's .nn-sib language */}
            <Link
              to="/recipes/$id"
              params={{ id: sibling.id }}
              className="inline-block rounded-chip border border-dashed border-gold/45 bg-panel px-3.5 py-2 text-sm text-ink transition hover:border-gold/80 hover:text-gold hover:glow-gold"
            >
              {sibling.title_en ?? sibling.title_original ?? 'Untitled dish'}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RawJsonDrawer({ detail }: { detail: RecipeDetail }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-10">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="rounded-field border border-line-bright px-3.5 py-1.5 font-display text-xs font-semibold tracking-[0.16em] text-ink-dim uppercase transition hover:border-cyan/55 hover:text-cyan"
      >
        {open ? 'Hide raw JSON' : 'Show raw JSON'}
      </button>
      {open && (
        <section
          aria-label="Raw extraction JSON"
          className="mt-3 overflow-x-auto rounded-card border border-line bg-panel-deep p-4"
        >
          <pre className="font-mono text-xs leading-relaxed text-ink-dim">
            {JSON.stringify(
              {
                document: detail.document,
                extraction_meta: detail.extraction_meta,
              },
              null,
              2,
            )}
          </pre>
        </section>
      )}
    </div>
  );
}

const fieldClass =
  'mt-1.5 w-full rounded-field border border-line-bright bg-panel-deep px-3.5 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-cyan/70 focus:glow-cyan focus:outline-none';
const saveButtonClass =
  'rounded-field border border-line-bright px-3.5 py-2 font-display text-xs font-semibold tracking-[0.16em] text-ink-dim uppercase transition hover:border-cyan/55 hover:text-cyan disabled:opacity-50';
const metaLabelClass =
  'block font-display text-[11px] font-semibold tracking-[0.2em] text-ink-dim uppercase';

/**
 * The user-editable fields (PATCH whitelist): free-text tags + notes, plus the
 * two derived 0–3 estimates. Correcting a rating flags the whole `estimated`
 * object `source:"user"` server-side (it drops the "estimated" affordance and
 * takes precedence over any future re-derivation).
 */
function MetaEditor({ detail }: { detail: RecipeDetail }) {
  const queryClient = useQueryClient();
  const [tagsDraft, setTagsDraft] = useState(detail.tags.join(', '));
  const [notesDraft, setNotesDraft] = useState(detail.user_notes ?? '');
  const [spiceDraft, setSpiceDraft] = useState<number | null>(
    detail.estimated_spiciness_level ?? null,
  );
  const [difficultyDraft, setDifficultyDraft] = useState<number | null>(
    detail.estimated_difficulty_level ?? null,
  );

  const patch = useMutation({
    ...patchRecipeApiRecipesRecipeIdPatchMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getRecipeApiRecipesRecipeIdGetQueryKey({
          path: { recipe_id: detail.id },
        }),
      });
      void queryClient.invalidateQueries({
        queryKey: listRecipesApiRecipesGetQueryKey(),
      });
    },
  });

  function saveTags(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const tags = tagsDraft
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean);
    patch.mutate({ path: { recipe_id: detail.id }, body: { tags } });
  }

  function saveNotes(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = notesDraft.trim();
    patch.mutate({
      path: { recipe_id: detail.id },
      body: { user_notes: trimmed ? notesDraft : null },
    });
  }

  function saveRatings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Both are sent so the intent is explicit; the server flags the whole
    // `estimated` object source:"user" (one provenance for the pair).
    patch.mutate({
      path: { recipe_id: detail.id },
      body: {
        estimated_spiciness_level: spiceDraft,
        estimated_difficulty_level: difficultyDraft,
      },
    });
  }

  return (
    <section
      aria-label="Your notes, tags, and ratings"
      className="mt-10 space-y-4"
    >
      <SectionHeading en="Your notes & tags" zh="笔记" />
      <form onSubmit={saveTags} className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <label htmlFor="recipe-tags" className={metaLabelClass}>
            Tags
          </label>
          <input
            id="recipe-tags"
            type="text"
            value={tagsDraft}
            onChange={(event) => setTagsDraft(event.target.value)}
            placeholder="comma, separated, tags"
            className={fieldClass}
          />
        </div>
        <button
          type="submit"
          disabled={patch.isPending}
          className={saveButtonClass}
        >
          Save tags
        </button>
      </form>

      <form onSubmit={saveNotes}>
        <label htmlFor="recipe-notes" className={metaLabelClass}>
          Notes
        </label>
        <textarea
          id="recipe-notes"
          rows={3}
          value={notesDraft}
          onChange={(event) => setNotesDraft(event.target.value)}
          placeholder="Your cooking notes"
          className={fieldClass}
        />
        <button
          type="submit"
          disabled={patch.isPending}
          className={`mt-2 ${saveButtonClass}`}
        >
          Save notes
        </button>
      </form>

      <form onSubmit={saveRatings} className="space-y-3">
        <RatingSelect
          id="recipe-spiciness"
          label="Spiciness"
          words={SPICINESS_WORDS}
          value={spiceDraft}
          onChange={setSpiceDraft}
          preview={<SpicinessScale level={spiceDraft} decorative />}
        />
        <RatingSelect
          id="recipe-difficulty"
          label="Difficulty"
          words={DIFFICULTY_WORDS}
          value={difficultyDraft}
          onChange={setDifficultyDraft}
          preview={<DifficultyScale level={difficultyDraft} decorative />}
        />
        <p className="text-xs text-ink-faint">
          {detail.estimated_source === 'user'
            ? 'Your ratings — you’ve overridden the model’s estimate.'
            : 'The model’s estimates — adjust either to save your own.'}
        </p>
        <button
          type="submit"
          disabled={patch.isPending}
          className={saveButtonClass}
        >
          Save ratings
        </button>
      </form>

      {patch.isError && (
        <p role="alert" className="text-sm text-chili-bright">
          {apiErrorMessage(patch.error)}
        </p>
      )}
      {patch.isSuccess && !patch.isPending && (
        <p className="text-sm text-gold">Saved.</p>
      )}
    </section>
  );
}

/**
 * One 0–3 estimate as a labelled `<select>` (— no estimate ‖ 0..3) with a live,
 * decorative scale preview. The preview scale is passed `decorative` so it
 * carries no accessible label — the `<select>`'s label is the single a11y
 * control here, and the read-only hero scale keeps sole ownership of the
 * "Spiciness: …" / "Difficulty: …" labels.
 */
function RatingSelect({
  id,
  label,
  words,
  value,
  onChange,
  preview,
}: {
  id: string;
  label: string;
  words: readonly string[];
  value: number | null;
  onChange: (value: number | null) => void;
  preview: ReactNode;
}) {
  return (
    <div className="flex items-end gap-3">
      <div className="min-w-0 flex-1">
        <label htmlFor={id} className={metaLabelClass}>
          {label}
        </label>
        <select
          id={id}
          value={value === null ? '' : String(value)}
          onChange={(event) =>
            onChange(
              event.target.value === '' ? null : Number(event.target.value),
            )
          }
          className={fieldClass}
        >
          <option value="">— no estimate</option>
          {words.map((word, index) => (
            <option key={word} value={index}>{`${index} · ${word}`}</option>
          ))}
        </select>
      </div>
      <span aria-hidden="true" className="pb-2">
        {preview}
      </span>
    </div>
  );
}

function DeleteControl({ recipeId }: { recipeId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  const deleteRecipe = useMutation({
    ...deleteRecipeApiRecipesRecipeIdDeleteMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: listRecipesApiRecipesGetQueryKey(),
      });
      void navigate({ to: '/' });
    },
  });

  return (
    <section
      aria-label="Delete recipe"
      className="mt-12 border-t border-chili/25 pt-6"
    >
      {!confirming ? (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="rounded-field border border-chili/50 px-3.5 py-1.5 font-display text-xs font-semibold tracking-[0.16em] text-chili-bright uppercase transition hover:border-chili hover:glow-chili"
        >
          Delete recipe
        </button>
      ) : (
        <div className="rounded-card border border-chili/40 bg-chili/5 p-4 text-sm glow-chili">
          <p className="text-ink-dim">
            This permanently deletes the recipe — a hard delete with no undo.
            Re-pasting the source link later will re-run (and re-pay for)
            extraction.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              disabled={deleteRecipe.isPending}
              onClick={() =>
                deleteRecipe.mutate({ path: { recipe_id: recipeId } })
              }
              className="rounded-field border border-chili bg-chili/15 px-3.5 py-1.5 font-display text-xs font-semibold tracking-[0.14em] text-chili-bright uppercase glow-chili transition hover:bg-chili/25 disabled:opacity-50"
            >
              Delete permanently
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded-field border border-line-bright px-3.5 py-1.5 font-display text-xs font-semibold tracking-[0.14em] text-ink-dim uppercase transition hover:border-cyan/55 hover:text-cyan"
            >
              Cancel
            </button>
          </div>
          {deleteRecipe.isError && (
            <p role="alert" className="mt-2 text-xs text-chili-bright">
              {apiErrorMessage(deleteRecipe.error)}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
