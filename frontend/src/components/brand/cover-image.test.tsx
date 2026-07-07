import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { genState, resetGenState } from '../../test/gen-mock';
import { CoverImage } from './cover-image';

// Mock the generated query-options module — component tests never real-fetch.
// Auth headers and ApiError mapping live centrally in src/api.ts, so this
// component's contract is only "ask the client for the blob".
vi.mock('../../client/@tanstack/react-query.gen', async () =>
  (await import('../../test/gen-mock')).genMockModule(),
);

// jsdom implements neither createObjectURL nor revokeObjectURL — stub both so
// the blob → object-URL lifecycle is observable.
const createObjectURL = vi.fn(() => 'blob:mock-cover');
const revokeObjectURL = vi.fn();
URL.createObjectURL = createObjectURL;
URL.revokeObjectURL = revokeObjectURL;

function renderCover(props: Partial<Parameters<typeof CoverImage>[0]> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CoverImage
        recipeId="r1"
        hasImage={false}
        platform="bilibili"
        alt="红烧肉 cover"
        {...props}
      />
    </QueryClientProvider>,
  );
}

describe('CoverImage', () => {
  beforeEach(() => {
    resetGenState();
    createObjectURL.mockClear();
    revokeObjectURL.mockClear();
  });

  it('renders the platform-tinted fallback without fetching when hasImage is false', () => {
    const { container } = renderCover({ hasImage: false });

    expect(container.querySelector('[data-cover-fallback]')).not.toBeNull();
    expect(
      screen.getByRole('img', { name: '红烧肉 cover' }),
    ).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
    expect(genState.image).not.toHaveBeenCalled();
  });

  it('fetches the image through the generated client and shows the blob object URL', async () => {
    const blob = new Blob(['jpeg-bytes'], { type: 'image/jpeg' });
    genState.image.mockResolvedValue(blob);

    const { container, unmount } = renderCover({ hasImage: true });

    await waitFor(() =>
      expect(container.querySelector('img')).toHaveAttribute(
        'src',
        'blob:mock-cover',
      ),
    );
    expect(container.querySelector('img')).toHaveAttribute(
      'alt',
      '红烧肉 cover',
    );
    expect(genState.image).toHaveBeenCalledWith(
      expect.objectContaining({ path: { recipe_id: 'r1' } }),
    );
    expect(createObjectURL).toHaveBeenCalledWith(blob);

    // effect cleanup revokes the object URL
    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-cover');
  });

  it('falls back to the platform tile when the image fetch errors', async () => {
    genState.image.mockRejectedValue(new Error('image fetch failed (404)'));

    const { container } = renderCover({ hasImage: true, platform: 'rednote' });

    await waitFor(() => expect(genState.image).toHaveBeenCalled());
    await waitFor(() =>
      expect(container.querySelector('[data-cover-fallback]')).not.toBeNull(),
    );
    expect(container.querySelector('img')).toBeNull();
  });

  // ── V2-F: inline sprite covers ────────────────────────────────────────────

  it('renders the assigned sprite inline without fetching when hasImage is false', () => {
    const { container } = renderCover({
      hasImage: false,
      coverSpriteId: 'red-braised-pork',
    });

    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute('data-cover-sprite', 'red-braised-pork');
    expect(img).toHaveAttribute('alt', '红烧肉 cover');
    // The sprite is a bundled static asset — no auth'd /image blob fetch.
    expect(genState.image).not.toHaveBeenCalled();
    expect(container.querySelector('[data-cover-fallback]')).toBeNull();
  });

  it('renders the generic unknown-dish sprite as the final assigned fallback', () => {
    const { container } = renderCover({
      hasImage: false,
      coverSpriteId: 'unknown-dish',
    });
    expect(
      container.querySelector('[data-cover-sprite="unknown-dish"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-cover-fallback]')).toBeNull();
  });

  it('falls back to the gradient when the sprite id is unknown', () => {
    const { container } = renderCover({
      hasImage: false,
      coverSpriteId: 'not-a-real-sprite-id',
    });
    expect(container.querySelector('[data-cover-fallback]')).not.toBeNull();
    expect(container.querySelector('img')).toBeNull();
  });

  it('shows the served image over the sprite when both are available', async () => {
    const blob = new Blob(['jpeg-bytes'], { type: 'image/jpeg' });
    genState.image.mockResolvedValue(blob);

    const { container } = renderCover({
      hasImage: true,
      coverSpriteId: 'red-braised-pork',
    });

    await waitFor(() =>
      expect(container.querySelector('img')).toHaveAttribute(
        'src',
        'blob:mock-cover',
      ),
    );
    // The served frame wins — it is NOT the sprite.
    expect(
      container.querySelector('img')?.getAttribute('data-cover-sprite'),
    ).toBeNull();
  });

  it('falls back to the sprite (not the gradient) when a served image errors', async () => {
    genState.image.mockRejectedValue(new Error('image fetch failed (404)'));

    const { container } = renderCover({
      hasImage: true,
      coverSpriteId: 'red-braised-pork',
    });

    await waitFor(() => expect(genState.image).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        container.querySelector('[data-cover-sprite="red-braised-pork"]'),
      ).not.toBeNull(),
    );
    expect(container.querySelector('[data-cover-fallback]')).toBeNull();
  });
});
