import { useId } from 'react';

// The house mascot — the NEON puppy chef (bake-off direction B), the one
// Braeden picked to live in the app. Drawn as glowing neon tubes (open stroked
// paths, round caps) over the black base, so it reads like a lit night-market
// storefront sign: pink toque, warm-white head + claws-up paws, tan-gold floppy
// ears, cyan eyes/nose/smile, a gold spatula raised in one paw. Ported from the
// #nn-pup markup in planning/design-bakeoff/direction-b-neon-night-market.html.
// The warm storybook alternate lives in puppy-chef-storybook.tsx (kept for reuse).

export type PuppyChefVariant = 'hero' | 'mark' | 'sleeping';

export interface PuppyChefProps {
  /** Rendered width in px; height follows the variant's aspect ratio. */
  size?: number;
  /**
   * 'hero' = full glowing pup (empty states, token gate);
   * 'mark' = simplified head + toque, crisp at 20–46px (header);
   * 'sleeping' = curled-up pup for quiet/empty corners.
   */
  variant?: PuppyChefVariant;
  /** hero only: neon-sign flicker (reduced-motion-guarded via .neon-flicker). */
  animated?: boolean;
  /** Accessible name; omitted → decorative (aria-hidden). */
  label?: string;
  className?: string;
}

const DEFAULT_SIZES: Record<PuppyChefVariant, number> = {
  hero: 150,
  mark: 34,
  sleeping: 140,
};

// Neon tube palette (direction B), aligned to the design tokens.
const PINK = '#ff4d6d'; // toque
const TAN = '#e0a458'; // ears
const WHITE = '#fff3e0'; // head + paws
const CYAN = '#35e0ff'; // eyes / nose / smile
const GOLD = '#ffd60a'; // spatula

/** The stacked-blur glow every neon tube shares — scoped per instance. */
function NeonFilter({ id, blur }: { id: string; blur: [number, number] }) {
  return (
    <filter id={id} x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur in="SourceGraphic" stdDeviation={blur[0]} result="b1" />
      <feGaussianBlur in="SourceGraphic" stdDeviation={blur[1]} result="b2" />
      <feMerge>
        <feMergeNode in="b2" />
        <feMergeNode in="b1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
  );
}

