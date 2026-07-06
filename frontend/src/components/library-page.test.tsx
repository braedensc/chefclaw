import { fireEvent, screen, waitFor } from '@testing-library/react';
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
    expect(chip).toHaveTextContent('Queued');
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
    expect(await screen.findByText(/No recipes yet/)).toBeInTheDocument();

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
    await waitFor(() =>
      expect(chip).toHaveTextContent('Failed — download_failed'),
    );
    expect(chip).toHaveTextContent('source fetch timed out');

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
});
