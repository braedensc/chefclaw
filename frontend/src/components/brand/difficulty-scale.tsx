// Difficulty as a 0–3 level meter — a mark VISUALLY DISTINCT from the chili
// spiciness scale: three short rounded bars of increasing height, filled up to
// `level` in electric cyan (with a soft cyan glow), empty bars in dim hairline.
// The level is a DERIVED estimate (estimated_difficulty_level), so the label is
// flagged "(estimated)"; a null/undefined level renders nothing (Hard Rule 7).

const DIFFICULTY_WORDS = ['very easy', 'easy', 'medium', 'hard'] as const;

// Three bars of increasing height, baseline-aligned in a 16-tall viewBox.
const BARS = [
  { x: 1.5, y: 9, h: 6 },
  { x: 6.5, y: 5.5, h: 9.5 },
  { x: 11.5, y: 2, h: 13 },
] as const;

function LevelMeter({ level }: { level: number }) {
  return (
    <svg viewBox="0 0 16 16" className="size-3.5" aria-hidden="true">
      {BARS.map((bar, index) => {
        const filled = index < level;
        return (
          <rect
            key={bar.x}
            x={bar.x}
            y={bar.y}
            width="3"
            height={bar.h}
            rx="1.3"
            data-filled={filled}
            fill={filled ? '#35e0ff' : '#26262c'}
            style={
              filled
                ? {
                    filter:
                      'drop-shadow(0 0 3px color-mix(in srgb, #35e0ff 55%, transparent))',
                  }
                : undefined
            }
          />
        );
      })}
    </svg>
  );
}

/**
 * A 3-segment level meter filled up to `level` (0–3), plus the difficulty word
 * as visible text (screen-reader and sighted parity — the glyphs are
 * decorative). The value is an ESTIMATE, so the label says so. A null/undefined
 * level renders nothing.
 */
export function DifficultyScale({
  level,
}: {
  level: number | null | undefined;
}) {
  if (level == null) return null;
  const word = DIFFICULTY_WORDS[level] ?? DIFFICULTY_WORDS[0];

  return (
    <span
      className="inline-flex items-center gap-1"
      aria-label={`Difficulty: ${word} (estimated)`}
    >
      <LevelMeter level={level} />
      <span
        aria-hidden="true"
        className="font-display text-[11px] tracking-[0.14em] text-ink-dim uppercase"
      >
        {word}
      </span>
    </span>
  );
}