export function PuppyChef({
  size,
  variant = 'hero',
  animated = false,
  label,
  className,
}: PuppyChefProps) {
  const uid = useId();
  const fid = `${uid}-neon`;
  const width = size ?? DEFAULT_SIZES[variant];
  const a11y = label
    ? ({ role: 'img', 'aria-label': label } as const)
    : ({ 'aria-hidden': true } as const);

  if (variant === 'sleeping') {
    return (
      <svg
        viewBox="0 0 160 110"
        width={width}
        height={(width * 110) / 160}
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        data-variant="sleeping"
        {...a11y}
      >
        <defs>
          <NeonFilter id={fid} blur={[1.4, 4]} />
        </defs>
        <g
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          filter={`url(#${fid})`}
        >
          {/* curled loaf body, tail curling up at the right */}
          <path
            d="M58 62 C80 48 116 50 130 64 C142 76 137 91 115 95 C94 98 72 95 58 85"
            stroke={WHITE}
            strokeWidth="4.5"
          />
          <path d="M128 68 q16 -6 10 -22" stroke={TAN} strokeWidth="4" />
          {/* head tucked down at the front, muzzle low-left */}
          <path
            d="M62 66 C62 80 50 90 36 88 C22 86 14 74 18 60 C22 48 34 44 46 47 C55 49 61 56 62 66"
            stroke={WHITE}
            strokeWidth="4.5"
          />
          {/* floppy tan ear draped down the side */}
          <path
            d="M40 49 C26 45 16 55 20 69 C23 78 33 77 36 68"
            stroke={TAN}
            strokeWidth="4"
          />
          {/* closed-arc sleepy eye + nose at the muzzle */}
          <path d="M40 66 q5 4 10 0" stroke={CYAN} strokeWidth="3.5" />
          <ellipse cx="20" cy="70" rx="3.6" ry="3" fill={CYAN} stroke="none" />
          {/* toque perched on the head, tilted */}
          <g stroke={PINK} strokeWidth="4" transform="rotate(-12 46 40)">
            <path d="M30 42 C24 32 34 24 44 28 C47 20 59 20 62 28 C72 24 80 32 74 42" />
            <path d="M30 44 L74 44" />
          </g>
        </g>
        {/* z z nap glyphs, rising over the back */}
        <text
          x="104"
          y="30"
          fontSize="16"
          fill={CYAN}
          opacity=".85"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          z
        </text>
        <text
          x="118"
          y="16"
          fontSize="11"
          fill={GOLD}
          opacity=".8"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          z
        </text>
      </svg>
    );
  }

  if (variant === 'mark') {
    // A dedicated small head + toque + face in a square box, thinner glow so it
    // stays legible at header scale (paws/spoon muddy under ~48px).
    return (
      <svg
        viewBox="0 0 100 100"
        width={width}
        height={width}
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        data-variant="mark"
        {...a11y}
      >
        <defs>
          <NeonFilter id={fid} blur={[1, 3]} />
        </defs>
        <g
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          filter={`url(#${fid})`}
        >
          {/* tan floppy ears */}
          <g stroke={TAN} strokeWidth="5">
            <path d="M28 48 C14 46 8 62 14 74 C17 80 25 80 29 73 C32 67 33 58 33 52" />
            <path d="M72 48 C86 46 92 62 86 74 C83 80 75 80 71 73 C68 67 67 58 67 52" />
          </g>
          {/* warm-white head */}
          <path
            stroke={WHITE}
            strokeWidth="5"
            d="M30 46 C22 54 18 64 18 74 C18 88 32 96 50 96 C68 96 82 88 82 74 C82 64 78 54 70 46"
          />
          {/* pink toque */}
          <g stroke={PINK} strokeWidth="5.5">
            <path d="M32 46 C22 46 17 36 22 29 C26 24 32 23 36 26 C38 18 46 14 50 14 C54 14 62 18 64 26 C68 23 74 24 78 29 C83 36 78 46 68 46" />
            <path d="M31 49 L69 49" />
          </g>
          {/* cyan eyes + glints, nose, smile */}
          <g stroke={CYAN} strokeWidth="4.5">
            <circle cx="40" cy="70" r="4.6" fill={CYAN} stroke="none" />
            <circle cx="60" cy="70" r="4.6" fill={CYAN} stroke="none" />
            <circle cx="42" cy="68" r="1.5" fill={WHITE} stroke="none" />
            <circle cx="62" cy="68" r="1.5" fill={WHITE} stroke="none" />
            <ellipse
              cx="50"
              cy="82"
              rx="4"
              ry="3.2"
              fill={CYAN}
              stroke="none"
            />
            <path d="M50 87 Q50 93 43 94" strokeWidth="3.5" />
            <path d="M50 87 Q50 93 57 94" strokeWidth="3.5" />
          </g>
        </g>
      </svg>
    );
  }

  // hero — the full glowing pup, claws up, spatula raised.
  return (
    <svg
      viewBox="0 0 224 200"
      width={width}
      height={(width * 200) / 224}
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      data-variant="hero"
      {...a11y}
    >
      <defs>
        <NeonFilter id={fid} blur={[2, 6]} />
      </defs>
      <g
        className={animated ? 'neon-flicker' : undefined}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter={`url(#${fid})`}
      >
        {/* pink toque */}
        <g stroke={PINK} strokeWidth="5">
          <path d="M86 55 C74 55 68 44 74 36 C78 30 86 29 91 32 C93 23 103 18 112 18 C121 18 131 23 133 32 C138 29 146 30 150 36 C156 44 150 55 138 55" />
          <rect x="84" y="57" width="56" height="13" rx="6.5" />
        </g>
        {/* tan floppy ears */}
        <g stroke={TAN} strokeWidth="5">
          <path d="M82 73 C56 70 42 88 46 106 C48 114 59 116 65 108 C70 101 74 92 76 83" />
          <path d="M142 73 C168 70 182 88 178 106 C176 114 165 116 159 108 C154 101 150 92 148 83" />
        </g>
        {/* warm-white head + both claws-up paws */}
        <g stroke={WHITE} strokeWidth="5">
          <path d="M78 82 C64 92 57 104 57 118 C57 146 81 164 112 164 C143 164 167 146 167 118 C167 104 160 92 146 82" />
          <g transform="translate(48 148) rotate(-25)">
            <ellipse rx="12" ry="10" />
            <path d="M-8 -8 L-13 -19" />
            <path d="M0 -10 L0 -24" />
            <path d="M8 -8 L13 -19" />
          </g>
          <g transform="translate(176 148) rotate(25)">
            <ellipse rx="12" ry="10" />
            <path d="M-8 -8 L-13 -19" />
            <path d="M0 -10 L0 -24" />
            <path d="M8 -8 L13 -19" />
          </g>
        </g>
        {/* cyan eyes + glints, nose, smile */}
        <g stroke={CYAN} strokeWidth="4">
          <circle cx="96" cy="119" r="5" fill={CYAN} stroke="none" />
          <circle cx="128" cy="119" r="5" fill={CYAN} stroke="none" />
          <circle cx="98.2" cy="116.8" r="1.8" fill={WHITE} stroke="none" />
          <circle cx="130.2" cy="116.8" r="1.8" fill={WHITE} stroke="none" />
          <ellipse
            cx="112"
            cy="138"
            rx="4.4"
            ry="3.5"
            fill={CYAN}
            stroke="none"
          />
          <path d="M112 145 Q112 152 104 153" />
          <path d="M112 145 Q112 152 120 153" />
        </g>
        {/* gold spatula in the raised right paw */}
        <g stroke={GOLD} strokeWidth="4.5">
          <path d="M186 128 L196 90" />
          <rect
            x="189"
            y="69"
            width="21"
            height="15"
            rx="5"
            transform="rotate(15 199.5 76.5)"
          />
        </g>
      </g>
    </svg>
  );
}
