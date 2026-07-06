// Difficulty as 1–3 lit neon chilis — direction B's #nnChili symbol, ported
// with its exact lit/unlit colors: lit = chili red pod + green stem behind a
// glow drop-shadow, unlit = dim outline. Unknown difficulty renders nothing
// (never fabricate — the word comes verbatim from the validated document).

const DIFFICULTY_LEVELS: Record<string, number> = {
  easy: 1,
  medium: 2,
  hard: 3,
};

const CHILI_SLOTS = [1, 2, 3] as const;

function Chili({ lit }: { lit: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      className="size-3.5"
      aria-hidden="true"
      data-lit={lit}
      style={
        lit ? { filter: 'drop-shadow(0 0 3px rgba(255,70,85,.8))' } : undefined
      }
    >
      <path
        d="M11.2 3.9 C13.5 6.6 12.6 11.3 8.6 13.7 C5.9 15.3 2.9 15 2.1 13.7 C1.8 13.2 2.2 12.6 2.9 12.7 C6.8 13.4 9.6 10.2 9.9 6 C9.95 5.1 9.9 4.5 9.75 3.9 Z"
        fill={lit ? '#ff4655' : '#1e1e24'}
        stroke={lit ? 'rgba(255,150,160,.65)' : '#3a3a42'}
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      <path
        d="M10.4 3.9 C10.7 2.5 11.9 1.6 13.4 1.8"
        fill="none"
        stroke={lit ? '#3ddc68' : '#34343c'}
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * 1–3 lit chilis plus the difficulty word as visible text (screen-reader and
 * sighted parity — the glyphs are decorative). Unknown values render nothing.
 */
export function ChiliScale({ difficulty }: { difficulty: string }) {
  const lit = DIFFICULTY_LEVELS[difficulty];
  if (lit === undefined) return null;

  return (
    <span className="inline-flex items-center gap-1">
      {CHILI_SLOTS.map((slot) => (
        <Chili key={slot} lit={slot <= lit} />
      ))}
      <span className="font-display text-[11px] tracking-[0.14em] text-ink-dim uppercase">
        {difficulty}
      </span>
    </span>
  );
}
