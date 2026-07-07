import { useId } from 'react';

// ALTERNATE MASCOT — the warm storybook puppy chef (bake-off direction A).
// NOT wired into the app right now: the active mascot is the neon puppy in
// puppy-chef.tsx. Kept here, intact and self-contained, so it can be reused
// elsewhere (a print piece, a light-theme, an about page) without redrawing it.
// Ported path-for-path from #mk-pup in
// planning/design-bakeoff/direction-a-midnight-kitchen.html: cream curly fur,
// tan floppy ears, pale-blue eyes with glints, ink outline, three-puff toque,
// both paws up with three claws each, wooden spoon in the right paw.

export type StorybookPuppyChefVariant = 'hero' | 'mark' | 'sleeping';

export interface StorybookPuppyChefProps {
  /** Rendered width in px; height follows the variant's aspect ratio. */
  size?: number;
  /**
   * 'hero' = full-detail portrait (empty states, token gate);
   * 'mark' = simplified head + toque, crisp at 20–46px (header);
   * 'sleeping' = curled-up pup for quiet/empty corners.
   */
  variant?: StorybookPuppyChefVariant;
  /** hero only: gentle bob + spoon wave + steam wisp (reduced-motion-guarded). */
  animated?: boolean;
  /** Accessible name; omitted → decorative (aria-hidden). */
  label?: string;
  className?: string;
}

const DEFAULT_SIZES: Record<StorybookPuppyChefVariant, number> = {
  hero: 150,
  mark: 32,
  sleeping: 140,
};

// Portrait palette (direction A) — ink outline on cream fur.
const INK = '#2e2a24';
const EYE = '#5f8aa3';

interface PawProps {
  transform: string;
  fill: string;
}

/** One raised paw: three claw wedges behind a padded ellipse. */
function Paw({ transform, fill }: PawProps) {
  return (
    <g transform={transform}>
      <path
        d="M-13 -8 L-9 -26 L-3 -10 Z"
        fill={fill}
        stroke={INK}
        strokeWidth="3"
        strokeLinejoin="round"
      />
      <path
        d="M-5 -11 L0 -30 L5 -11 Z"
        fill={fill}
        stroke={INK}
        strokeWidth="3"
        strokeLinejoin="round"
      />
      <path
        d="M3 -10 L9 -26 L13 -8 Z"
        fill={fill}
        stroke={INK}
        strokeWidth="3"
        strokeLinejoin="round"
      />
      <ellipse rx="18" ry="15.5" fill={fill} stroke={INK} strokeWidth="3" />
      <path
        d="M-6 -14 L-6 -4 M6 -14 L6 -4"
        stroke={INK}
        strokeWidth="2"
        strokeLinecap="round"
        opacity=".55"
      />
    </g>
  );
}

