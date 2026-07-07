import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { jobOut } from '../test/fixtures';
import { genState, resetGenState } from '../test/gen-mock';
import { renderApp } from '../test/render-app';

// Mock the generated query-options module — component tests never real-fetch.
vi.mock('../client/@tanstack/react-query.gen', async () =>
  (await import('../test/gen-mock')).genMockModule(),
);

async function openDrawer() {
  renderApp('/');
  fireEvent.click(await screen.findByRole('button', { name: 'Jobs' }));
  return await screen.findByRole('complementary', { name: 'Jobs' });
}

describe('JobsDrawer', () => {
  beforeEach(() => {
    resetGenState();
  });

  it('offers Retry for retryable errors, enabled only when the url is present', async () => {
    genState.jobsList = [
      jobOut({
        id: 'j-retry',
        status: 'failed',
        error_type: 'download_failed',
        error_detail: 'source fetch timed out',
        url: 'fake://retry-me',
      }),
      jobOut({
        id: 'j-nourl',
        status: 'failed',
        error_type: 'interrupted',
        url: null,
      }),
    ];
    genState.extract.mockResolvedValue(jobOut({ id: 'j-new' }));

    const drawer = await openDrawer();

    const retryButtons = await within(drawer).findAllByRole('button', {
      name: 'Retry',
    });
    expect(retryButtons).toHaveLength(2);
    expect(retryButtons[0]).toBeEnabled();
    expect(retryButtons[1]).toBeDisabled();

    fireEvent.click(retryButtons[0]);
    await waitFor(() =>
      expect(genState.extract).toHaveBeenCalledWith(
        expect.objectContaining({ body: { url: 'fake://retry-me' } }),
      ),
    );
  });

  it('surfaces a retry failure instead of swallowing it', async () => {
    genState.jobsList = [
      jobOut({
        id: 'j-retry',
        status: 'failed',
        error_type: 'download_failed',
        url: 'fake://retry-me',
      }),
    ];
    genState.extract.mockRejectedValue(new Error('connection refused'));

    const drawer = await openDrawer();

    fireEvent.click(
      await within(drawer).findByRole('button', { name: 'Retry' }),
    );

    const alert = await within(drawer).findByRole('alert');
    expect(alert).toHaveTextContent(/Retry failed/);
  });

  it('offers re-upload guidance instead of Retry for failed upload jobs', async () => {
    genState.jobsList = [
      jobOut({
        id: 'j-upload',
        type: 'upload',
        platform: 'local',
        canonical_id: 'file-abc',
        status: 'failed',
        error_type: 'download_failed',
        error_detail: 'staged upload file is gone',
        url: 'local://file-abc',
      }),
    ];

    const drawer = await openDrawer();

    expect(
      await within(drawer).findByText(/re-upload the video file/i),
    ).toBeInTheDocument();
    // No Retry — a re-POST of local:// is a guaranteed 400 (no adapter
    // matches), and the staged file is deleted once the job is terminal.
    expect(
      within(drawer).queryByRole('button', { name: 'Retry' }),
    ).not.toBeInTheDocument();
    expect(genState.extract).not.toHaveBeenCalled();
  });

  it('retries a failed illustration job by re-enqueueing, not re-POSTing an extract', async () => {
    genState.jobsList = [
      jobOut({
        id: 'j-illus',
        type: 'illustration',
        platform: null,
        canonical_id: null,
        url: null,
        recipe_ids: ['recipe-42'],
        status: 'failed',
        error_type: 'illustration_failed',
        error_detail: '1 of 1 illustration(s) could not be generated',
      }),
    ];
    genState.regenerateIllustration.mockResolvedValue(
      jobOut({ id: 'j-illus-2', type: 'illustration' }),
    );

    const drawer = await openDrawer();

    // The row reads as a cover job, not a canonical id:
    const [row] = await within(drawer).findAllByRole('listitem');
    expect(row).toHaveTextContent('Cover illustration');

    fireEvent.click(
      await within(drawer).findByRole('button', { name: 'Retry' }),
    );
    await waitFor(() =>
      expect(genState.regenerateIllustration).toHaveBeenCalledWith(
        expect.objectContaining({ path: { recipe_id: 'recipe-42' } }),
      ),
    );
    // It must NOT re-POST the extract endpoint for an illustration job:
    expect(genState.extract).not.toHaveBeenCalled();
  });

  it('maps non-retryable typed errors onto guidance text', async () => {
    genState.jobsList = [
      jobOut({
        id: 'j-cookie',
        status: 'failed',
        platform: 'rednote',
        error_type: 'cookies_expired',
        url: null,
      }),
      jobOut({
        id: 'j-budget',
        status: 'failed',
        error_type: 'budget_exceeded',
        url: 'fake://over-budget',
      }),
      jobOut({
        id: 'j-config',
        status: 'failed',
        error_type: 'config_error',
        url: 'fake://misconfigured',
      }),
    ];

    const drawer = await openDrawer();

    expect(
      await within(drawer).findByText(/docs\/RUNBOOK\.md/),
    ).toBeInTheDocument();
    // The runbook EXISTS (Phase 4) — the pre-landing "lands with Phase 4"
    // hedge must not resurface.
    expect(
      within(drawer).queryByText(/lands with Phase 4/),
    ).not.toBeInTheDocument();
    expect(within(drawer).getByText(/Budget cap reached/)).toBeInTheDocument();
    expect(
      within(drawer).getByText(/Check server configuration/),
    ).toBeInTheDocument();
    // None of these get a Retry button — retrying cannot fix them.
    expect(
      within(drawer).queryByRole('button', { name: 'Retry' }),
    ).not.toBeInTheDocument();
  });

  it('lists active jobs before terminal ones with status and identity', async () => {
    genState.jobsList = [
      jobOut({
        id: 'j-done',
        status: 'stored',
        canonical_id: 'fake-golden-1',
        updated_at: '2026-07-06T02:00:00Z',
      }),
      jobOut({
        id: 'j-active',
        status: 'extracting',
        canonical_id: 'fake-golden-2',
        updated_at: '2026-07-06T01:00:00Z',
      }),
    ];

    const drawer = await openDrawer();

    const rows = await within(drawer).findAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('fake-golden-2');
    expect(rows[0]).toHaveTextContent('Extracting');
    expect(rows[1]).toHaveTextContent('fake-golden-1');
    expect(rows[1]).toHaveTextContent('Stored');
  });

  it('keeps the sober statusLabel vocabulary for stored jobs (golden contract)', async () => {
    genState.jobsList = [
      jobOut({
        id: 'j-stored',
        status: 'stored',
        canonical_id: 'fake-golden-1',
      }),
    ];

    const drawer = await openDrawer();

    const [row] = await within(drawer).findAllByRole('listitem');
    // The golden suite asserts the literal 'Stored' — the playful cooking
    // microcopy (lib/cooking-stages) stays on the chips, never the drawer.
    expect(row).toHaveTextContent('Stored');
    expect(row).toHaveTextContent('bilibili');
    expect(row).not.toHaveTextContent('上菜');
  });
});
