// Neon rim pill (direction B's .nn-badge): platform-token hairline ring +
// halo, text stays the lowercase platform value as data — the caps look is
// text-transform only, so tests keep matching the literal 'bilibili'.

const BADGE_STYLES: Record<string, string> = {
  bilibili: 'border-platform-bilibili/60 text-platform-bilibili glow-cyan',
  rednote: 'border-platform-rednote/60 text-platform-rednote glow-chili',
  local: 'border-platform-local/50 text-platform-local glow-warm',
};

const FALLBACK_STYLE = 'border-line-bright text-ink-dim';

/** Small pill naming the source platform (bilibili / rednote / local). */
export function PlatformBadge({ platform }: { platform: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-chip border bg-night/70 px-2 py-0.5 font-display text-[10px] font-bold tracking-[0.18em] uppercase ${BADGE_STYLES[platform] ?? FALLBACK_STYLE}`}
    >
      {platform}
    </span>
  );
}