export function StorybookPuppyChef({
  size,
  variant = 'hero',
  animated = false,
  label,
  className,
}: StorybookPuppyChefProps) {
  const uid = useId();
  const width = size ?? DEFAULT_SIZES[variant];
  const a11y = label
    ? ({ role: 'img', 'aria-label': label } as const)
    : ({ 'aria-hidden': true } as const);

  if (variant === 'sleeping') {
    return (
      <SleepingPup
        width={width}
        className={className}
        a11y={a11y}
        data-variant="sleeping"
      />
    );
  }

  if (variant === 'mark') {
    return (
      <MarkPup
        width={width}
        className={className}
        a11y={a11y}
        data-variant="mark"
      />
    );
  }

  const fur = `${uid}-fur`;
  const ear = `${uid}-ear`;
  const paw = `${uid}-paw`;
  const hat = `${uid}-hat`;
  const spoon = `${uid}-spoon`;

  // Hero viewBox carries headroom for the steam wisp (direction A's
  // empty-state framing) whether or not it animates.
  return (
    <svg
      viewBox="0 -16 220 206"
      width={width}
      height={(width * 206) / 220}
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      data-variant="hero"
      {...a11y}
    >
      <defs>
        <radialGradient id={fur} cx="42%" cy="30%" r="85%">
          <stop offset="0%" stopColor="#fefaf1" />
          <stop offset="55%" stopColor="#f8f2e6" />
          <stop offset="100%" stopColor="#e9dcc2" />
        </radialGradient>
        <linearGradient id={ear} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#c2b295" />
          <stop offset="100%" stopColor="#9c8b6f" />
        </linearGradient>
        <linearGradient id={paw} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#fbf6ea" />
          <stop offset="100%" stopColor="#eadcbe" />
        </linearGradient>
        <linearGradient id={hat} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#fdf7ea" />
          <stop offset="100%" stopColor="#e3d2b2" />
        </linearGradient>
        <linearGradient id={spoon} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#cf9f63" />
          <stop offset="100%" stopColor="#94663a" />
        </linearGradient>
      </defs>
      <g className={animated ? 'pup-bob' : undefined}>
        {animated && (
          <path
            className="steam-wisp"
            d="M186 0 C182 -5 189 -8 185 -14"
            stroke="#f4e9d4"
            strokeWidth="2.6"
            strokeLinecap="round"
            fill="none"
            opacity=".4"
          />
        )}
        {/* floppy tan ears, behind the head */}
        <path
          d="M66 76 C35 87 29 136 61 157 C84 165 102 128 89 89 Z"
          fill={`url(#${ear})`}
          stroke={INK}
          strokeWidth="3.5"
          strokeLinejoin="round"
        />
        <path
          d="M154 76 C185 87 191 136 159 157 C136 165 118 128 131 89 Z"
          fill={`url(#${ear})`}
          stroke={INK}
          strokeWidth="3.5"
          strokeLinejoin="round"
        />
        <circle
          cx="110"
          cy="110"
          r="52"
          fill={`url(#${fur})`}
          stroke={INK}
          strokeWidth="3.5"
        />
        {/* curly-fur wisps */}
        <g
          stroke="#d9c9a6"
          strokeWidth="2.5"
          strokeLinecap="round"
          fill="none"
          opacity=".7"
        >
          <path d="M86 78 q6 -8 12 0" />
          <path d="M104 72 q6 -8 12 0" />
          <path d="M122 76 q6 -8 12 0" />
          <path d="M72 118 q5 -7 10 0" />
          <path d="M138 116 q5 -7 10 0" />
        </g>
        <ellipse
          cx="110"
          cy="134"
          rx="23"
          ry="15"
          fill="#fdfaf2"
          opacity=".9"
        />
        <circle
          cx="90.5"
          cy="105"
          r="9.4"
          fill={EYE}
          stroke={INK}
          strokeWidth="2.5"
        />
        <circle
          cx="129.5"
          cy="105"
          r="9.4"
          fill={EYE}
          stroke={INK}
          strokeWidth="2.5"
        />
        <circle cx="93.5" cy="101.5" r="2.8" fill="#fff" />
        <circle cx="132.5" cy="101.5" r="2.8" fill="#fff" />
        <circle cx="87.5" cy="108" r="1.4" fill="#fff" opacity=".8" />
        <circle cx="126.5" cy="108" r="1.4" fill="#fff" opacity=".8" />
        <ellipse cx="75" cy="124" rx="8" ry="5" fill="#e88585" opacity=".4" />
        <ellipse cx="145" cy="124" rx="8" ry="5" fill="#e88585" opacity=".4" />
        <ellipse cx="110" cy="129" rx="8.3" ry="6.2" fill={INK} />
        <path
          d="M110 136 Q110 143 102 144.5"
          stroke={INK}
          strokeWidth="3.5"
          strokeLinecap="round"
          fill="none"
        />
        <path
          d="M110 136 Q110 143 118 144.5"
          stroke={INK}
          strokeWidth="3.5"
          strokeLinecap="round"
          fill="none"
        />
        {/* left paw jumping up to say hi */}
        <Paw transform="translate(54 140) rotate(-25)" fill={`url(#${paw})`} />
        {/* right paw raised beside his face, waving the wooden spoon */}
        <g
          className={animated ? 'pup-wave' : undefined}
          style={animated ? { transformOrigin: '166px 140px' } : undefined}
        >
          <path
            d="M168 136 L184 28"
            stroke={INK}
            strokeWidth="9"
            strokeLinecap="round"
            fill="none"
          />
          <path
            d="M168 136 L184 28"
            stroke="#b0793f"
            strokeWidth="5"
            strokeLinecap="round"
            fill="none"
          />
          <ellipse
            cx="186"
            cy="20"
            rx="9.5"
            ry="13"
            transform="rotate(18 186 20)"
            fill={`url(#${spoon})`}
            stroke={INK}
            strokeWidth="3"
          />
          <ellipse
            cx="185"
            cy="19"
            rx="5"
            ry="8"
            transform="rotate(18 185 19)"
            fill="#8a5f33"
            opacity=".55"
          />
          <Paw
            transform="translate(166 140) rotate(25)"
            fill={`url(#${paw})`}
          />
        </g>
        {/* floppy three-puff toque, tilted */}
        <g transform="rotate(-7 110 44)">
          <path
            d="M78 52 C66 36 78 17 96 22 C100 6 124 6 128 22 C146 17 156 36 144 52 Z"
            fill={`url(#${hat})`}
            stroke={INK}
            strokeWidth="3"
          />
          <circle
            cx="145"
            cy="47"
            r="9"
            fill={`url(#${hat})`}
            stroke={INK}
            strokeWidth="3"
          />
          <rect
            x="76"
            y="48"
            width="68"
            height="15"
            rx="7.5"
            fill={`url(#${hat})`}
            stroke={INK}
            strokeWidth="3"
          />
        </g>
      </g>
    </svg>
  );
}

