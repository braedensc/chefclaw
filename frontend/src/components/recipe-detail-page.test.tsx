import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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

    // Default: EN names, quantities straight from quantity.raw_text.
    expect(await screen.findByText('pork belly')).toBeInTheDocument();
    expect(screen.getByText('500克')).toBeInTheDocument();
    expect(screen.getByText('适量')).toBeInTheDocument();
    expect(screen.queryByText('五花肉500克')).not.toBeInTheDocument();

    const toggle = screen.getByRole('button', { name: '原文' });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'true');

    // Toggled: original names + the full raw_text captured verbatim.
    expect(screen.getByText('五花肉500克')).toBeInTheDocument();
    expect(screen.getByText('盐适量')).toBeInTheDocument();
    expect(screen.queryByText('pork belly')).not.toBeInTheDocument();
  });

  it('renders steps with visual cues and technique notes distinctly', async () => {
    genState.recipesById['r1'] = recipeDetail();

    renderApp('/recipes/r1');

    expect(
      await screen.findByText(/Skim until the surface foam is gone/),
    ).toBeInTheDocument();
    expect(screen.getByText('Visual cue:')).toBeInTheDocument();
    expect(screen.getByText('Technique:')).toBeInTheDocument();
    expect(screen.getByText(/Duration: 1小时/)).toBeInTheDocument();
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
});
