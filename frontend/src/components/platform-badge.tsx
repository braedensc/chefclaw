const BADGE_STYLES: Record<string, string> = {
  bilibili: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
  rednote: 'bg-rose-500/15 text-rose-300 ring-rose-500/30',
  local: 'bg-neutral-500/15 text-neutral-300 ring-neutral-500/30',
};

const FALLBACK_STYLE = 'bg-neutral-500/15 text-neutral-300 ring-neutral-500/30';

/** Small pill naming the source platform (bilibili / rednote / local). */
export function PlatformBadge({ platform }: { platform: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${BADGE_STYLES[platform] ?? FALLBACK_STYLE}`}
    >
      {platform}
    </span>
  );
}