type A11yAttrs =
  | { readonly role: 'img'; readonly 'aria-label': string }
  | { readonly 'aria-hidden': true };

interface VariantSvgProps {
  width: number;
  className?: string;
  a11y: A11yAttrs;
  'data-variant': string;
}

/**
 * Header mark: head + toque only, flat fills and heavier outlines so it stays
 * crisp at 20–46px (paws and spoon muddy below ~48px).
 */
function MarkPup({ width, className, a11y, ...rest }: VariantSvgProps) {
  return (
    <svg
      viewBox="0 0 96 96"
      width={width}
      height={width}
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      {...rest}
      {...a11y}
    >
      <path
        d="M28 40 C13 46 11 68 26 76 C36 79 42 62 37 46 Z"
        fill="#b3a284"
        stroke={INK}
        strokeWidth="3.5"
        strokeLinejoin="round"
      />
      <path
        d="M68 40 C83 46 85 68 70 76 C60 79 54 62 59 46 Z"
        fill="#b3a284"
        stroke={INK}
        strokeWidth="3.5"
        strokeLinejoin="round"
      />
      <circle
        cx="48"
        cy="55"
        r="25"
        fill="#f8f2e6"
        stroke={INK}
        strokeWidth="3.5"
      />
      <circle
        cx="37"
        cy="20"
        r="8"
        fill="#fdf7ea"
        stroke={INK}
        strokeWidth="3.5"
      />
      <circle
        cx="48"
        cy="16"
        r="9"
        fill="#fdf7ea"
        stroke={INK}
        strokeWidth="3.5"
      />
      <circle
        cx="59"
        cy="20"
        r="8"
        fill="#fdf7ea"
        stroke={INK}
        strokeWidth="3.5"
      />
      <rect
        x="31"
        y="22"
        width="34"
        height="11"
        rx="5.5"
        fill="#fdf7ea"
        stroke={INK}
        strokeWidth="3.5"
      />
      <circle cx="39" cy="53" r="4.6" fill={EYE} />
      <circle cx="57" cy="53" r="4.6" fill={EYE} />
      <circle cx="40.5" cy="51.5" r="1.5" fill="#fff" />
      <circle cx="58.5" cy="51.5" r="1.5" fill="#fff" />
      <ellipse cx="48" cy="66" rx="11" ry="8" fill="#fdfaf2" />
      <ellipse cx="48" cy="63" rx="4.4" ry="3.4" fill={INK} />
      <path
        d="M48 66.5 Q48 70.5 43.5 71.5"
        stroke={INK}
        strokeWidth="2.6"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M48 66.5 Q48 70.5 52.5 71.5"
        stroke={INK}
        strokeWidth="2.6"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

/**
 * Curled-up sleeping pup — todoclaw's SleepingPuppy pose language (curled
 * body, head low, closed-arc eye, z z) redrawn in the chefclaw storybook
 * style: portrait colors, ink outline, toque slouched over one ear.
 */
function SleepingPup({ width, className, a11y, ...rest }: VariantSvgProps) {
  return (
    <svg
      viewBox="0 0 160 110"
      width={width}
      height={(width * 110) / 160}
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      {...rest}
      {...a11y}
    >
      {/* tail curl */}
      <path
        d="M128 82 q16 -8 9 -24"
        stroke="#b3a284"
        strokeWidth="7"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M128 82 q16 -8 9 -24"
        stroke={INK}
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
        opacity=".35"
      />
      {/* curled body */}
      <path
        d="M24 88 C8 66 22 40 56 34 C90 27 120 34 132 52 C144 70 138 88 114 94 C84 101 46 99 24 88 Z"
        fill="#f8f2e6"
        stroke={INK}
        strokeWidth="3.5"
        strokeLinejoin="round"
      />
      {/* haunch shading + curly-fur wisps */}
      <path
        d="M96 44 C118 48 128 64 120 80"
        stroke="#e9dcc2"
        strokeWidth="7"
        strokeLinecap="round"
        fill="none"
        opacity=".8"
      />
      <g
        stroke="#d9c9a6"
        strokeWidth="2.5"
        strokeLinecap="round"
        fill="none"
        opacity=".7"
      >
        <path d="M70 46 q6 -8 12 0" />
        <path d="M92 56 q6 -8 12 0" />
        <path d="M78 72 q5 -7 10 0" />
      </g>
      {/* head resting on paws, muzzle low at the left */}
      <circle
        cx="40"
        cy="62"
        r="23"
        fill="#f8f2e6"
        stroke={INK}
        strokeWidth="3.5"
      />
      {/* floppy tan ear draped over */}
      <path
        d="M42 42 C26 38 12 50 16 66 C19 76 32 76 36 66 C39 58 41 50 42 42 Z"
        fill="#b3a284"
        stroke={INK}
        strokeWidth="3"
        strokeLinejoin="round"
      />
      {/* muzzle, nose, closed-arc eye, blush */}
      <ellipse cx="28" cy="72" rx="10" ry="7.5" fill="#fdfaf2" />
      <ellipse cx="24" cy="68" rx="4.4" ry="3.4" fill={INK} />
      <path
        d="M46 62 q5 4 10 0"
        stroke={INK}
        strokeWidth="3"
        strokeLinecap="round"
        fill="none"
      />
      <ellipse cx="52" cy="72" rx="6" ry="3.5" fill="#e88585" opacity=".4" />
      {/* toque slouched over the ear */}
      <g transform="rotate(-18 46 34)">
        <circle
          cx="38"
          cy="26"
          r="6"
          fill="#fdf7ea"
          stroke={INK}
          strokeWidth="2.6"
        />
        <circle
          cx="47"
          cy="23"
          r="7"
          fill="#fdf7ea"
          stroke={INK}
          strokeWidth="2.6"
        />
        <circle
          cx="56"
          cy="26"
          r="6"
          fill="#fdf7ea"
          stroke={INK}
          strokeWidth="2.6"
        />
        <rect
          x="33"
          y="28"
          width="27"
          height="9"
          rx="4.5"
          fill="#fdf7ea"
          stroke={INK}
          strokeWidth="2.6"
        />
      </g>
      {/* z z */}
      <text
        x="78"
        y="26"
        fontSize="15"
        fill="#9a9ba6"
        style={{ fontFamily: 'var(--font-display)' }}
      >
        z
      </text>
      <text
        x="90"
        y="14"
        fontSize="11"
        fill="#63646e"
        style={{ fontFamily: 'var(--font-display)' }}
      >
        z
      </text>
    </svg>
  );
}
