import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api-error';
import { adminConfig, meOut } from '../test/fixtures';
import { genState, resetGenState } from '../test/gen-mock';
import { renderApp } from '../test/render-app';

vi.mock('../client/@tanstack/react-query.gen', async () =>
  (await import('../test/gen-mock')).genMockModule(),
);

describe('AdminConfigPage', () => {
  beforeEach(() => resetGenState());

  it('renders runtime policy, secret status, and read-only infra', async () => {
    renderApp('/admin/config');

    // A runtime-policy control with its env default.
    const cover = (await screen.findByLabelText(
      'chefclaw_image_generator',
    )) as HTMLSelectElement;
    expect(cover.value).toBe('sprite');

    // An overridden flag shows the override badge + its env default.
    expect(screen.getAllByText('override').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/env default:/)).toBeInTheDocument();

    // Secrets are STATUS ONLY — a label, never a value.
    expect(screen.getByText('gemini_api_key')).toBeInTheDocument();
    expect(screen.getByText('not set')).toBeInTheDocument();

    // Infra is read-only.
    expect(screen.getByText('chefclaw_auth_provider')).toBeInTheDocument();
  });

  it('saves a changed flag with the right PATCH body', async () => {
    genState.patchConfig.mockResolvedValue(adminConfig());
    renderApp('/admin/config');

    const cover = await screen.findByLabelText('chefclaw_image_generator');
    fireEvent.change(cover, { target: { value: 'gemini' } });
    fireEvent.click(
      screen.getByRole('button', { name: 'Save chefclaw_image_generator' }),
    );

    await waitFor(() =>
      expect(genState.patchConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { updates: { chefclaw_image_generator: 'gemini' } },
        }),
      ),
    );
  });

  it('reset-to-env on an overridden flag sends null', async () => {
    genState.patchConfig.mockResolvedValue(adminConfig());
    renderApp('/admin/config');

    // monthly_llm_budget_usd is overridden in the fixture (25, env 10).
    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Reset monthly_llm_budget_usd to env default',
      }),
    );

    await waitFor(() =>
      expect(genState.patchConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { updates: { monthly_llm_budget_usd: null } },
        }),
      ),
    );
  });

  it('surfaces a 422 validation message inline', async () => {
    genState.patchConfig.mockRejectedValue(
      new ApiError(422, 'Unprocessable', {
        error_type: 'config_invalid',
        detail: 'gemini_media_resolution_max: must be ABOVE the base',
      }),
    );
    renderApp('/admin/config');

    const cover = await screen.findByLabelText('chefclaw_image_generator');
    fireEvent.change(cover, { target: { value: 'fake' } });
    fireEvent.click(
      screen.getByRole('button', { name: 'Save chefclaw_image_generator' }),
    );

    expect(
      await screen.findByText(/must be ABOVE the base/),
    ).toBeInTheDocument();
  });

  it('shows a no-access notice for a non-admin', async () => {
    genState.me = meOut({ is_admin: false });
    renderApp('/admin/config');
    expect(
      await screen.findByText(/don't have access to configuration/),
    ).toBeInTheDocument();
  });
});
