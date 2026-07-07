// Neon rim pill (direction B's .nn-badge): platform-token hairline ring +
// halo, text stays the lowercase platform value as data — the caps look is
// text-transform only, so tests keep matching the literal 'bilibili'.

import { platformAccent } from './brand/platform-accents';

/** Small pill naming the source platform (bilibili / rednote / local). */
export function PlatformBadge({ platform }: { platform: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-chip border bg-night/70 px-2 py-0.5 font-display text-[10px] font-bold tracking-[0.18em] uppercase ${platformAccent(platform).badge}`}
    >
      {platform}
    </span>
  );
}
