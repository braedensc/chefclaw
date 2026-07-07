// One source of truth for the per-platform accent treatments (direction B's
// .nn-card--*/.nn-badge custom-property trick, spelled out as full class
// strings so Tailwind sees every class statically). Consumers: PlatformBadge,
// RecipeCard, RecipeDetailPage, CoverImage, PasteBar, JobsDrawer.

export interface PlatformAccent {
  /** PlatformBadge pill: hairline ring + text + halo. */
  badge: string;
  /** RecipeCard hover: platform rim + halo. */
  cardHover: string;
  /** Halo on the ZH display title (cards and the detail hero). */
  titleGlow: string;
  /** CSS custom-property reference for the platform tint (tokens in src/index.css). */
  tint: string;
}

const PLATFORM_ACCENTS: Record<string, PlatformAccent> = {
  bilibili: {
    badge: 'border-platform-bilibili/60 text-platform-bilibili glow-cyan',
    cardHover: 'hover:border-platform-bilibili/60 hover:glow-cyan',
    titleGlow: 'glow-text-cyan',
    tint: 'var(--color-platform-bilibili)',
  },
  rednote: {
    badge: 'border-platform-rednote/60 text-platform-rednote glow-chili',
    cardHover: 'hover:border-platform-rednote/60 hover:glow-chili',
    titleGlow: 'glow-text-chili',
    tint: 'var(--color-platform-rednote)',
  },
  local: {
    badge: 'border-platform-local/50 text-platform-local glow-warm',
    cardHover: 'hover:border-platform-local/50 hover:glow-warm',
    titleGlow: 'glow-text-warm',
    tint: 'var(--color-platform-local)',
  },
};

/** Unknown platforms stay neutral-warm — never a wrong platform hue. */
export const FALLBACK_ACCENT: PlatformAccent = {
  badge: 'border-line-bright text-ink-dim',
  cardHover: 'hover:border-line-bright hover:glow-warm',
  titleGlow: 'glow-text-warm',
  tint: 'var(--color-warm)',
};

export function platformAccent(platform: string): PlatformAccent {
  return PLATFORM_ACCENTS[platform] ?? FALLBACK_ACCENT;
}

/**
 * The no-cover gradient: platform tint spilling from the top-right corner
 * over the dark panel wash. `tintMixPercent` is deliberately a parameter —
 * CoverImage's fallback runs 15%, the detail hero's no-cover header 13%.
 */
export function fallbackCoverGradient(
  tint: string,
  tintMixPercent: number,
): string {
  return `radial-gradient(95% 85% at 100% 0%, color-mix(in srgb, ${tint} ${tintMixPercent}%, transparent), transparent 58%), linear-gradient(160deg, #101014 0%, var(--color-panel) 55%, #060608 100%)`;
}

/**
 * The stall's neon strip light (direction B .nn-paste::before) — apply via a
 * `style` background so the paste bar and jobs drawer share one spelling.
 */
export const STRIP_LIGHT =
  'linear-gradient(90deg, transparent, var(--color-chili) 22%, var(--color-gold) 50%, var(--color-cyan) 78%, transparent)';
