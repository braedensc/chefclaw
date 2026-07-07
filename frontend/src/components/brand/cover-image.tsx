import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

import { getRecipeImageApiRecipesRecipeIdImageGetOptions } from '../../client/@tanstack/react-query.gen';
import { fallbackCoverGradient, platformAccent } from './platform-accents';
import { SteamWisps } from './steam-wisps';

// The authed recipe image (a generated dish illustration), fetched through the
// generated SDK — auth and ApiError mapping live centrally in src/api.ts.
// <img> can't send an Authorization header, so the image bytes come down as a
// blob → object URL. Loading and error states show the same platform-tinted
// fallback as hasImage=false — no spinner flash; empty covers still look
// intentional.

export interface CoverImageProps {
  recipeId: string;
  hasImage: boolean;
  platform: string;
  alt: string;
  /** Caller sizes the tile (e.g. `aspect-[16/10]`) — the art fills it. */
  className?: string;
}

// Legibility scrim baked over every state — dark bottom ~45% so overlaid
// titles read (direction B's .nn-cover::after treatment).
const SCRIM =
  'linear-gradient(180deg, rgba(5,5,5,0) 42%, rgba(5,5,5,.55) 70%, rgba(6,6,8,.93) 100%)';

/** Refined dark gradient in the platform hue + subtle steam wisps. */
function FallbackArt({ platform, alt }: { platform: string; alt: string }) {
  const { tint } = platformAccent(platform);
  return (
    <div
      role="img"
      aria-label={alt}
      data-cover-fallback
      className="absolute inset-0"
      style={{ background: fallbackCoverGradient(tint, 15) }}
    >
      <svg
        viewBox="0 0 64 64"
        aria-hidden="true"
        className="absolute top-1/2 left-1/2 h-1/3 w-auto -translate-x-1/2 -translate-y-1/2 opacity-60"
      >
        <SteamWisps
          transform="translate(0 24)"
          opacities={[0.35, 0.45, 0.35]}
        />
      </svg>
    </div>
  );
}

export function CoverImage({
  recipeId,
  hasImage,
  platform,
  alt,
  className,
}: CoverImageProps) {
  const imageQuery = useQuery({
    ...getRecipeImageApiRecipesRecipeIdImageGetOptions({
      path: { recipe_id: recipeId },
    }),
    enabled: hasImage,
    // The image never changes for a stored recipe — fetch once per session
    // and never evict (the default 5-min gcTime would re-download the bytes
    // on back-navigation).
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  });

  // The generated response type is `unknown`; the client parses the image
  // bytes to a Blob. The object URL is derived synchronously (useMemo) so
  // the image paints on the same render the blob lands — no post-paint
  // flash from a useState-in-effect double render; the effect cleanup
  // revokes the previous URL on change/unmount.
  const blob = imageQuery.data instanceof Blob ? imageQuery.data : null;
  const objectUrl = useMemo(
    () => (blob === null ? null : URL.createObjectURL(blob)),
    [blob],
  );
  useEffect(() => {
    if (objectUrl === null) return;
    return () => URL.revokeObjectURL(objectUrl);
  }, [objectUrl]);

  // A blob that doesn't decode (a corrupt/partial image, or a placeholder in
  // dev) must show the tasteful fallback, never a broken-image glyph. Reset
  // the flag whenever the URL changes so a new image gets a fresh chance.
  const [decodeFailed, setDecodeFailed] = useState(false);
  useEffect(() => setDecodeFailed(false), [objectUrl]);

  const showImage =
    hasImage && objectUrl !== null && !imageQuery.isError && !decodeFailed;

  return (
    <div className={`relative overflow-hidden ${className ?? ''}`}>
      {showImage ? (
        <img
          src={objectUrl}
          alt={alt}
          onError={() => setDecodeFailed(true)}
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
