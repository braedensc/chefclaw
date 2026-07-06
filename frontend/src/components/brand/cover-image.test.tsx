import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TOKEN_STORAGE_KEY } from '../../token';
import { CoverImage } from './cover-image';

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
        hasCover={false}
        platform="bilibili"
        alt="红烧肉 cover"
        {...props}
      />
    </QueryClientProvider>,
  );
}

describe('CoverImage', () => {
  beforeEach(() => {
    createObjectURL.mockClear();
    revokeObjectURL.mockClear();
  });

  it('renders the platform-tinted fallback without fetching when hasCover is false', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const { container } = renderCover({ hasCover: false });

    expect(container.querySelector('[data-cover-fallback]')).not.toBeNull();
    expect(
      screen.getByRole('img', { name: '红烧肉 cover' }),
    ).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('fetches the cover with the bearer token and shows the blob object URL', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'placeholder-token');
    const blob = new Blob(['jpeg-bytes'], { type: 'image/jpeg' });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(blob),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { container, unmount } = renderCover({ hasCover: true });

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
    expect(fetchMock).toHaveBeenCalledWith('/api/recipes/r1/cover', {
      headers: { Authorization: 'Bearer placeholder-token' },
    });
    expect(createObjectURL).toHaveBeenCalledWith(blob);

    // effect cleanup revokes the object URL
    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-cover');
  });

  it('falls back to the platform tile when the cover fetch errors', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404 });
    vi.stubGlobal('fetch', fetchMock);

    const { container } = renderCover({ hasCover: true, platform: 'rednote' });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() =>
      expect(container.querySelector('[data-cover-fallback]')).not.toBeNull(),
    );
    expect(container.querySelector('img')).toBeNull();
  });
});
