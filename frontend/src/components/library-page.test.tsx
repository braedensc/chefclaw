import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { jobOut, recipePage, recipeSummary } from '../test/fixtures';
import { genState, resetGenState } from '../test/gen-mock';
import { renderApp } from '../test/render-app';

// Mock the generated query-options module — component tests never real-fetch.
vi.mock('../client/@tanstack/react-query.gen', async () =>
  (await import('../test/gen-mock')).genMockModule(),
);

describe('LibraryPage', () => {
  beforeEach(() => {
    resetGenState();
  });

  it('POSTs the pasted link to the extract endpoint and shows a job chip', async () => {
    const job = jobOut({ id: 'j1', status: 'pending' });
    genState.extract.mockResolvedValue(job);
    genState.jobsById['j1'] = job;

    renderApp('/');

    fireEvent.change(await screen.findByLabelText('Video link'), {
      target: { value: 'fake://golden-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Extract' }));

    await waitFor(() =>
      expect(genState.extract).toHaveBeenCalledWith(
        expect.objectContaining({ body: { url: 'fake://golden-1' } }),
      ),
    );
    const chip = await screen.findByRole('status');
    expect(chip).toHaveTextContent('fake://golden-1');
    expect(chip).toHaveTextContent('in the queue… 排队中');
  });

  it('shows the cooking-stage copy and step for an extracting job', async () => {
    genState.extract.mockResolvedValue(jobOut({ id: 'j1', status: 'pending' }));
    genState.jobsById['j1'] = jobOut({ id: 'j1', status: 'extracting' });

    renderApp('/');
    fireEvent.change(await screen.findByLabelText('Video link'), {
      target: { value: 'fake://golden-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Extract' }));

    const chip = await screen.findByRole('status');
    await waitFor(() =>
      expect(chip).toHaveTextContent('reading the recipe… 正在读菜谱'),
    );
    expect(chip).toHaveTextContent('Step 3 / 4');
    expect(chip).toHaveTextContent('fake://golden-1');
  });

  it('morphs the chip into the recipe card when the job reaches stored', async () => {
    genState.extract.mockResolvedValue(jobOut({ id: 'j1', status: 'pending' }));
    // The chip's first poll already sees the job stored…
    genState.jobsById['j1'] = jobOut({
      id: 'j1',
      status: 'stored',
      result_recipe_ids: ['r1'],
    });

    renderApp('/');
    expect(
      await screen.findByText(/Your cookbook is hungry/),
    ).toBeInTheDocument();

    // …and the invalidation-triggered list refetch returns the new card.
    genState.recipesPage = recipePage([recipeSummary({ id: 'r1' })]);

    fireEvent.change(await screen.findByLabelText('Video link'), {
      target: { value: 'fake://golden-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Extract' }));

    expect(
      await screen.findByRole('link', { name: /Red-braised pork belly/ }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole('status')).not.toBeInTheDocument(),
    );
  });

  it('shows a typed-error chip when the job fails', async () => {
    genState.extract.mockResolvedValue(jobOut({ id: 'j1', status: 'pending' }));
    genState.jobsById['j1'] = jobOut({
      id: 'j1',
      status: 'failed',
      error_type: 'download_failed',
      error_detail: 'source fetch timed out',
    });

    renderApp('/');
    fireEvent.change(await screen.findByLabelText('Video link'), {
      target: { value: 'fake://golden-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Extract' }));

    const chip = await screen.findByRole('status');
    await waitFor(() => expect(chip).toHaveTextContent('Order dropped'));
    // The typed facts stay visible: error_type pill, detail, source label.
    expect(chip).toHaveTextContent('download_failed');
    expect(chip).toHaveTextContent('source fetch timed out');
    expect(chip).toHaveTextContent('fake://golden-1');

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('uploads a chosen file through the upload endpoint (tier-2 floor)', async () => {
    const job = jobOut({
      id: 'j2',
      platform: 'local',
      canonical_id: 'file-abc',
      url: null,
    });
    genState.upload.mockResolvedValue(job);
    genState.jobsById['j2'] = job;

    renderApp('/');

    const file = new File(['bytes'], 'dish.mp4', { type: 'video/mp4' });
    fireEvent.change(await screen.findByLabelText('Upload video file'), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(genState.upload).toHaveBeenCalledWith(
        expect.objectContaining({ body: { file } }),
      ),
    );
    expect(await screen.findByRole('status')).toHaveTextContent('file-abc');
  });

  it('renders card meta (chilis, time, ingredient count) from summary fields', async () => {
    genState.recipesPage = recipePage([recipeSummary({ id: 'r1' })]);

    renderApp('/');

    const card = await screen.findByRole('link', {
      name: /Red-braised pork belly/,
    });
    // Verbatim projections from the document: difficulty word beside the
    // lit chilis, stated minutes, stated ingredient count.
    expect(within(card).getByText('medium')).toBeInTheDocument();
    expect(within(card).getByText('75 min')).toBeInTheDocument();
    expect(within(card).getByText('2 ingredients')).toBeInTheDocument();
  });

  it('renders no meta when the summary fields are absent (never invent)', async () => {
    genState.recipesPage = recipePage([
      recipeSummary({
        id: 'r1',
        difficulty: null,
        total_time_minutes: null,
        ingredient_count: null,
      }),
    ]);

    renderApp('/');

    const card = await screen.findByRole('link', {
      name: /Red-braised pork belly/,
    });
    expect(within(card).queryByText('medium')).not.toBeInTheDocument();
    expect(within(card).queryByText(/\d+ min/)).not.toBeInTheDocument();
    expect(within(card).queryByText(/ingredient/)).not.toBeInTheDocument();
  });

  it('shows the same-video ticket only on grouped multi-dish cards', async () => {
    genState.recipesPage = recipePage([
      recipeSummary({ id: 'r1', dish_index: 0 }),
      recipeSummary({
        id: 'r2',
        dish_index: 1,
        title_en: 'Braised greens',
        title_original: '烧青菜',
      }),
      recipeSummary({
        id: 'r3',
        canonical_id: 'fake-golden-2',
        title_en: 'Cola chicken wings',
        title_original: '可乐鸡翅',
      }),
    ]);

    renderApp('/');

    await screen.findByRole('link', { name: /Cola chicken wings/ });
    // Both siblings get a ticket, the lone third card does not.
    expect(screen.getAllByText(/same video/)).toHaveLength(2);
    expect(screen.getByText('①')).toBeInTheDocument();
    expect(screen.getByText('②')).toBeInTheDocument();
  });

  it('empty state offers a Paste-a-link button that focuses the paste bar', async () => {
    renderApp('/');

    await screen.findByText(/Your cookbook is hungry/);
    // The vignette (and its button) live INSIDE the Recipe library section.
    const library = screen.getByRole('region', { name: 'Recipe library' });
    expect(
      within(library).getByText(/Your cookbook is hungry/),
    ).toBeInTheDocument();

    fireEvent.click(
      within(library).getByRole('button', { name: 'Paste a link' }),
    );
    expect(screen.getByLabelText('Video link')).toHaveFocus();
  });
});
