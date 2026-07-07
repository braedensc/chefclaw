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
   * 'hero' = full glowing pup, thin tubes (empty states, token gate);
   * 'mark' = the SAME full pup rendered small with thick tubes, the mock's
   *   storefront sign treatment — crisp at header scale (header);
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
  mark: 44,
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
          {/* curled body — a low flat loaf, back gently domed, belly closed so
              it reads as a mass (not a hollow ring); tail flicks up at the right */}
          <path
            d="M60 95 C48 93 47 74 64 67 C87 58 117 59 131 71 C141 79 139 93 127 95 C104 97 82 97 60 95 Z"
            stroke={WHITE}
            strokeWidth="5"
          />
          <path d="M130 78 q17 -5 11 -25" stroke={TAN} strokeWidth="4.5" />
          {/* small head resting at the front-left, tucked against the body */}
          <path
            d="M58 78 C59 90 49 97 38 95 C27 93 22 84 26 74 C30 65 40 63 48 67 C54 70 57 73 58 78 Z"
            stroke={WHITE}
            strokeWidth="5"
          />
          {/* floppy tan ear draped down the cheek */}
          <path
            d="M42 67 C29 63 21 73 25 84 C28 92 36 91 39 82"
            stroke={TAN}
            strokeWidth="4.5"
          />
          {/* closed-arc sleepy eye + nose at the muzzle tip */}
          <path d="M34 81 q6 5 12 0" stroke={CYAN} strokeWidth="4" />
          <ellipse
            cx="22"
            cy="83"
            rx="3.8"
            ry="3.2"
            fill={CYAN}
            stroke="none"
          />
          {/* pink toque perched on the head, tilted back */}
          <g stroke={PINK} strokeWidth="4.5" transform="rotate(-16 44 58)">
            <path d="M30 60 C24 50 34 42 44 46 C47 38 59 38 62 46 C72 42 80 50 74 60" />
            <path d="M30 62 L74 62" />
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
    // The header sign: the FULL neon pup (toque, floppy ears, claws-up paws,
    // gold spatula) rendered small with THICK tubes and a tight glow — the
    // mock's storefront-mark treatment, so it stays a chunky lit sign at
    // header scale instead of thinning out.
    return (
      <svg
        viewBox="0 0 224 200"
        width={width}
        height={(width * 200) / 224}
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        data-variant="mark"
        {...a11y}
      >
        <defs>
          <NeonFilter id={fid} blur={[1.5, 4.5]} />
        </defs>
        <g
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          filter={`url(#${fid})`}
        >
          {/* pink toque */}
          <g stroke={PINK} strokeWidth="9">
            <path d="M86 55 C74 55 68 44 74 36 C78 30 86 29 91 32 C93 23 103 18 112 18 C121 18 131 23 133 32 C138 29 146 30 150 36 C156 44 150 55 138 55" />
            <rect x="84" y="57" width="56" height="13" rx="6.5" />
          </g>
          {/* tan floppy ears */}
          <g stroke={TAN} strokeWidth="8">
            <path d="M82 73 C56 70 42 88 46 106 C48 114 59 116 65 108 C70 101 74 92 76 83" />
            <path d="M142 73 C168 70 182 88 178 106 C176 114 165 116 159 108 C154 101 150 92 148 83" />
          </g>
          {/* warm-white head + both claws-up paws */}
          <g stroke={WHITE} strokeWidth="9">
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
          {/* cyan eyes, nose, smile */}
          <g stroke={CYAN} strokeWidth="8">
            <circle cx="96" cy="119" r="6" fill={CYAN} stroke="none" />
            <circle cx="128" cy="119" r="6" fill={CYAN} stroke="none" />
            <ellipse
              cx="112"
              cy="138"
              rx="5"
              ry="4"
              fill={CYAN}
              stroke="none"
            />
            <path d="M112 145 Q112 152 104 153" />
            <path d="M112 145 Q112 152 120 153" />
          </g>
          {/* gold spatula in the raised right paw */}
          <g stroke={GOLD} strokeWidth="8">
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
