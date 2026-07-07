import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { RecipeDetail } from '../client/types.gen';
import { recipeDetail } from '../test/fixtures';
import { genState, resetGenState } from '../test/gen-mock';
import { renderApp } from '../test/render-app';

// Mock the generated query-options module — component tests never real-fetch.
vi.mock('../client/@tanstack/react-query.gen', async () =>
  (await import('../test/gen-mock')).genMockModule(),
);

describe('RecipeDetailPage', () => {
  beforeEach(() => {
    resetGenState();
  });

  it('toggles ingredients between EN names and 原文 with verbatim raw_text', async () => {
    genState.recipesById['r1'] = recipeDetail();

    renderApp('/recipes/r1');

    // Default (EN mode): a stated value+unit renders in English units
    // ("500克" → "500 g"); an approx quantity with no unit falls back to the
    // verbatim raw_text ("适量").
    expect(await screen.findByText('pork belly')).toBeInTheDocument();
    expect(screen.getByText('500 g')).toBeInTheDocument();
    expect(screen.queryByText('500克')).not.toBeInTheDocument();
    expect(screen.getByText('适量')).toBeInTheDocument();
    expect(screen.queryByText('五花肉500克')).not.toBeInTheDocument();

    const toggle = screen.getByRole('button', { name: '原文' });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'true');

    // Toggled (原文): original names + the full raw_text captured verbatim,
    // and the English unit is gone (the raw 克 is back).
    expect(screen.getByText('五花肉500克')).toBeInTheDocument();
    expect(screen.getByText('盐适量')).toBeInTheDocument();
    expect(screen.queryByText('500 g')).not.toBeInTheDocument();
    expect(screen.queryByText('pork belly')).not.toBeInTheDocument();
  });

  it('renders steps with visual cues and technique notes distinctly', async () => {
    genState.recipesById['r1'] = recipeDetail();

    renderApp('/recipes/r1');

    expect(
      await screen.findByText(/Skim until the surface foam is gone/),
    ).toBeInTheDocument();
    expect(screen.getByText('Visual cue')).toBeInTheDocument();
    expect(screen.getByText('Technique')).toBeInTheDocument();
    expect(screen.getByText(/Duration: 1小时/)).toBeInTheDocument();
  });

  it('renders the illustration hero when the recipe has an image', async () => {
    genState.recipesById['r1'] = recipeDetail({ has_image: true });

    renderApp('/recipes/r1');

    // In jsdom the blob fetch never succeeds, so CoverImage shows its
    // platform-tinted fallback — role img + the alt name either way.
    expect(
      await screen.findByRole('img', { name: /cover photo/ }),
    ).toBeInTheDocument();
    // One heading carries both languages; EN-title selectors still match.
    expect(
      screen.getByRole('heading', { name: /Red-braised pork belly/ }),
    ).toBeInTheDocument();
  });

  it('enqueues a cover job from the Regenerate illustration control', async () => {
    genState.recipesById['r1'] = recipeDetail({ id: 'r1', has_image: true });
    genState.regenerateIllustration.mockResolvedValue({});

    renderApp('/recipes/r1');

    const button = await screen.findByRole('button', {
      name: 'Regenerate illustration',
    });
    fireEvent.click(button);
    await waitFor(() =>
      expect(genState.regenerateIllustration).toHaveBeenCalledWith(
        expect.objectContaining({ path: { recipe_id: 'r1' } }),
      ),
    );
    expect(await screen.findByText(/Queued/)).toBeInTheDocument();
  });

  it('labels the cover control Generate when the recipe has no image yet', async () => {
    genState.recipesById['r1'] = recipeDetail({ id: 'r1', has_image: false });

    renderApp('/recipes/r1');

    expect(
      await screen.findByRole('button', { name: 'Generate illustration' }),
    ).toBeInTheDocument();
  });

  it('shows no illustration hero when has_image is false', async () => {
    genState.recipesById['r1'] = recipeDetail({ has_image: false });

    renderApp('/recipes/r1');

    await screen.findByRole('heading', { name: /Red-braised pork belly/ });
    expect(
      screen.queryByRole('img', { name: /cover photo/ }),
    ).not.toBeInTheDocument();
  });

  it('shows the estimated spiciness + difficulty scales in the hero meta', async () => {
    genState.recipesById['r1'] = recipeDetail();

    renderApp('/recipes/r1');

    // Recipe-level ESTIMATES from detail: spiciness=2 → medium, difficulty=1
    // → easy; two distinct, flagged-estimated indicators.
    expect(
      await screen.findByLabelText('Spiciness: medium (estimated)'),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText('Difficulty: easy (estimated)'),
    ).toBeInTheDocument();
  });

  it('omits the estimate scales when the fields are null (never invent)', async () => {
    genState.recipesById['r1'] = recipeDetail({
      estimated_spiciness_level: null,
      estimated_difficulty_level: null,
    });

    renderApp('/recipes/r1');

    await screen.findByRole('heading', { name: /Red-braised pork belly/ });
    expect(screen.queryByLabelText(/Spiciness:/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Difficulty:/)).not.toBeInTheDocument();
  });

  it('shows the sleeping pup while the recipe loads', async () => {
    // A never-settling thenable keeps the detail query pending forever, so
    // the loading state is stable to assert against.
    genState.recipesById['r1'] = new Promise<never>(
      () => undefined,
    ) as unknown as RecipeDetail;

    renderApp('/recipes/r1');

    expect(await screen.findByText(/plating up/)).toBeInTheDocument();
    expect(screen.getByText('上菜中')).toBeInTheDocument();
    expect(
      document.querySelector('svg[data-variant="sleeping"]'),
    ).not.toBeNull();
  });

  it('opens the raw-JSON drawer with document + extraction_meta', async () => {
    genState.recipesById['r1'] = recipeDetail();

    renderApp('/recipes/r1');

    fireEvent.click(
      await screen.findByRole('button', { name: 'Show raw JSON' }),
    );
    const region = screen.getByRole('region', {
      name: 'Raw extraction JSON',
    });
    expect(region).toHaveTextContent('"dish_name"');
    expect(region).toHaveTextContent('"extraction_meta"');
  });

  it('PATCHes edited notes and tags through the whitelist endpoint', async () => {
    genState.recipesById['r1'] = recipeDetail();
    genState.patch.mockResolvedValue(recipeDetail());

    renderApp('/recipes/r1');

    fireEvent.change(await screen.findByLabelText('Notes'), {
      target: { value: 'less sugar next time' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save notes' }));
    await waitFor(() =>
      expect(genState.patch).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { recipe_id: 'r1' },
          body: { user_notes: 'less sugar next time' },
        }),
      ),
    );

    fireEvent.change(screen.getByLabelText('Tags'), {
      target: { value: 'pork, braise' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save tags' }));
    await waitFor(() =>
      expect(genState.patch).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { recipe_id: 'r1' },
          body: { tags: ['pork', 'braise'] },
        }),
      ),
    );
  });

  it('PATCHes corrected estimates, sending both levels as an owner override', async () => {
    genState.recipesById['r1'] = recipeDetail();
    genState.patch.mockResolvedValue(
      recipeDetail({ estimated_source: 'user' }),
    );

    renderApp('/recipes/r1');

    // Fixture starts spiciness=2 (medium) / difficulty=1 (easy), source derived.
    // Correcting only spiciness still sends both — the pair shares one provenance.
    fireEvent.change(await screen.findByLabelText('Spiciness'), {
      target: { value: '3' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save ratings' }));

    await waitFor(() =>
      expect(genState.patch).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { recipe_id: 'r1' },
          body: {
            estimated_spiciness_level: 3,
            estimated_difficulty_level: 1,
          },
        }),
      ),
    );
  });

  it('clears an estimate by sending an explicit null level', async () => {
    genState.recipesById['r1'] = recipeDetail();
    genState.patch.mockResolvedValue(recipeDetail());

    renderApp('/recipes/r1');

    fireEvent.change(await screen.findByLabelText('Difficulty'), {
      target: { value: '' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save ratings' }));

    await waitFor(() =>
      expect(genState.patch).toHaveBeenCalledWith(
        expect.objectContaining({
          body: {
            estimated_spiciness_level: 2,
            estimated_difficulty_level: null,
          },
        }),
      ),
    );
  });

  it('drops the "(estimated)" flag on the hero once the owner has overridden', async () => {
    genState.recipesById['r1'] = recipeDetail({ estimated_source: 'user' });

    renderApp('/recipes/r1');

    // source "user" ⇒ the hero scales read as the owner's values, not estimates.
    expect(
      await screen.findByLabelText('Spiciness: medium'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Difficulty: easy')).toBeInTheDocument();
    expect(screen.queryByLabelText(/\(estimated\)/)).not.toBeInTheDocument();
  });

  it('hard-deletes only after the explicit confirm step', async () => {
    genState.recipesById['r1'] = recipeDetail();
    genState.deleteRecipe.mockResolvedValue(undefined);

    renderApp('/recipes/r1');

    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete recipe' }),
    );
    expect(genState.deleteRecipe).not.toHaveBeenCalled();
    expect(screen.getByText(/permanently deletes the recipe/)).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: 'Delete permanently' }));
    await waitFor(() =>
      expect(genState.deleteRecipe).toHaveBeenCalledWith(
        expect.objectContaining({ path: { recipe_id: 'r1' } }),
      ),
    );
  });

  it('does not render a clickable "View original" for a non-http(s) source_url (XSS guard)', async () => {
    // source_url is persisted third-party/upload-provenance data; a javascript:
    // URL as an href would execute on click (V2-D). The guard drops the link.
    genState.recipesById['r1'] = recipeDetail({
      source_url: 'javascript:alert(document.cookie)',
    });

    renderApp('/recipes/r1');

    // The page renders (the URL still shows as escaped text) …
    expect(
      await screen.findByText('javascript:alert(document.cookie)'),
    ).toBeInTheDocument();
    // … but there is no clickable link, and nothing carries a javascript: href.
    expect(
      screen.queryByRole('link', { name: /view original/i }),
    ).not.toBeInTheDocument();
    expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
  });

  it('renders a "View original" link for an http(s) source_url', async () => {
    genState.recipesById['r1'] = recipeDetail({
      source_url: 'https://www.bilibili.com/video/BV1xx',
    });

    renderApp('/recipes/r1');

    const link = await screen.findByRole('link', { name: /view original/i });
    expect(link).toHaveAttribute(
      'href',
      'https://www.bilibili.com/video/BV1xx',
    );
  });
});
