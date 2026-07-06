import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from '@tanstack/react-router';
import { useState } from 'react';
import type { FormEvent } from 'react';

import { ApiError } from '../api-error';
import {
  deleteRecipeApiRecipesRecipeIdDeleteMutation,
  getRecipeApiRecipesRecipeIdGetOptions,
  getRecipeApiRecipesRecipeIdGetQueryKey,
  listRecipesApiRecipesGetOptions,
  listRecipesApiRecipesGetQueryKey,
  patchRecipeApiRecipesRecipeIdPatchMutation,
} from '../client/@tanstack/react-query.gen';
import type { RecipeDetail } from '../client/types.gen';
import { apiErrorMessage } from '../lib/error-message';
import { asRecipeDoc } from '../lib/recipe-document';
import type { IngredientDoc, RecipeDoc, StepDoc } from '../lib/recipe-document';
import { PlatformBadge } from './platform-badge';

/**
 * Screen 2 (plan §7): full recipe — ingredients with the 原文 toggle, steps
 * with visual cues + technique notes, tips, source attribution, related
 * dishes from the same video, the raw-JSON drawer, tags/notes editing, and
 * hard delete.
 */
export function RecipeDetailPage() {
  const { id } = useParams({ from: '/recipes/$id' });
  const detailQuery = useQuery(
    getRecipeApiRecipesRecipeIdGetOptions({ path: { recipe_id: id } }),
  );

  if (detailQuery.isPending) {
    return <p className="text-sm text-neutral-400">Loading recipe…</p>;
  }

  if (detailQuery.isError) {
    const status =
      detailQuery.error instanceof ApiError ? detailQuery.error.status : null;
    return (
      <div role="alert" className="text-sm">
        <p className="text-red-300">
          {status === 404
            ? 'Recipe not found — it may have been deleted.'
            : apiErrorMessage(detailQuery.error)}
        </p>
        <Link
          to="/"
          className="mt-3 inline-block text-neutral-400 underline hover:text-neutral-200"
        >
          Back to library
        </Link>
      </div>
    );
  }

  const detail = detailQuery.data;
  const doc = asRecipeDoc(detail.document);

  return (
    <article>
      <Link to="/" className="text-sm text-neutral-400 hover:text-neutral-200">
        ← Back to library
      </Link>

      <header className="mt-4">
        <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-400">
          <PlatformBadge platform={detail.platform} />
          {doc.difficulty != null && (
            <span className="rounded-full bg-neutral-800 px-2 py-0.5">
              {doc.difficulty}
            </span>
          )}
          {doc.total_time_minutes != null && (
            <span className="rounded-full bg-neutral-800 px-2 py-0.5">
              {doc.total_time_minutes} min
            </span>
          )}
          {doc.servings != null && (
            <span className="rounded-full bg-neutral-800 px-2 py-0.5">
              serves {doc.servings}
            </span>
          )}
          {doc.cuisine_type != null && (
            <span className="rounded-full bg-neutral-800 px-2 py-0.5">
              {doc.cuisine_type}
            </span>
          )}
        </div>
        <h1 className="mt-3 text-2xl font-semibold text-neutral-100">
          {detail.title_en ?? detail.title_original ?? 'Untitled dish'}
        </h1>
        {detail.title_en != null && detail.title_original != null && (
          <p lang="zh" className="mt-1 text-lg text-neutral-400">
            {detail.title_original}
          </p>
        )}
      </header>

      <IngredientsSection ingredients={doc.ingredients} />

      {doc.equipment.length > 0 && (
        <p className="mt-4 text-sm text-neutral-400">
          <span className="font-medium text-neutral-300">Equipment:</span>{' '}
          {doc.equipment.join(' · ')}
        </p>
      )}

      <StepsSection steps={doc.steps} />

      {doc.tips.length > 0 && (
        <section aria-label="Tips" className="mt-8">
          <h2 className="text-lg font-semibold text-neutral-100">Tips</h2>
          <ul className="mt-2 space-y-1 text-sm text-neutral-300">
            {doc.tips.map((tip) => (
              <li key={tip} className="border-l-2 border-emerald-500/50 pl-3">
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

function IngredientsSection({ ingredients }: { ingredients: IngredientDoc[] }) {
  const [showOriginal, setShowOriginal] = useState(false);

  return (
    <section aria-label="Ingredients" className="mt-8">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold text-neutral-100">Ingredients</h2>
        <button
          type="button"
          aria-pressed={showOriginal}
          onClick={() => setShowOriginal((value) => !value)}
          className={`rounded-md border px-3 py-1 text-sm transition ${
            showOriginal
              ? 'border-emerald-500 bg-emerald-500/15 text-emerald-300'
              : 'border-neutral-700 text-neutral-300 hover:border-neutral-500'
          }`}
        >
          原文
        </button>
      </div>
      <ul className="mt-3 divide-y divide-neutral-800/70 text-sm">
        {ingredients.map((ingredient, index) => (
          <li
            key={index}
            className="flex items-baseline justify-between gap-3 py-2"
          >
            {showOriginal ? (
              // Original names, with the source's raw_text captured verbatim.
              <>
                <span lang="zh" className="text-neutral-100">
                  {ingredient.name.original ?? ingredient.name.en}
                </span>
                <span lang="zh" className="text-right text-neutral-400">
                  {ingredient.raw_text}
                </span>
              </>
            ) : (
              // EN names; quantities always shown from raw_text (Hard Rule 7
              // — never a normalized/derived number).
              <>
                <span className="flex items-baseline gap-2">
                  <span className="text-neutral-100">
                    {ingredient.name.en ?? ingredient.name.original}
                  </span>
                  {ingredient.prep_state != null && (
                    <span className="text-xs text-neutral-500">
                      {ingredient.prep_state}
                    </span>
                  )}
                </span>
                {ingredient.quantity?.raw_text != null && (
                  <span lang="zh" className="text-right text-neutral-400">
                    {ingredient.quantity.raw_text}
                  </span>
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function StepsSection({ steps }: { steps: StepDoc[] }) {
  return (
    <section aria-label="Steps" className="mt-8">
      <h2 className="text-lg font-semibold text-neutral-100">Steps</h2>
      <ol className="mt-3 space-y-3">
        {steps.map((step) => (
          <li
            key={step.step_number}
            className="rounded-lg border border-neutral-800 bg-neutral-900/60 p-4"
          >
            <div className="flex items-baseline gap-3">
              <span className="shrink-0 text-sm font-semibold text-emerald-400">
                {step.step_number}
              </span>
              <p className="flex-1 text-sm text-neutral-200">
                {step.instruction}
              </p>
            </div>
            {step.duration != null && (
              <p className="mt-2 pl-6 text-xs text-neutral-400">
                Duration: {step.duration}
              </p>
            )}
            {step.visual_cues != null && (
              <p className="mt-2 ml-6 border-l-2 border-sky-500/60 pl-3 text-xs text-sky-200/90">
                <span className="font-medium">Visual cue:</span>{' '}
                {step.visual_cues}
              </p>
            )}
            {step.technique_notes != null && (
              <p className="mt-2 ml-6 border-l-2 border-amber-500/60 pl-3 text-xs text-amber-200/90">
                <span className="font-medium">Technique:</span>{' '}
                {step.technique_notes}
              </p>
            )}
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
      className="mt-8 flex flex-wrap items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-900/60 p-4 text-sm"
    >
      <PlatformBadge platform={detail.platform} />
      {doc.source?.creator != null && (
        <span className="text-neutral-300">by {doc.source.creator}</span>
      )}
      <a
        href={detail.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-emerald-400 underline hover:text-emerald-300"
      >
        View original
      </a>
      <span className="min-w-0 truncate text-xs text-neutral-500">
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
    <section aria-label="Related dishes" className="mt-8">
      <h2 className="text-lg font-semibold text-neutral-100">Related dishes</h2>
      <p className="mt-1 text-xs text-neutral-500">
        Extracted from the same video
      </p>
      <ul className="mt-2 space-y-1 text-sm">
        {siblings.map((sibling) => (
          <li key={sibling.id}>
            <Link
              to="/recipes/$id"
              params={{ id: sibling.id }}
              className="text-emerald-400 underline hover:text-emerald-300"
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
    <div className="mt-8">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="rounded-md border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:border-neutral-500 hover:text-neutral-100"
      >
        {open ? 'Hide raw JSON' : 'Show raw JSON'}
      </button>
      {open && (
        <section
          aria-label="Raw extraction JSON"
          className="mt-3 overflow-x-auto rounded-lg border border-neutral-800 bg-neutral-950 p-4"
        >
          <pre className="text-xs leading-relaxed text-neutral-300">
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

/** Tags + notes are the ONLY user-editable fields (PATCH whitelist). */
function MetaEditor({ detail }: { detail: RecipeDetail }) {
  const queryClient = useQueryClient();
  const [tagsDraft, setTagsDraft] = useState(detail.tags.join(', '));
  const [notesDraft, setNotesDraft] = useState(detail.user_notes ?? '');

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

  return (
    <section aria-label="Your notes and tags" className="mt-8 space-y-4">
      <form onSubmit={saveTags} className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <label
            htmlFor="recipe-tags"
            className="block text-sm font-medium text-neutral-300"
          >
            Tags
          </label>
          <input
            id="recipe-tags"
            type="text"
            value={tagsDraft}
            onChange={(event) => setTagsDraft(event.target.value)}
            placeholder="comma, separated, tags"
            className="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-sm text-neutral-100 placeholder:text-neutral-500 focus:border-emerald-500 focus:outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={patch.isPending}
          className="rounded-md border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:border-neutral-500 hover:text-neutral-100 disabled:opacity-50"
        >
          Save tags
        </button>
      </form>

      <form onSubmit={saveNotes}>
        <label
          htmlFor="recipe-notes"
          className="block text-sm font-medium text-neutral-300"
        >
          Notes
        </label>
        <textarea
          id="recipe-notes"
          rows={3}
          value={notesDraft}
          onChange={(event) => setNotesDraft(event.target.value)}
          placeholder="Your cooking notes"
          className="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 placeholder:text-neutral-500 focus:border-emerald-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={patch.isPending}
          className="mt-2 rounded-md border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:border-neutral-500 hover:text-neutral-100 disabled:opacity-50"
        >
          Save notes
        </button>
      </form>

      {patch.isError && (
        <p role="alert" className="text-sm text-red-400">
          {apiErrorMessage(patch.error)}
        </p>
      )}
      {patch.isSuccess && !patch.isPending && (
        <p className="text-sm text-emerald-400">Saved.</p>
      )}
    </section>
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
      className="mt-10 border-t border-neutral-800 pt-6"
    >
      {!confirming ? (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="rounded-md border border-red-900 px-3 py-1.5 text-sm text-red-300 hover:border-red-700 hover:text-red-200"
        >
          Delete recipe
        </button>
      ) : (
        <div className="rounded-md border border-red-900 bg-red-950/40 p-4 text-sm">
          <p className="text-red-200">
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
              className="rounded-md bg-red-800 px-3 py-1.5 text-xs font-medium text-red-100 hover:bg-red-700 disabled:opacity-50"
            >
              Delete permanently
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:border-neutral-500"
            >
              Cancel
            </button>
          </div>
          {deleteRecipe.isError && (
            <p role="alert" className="mt-2 text-xs text-red-300">
              {apiErrorMessage(deleteRecipe.error)}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
