import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { getToken } from '../../token';

// The authed recipe-cover image. <img> can't send an Authorization header, so
// the cover bytes come down via an authed fetch → blob → object URL. Loading
// and error states show the same platform-tinted fallback as hasCover=false —
// no spinner flash; empty covers still look intentional.

export interface CoverImageProps {
  recipeId: string;
  hasCover: boolean;
  platform: string;
  alt: string;
  /** Caller sizes the tile (e.g. `aspect-[16/10]`) — the art fills it. */
  className?: string;
}

// Platform accent for the fallback's corner spill (tokens in src/index.css).
const PLATFORM_TINTS: Record<string, string> = {
  bilibili: 'var(--color-platform-bilibili)',
  rednote: 'var(--color-platform-rednote)',
  local: 'var(--color-platform-local)',
};

const FALLBACK_TINT = 'var(--color-warm)';

// Legibility scrim baked over every state — dark bottom ~45% so overlaid
// titles read (direction B's .nn-cover::after treatment).
const SCRIM =
  'linear-gradient(180deg, rgba(5,5,5,0) 42%, rgba(5,5,5,.55) 70%, rgba(6,6,8,.93) 100%)';

/** Refined dark gradient in the platform hue + subtle steam wisps. */
function FallbackArt({ platform, alt }: { platform: string; alt: string }) {
  const tint = PLATFORM_TINTS[platform] ?? FALLBACK_TINT;
  return (
    <div
      role="img"
      aria-label={alt}
      data-cover-fallback
      className="absolute inset-0"
      style={{
        background: `radial-gradient(95% 85% at 100% 0%, color-mix(in srgb, ${tint} 15%, transparent), transparent 58%), linear-gradient(160deg, #101014 0%, var(--color-panel) 55%, #060608 100%)`,
      }}
    >
      <svg
        viewBox="0 0 64 64"
        aria-hidden="true"
        className="absolute top-1/2 left-1/2 h-1/3 w-auto -translate-x-1/2 -translate-y-1/2 opacity-60"
      >
        <g stroke="#f4e9d4" strokeWidth="2.4" strokeLinecap="round" fill="none">
          <path
            className="steam-wisp"
            d="M22 46 C20 42 24 39 22 34"
            opacity=".35"
          />
          <path
            className="steam-wisp steam-wisp-2"
            d="M32 44 C30 40 34 37 32 31"
            opacity=".45"
          />
          <path
            className="steam-wisp steam-wisp-3"
            d="M42 46 C40 42 44 39 42 34"
            opacity=".35"
          />
        </g>
      </svg>
    </div>
  );
}

export function CoverImage({
  recipeId,
  hasCover,
  platform,
  alt,
  className,
}: CoverImageProps) {
  const coverQuery = useQuery({
    queryKey: ['recipe-cover', recipeId],
    queryFn: async () => {
      const token = getToken();
      const response = await fetch(`/api/recipes/${recipeId}/cover`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!response.ok) {
        throw new Error(`cover fetch failed (${response.status})`);
      }
      return response.blob();
    },
    enabled: hasCover,
    // The cover never changes for a stored recipe — fetch once per session.
    staleTime: Infinity,
    retry: false,
  });

  // Object URL is created here and revoked in the effect cleanup — effect
  // (not useMemo) so StrictMode's double-invoke never leaks a URL.
  const blob = coverQuery.data ?? null;
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) {
      setObjectUrl(null);
      return;
    }
    const url = URL.createObjectURL(blob);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [blob]);

  const showImage = hasCover && objectUrl !== null && !coverQuery.isError;

  return (
    <div className={`relative overflow-hidden ${className ?? ''}`}>
      {showImage ? (
        <img
          src={objectUrl}
          alt={alt}
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : (
        <FallbackArt platform={platform} alt={alt} />
      )}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{ background: SCRIM }}
      />
    </div>
  );
}
