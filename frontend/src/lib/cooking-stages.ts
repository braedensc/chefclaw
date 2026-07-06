// Chip-side staged microcopy for extraction jobs. The jobs DRAWER keeps the
// sober statusLabel() vocabulary (src/lib/job-status.ts — the golden suite
// asserts 'Stored' there); these playful bilingual lines are for chips only.
// `failed` is deliberately unmapped: the chip renders its own failure UI.

/** Number of numbered pipeline steps a chip renders ('STEP n / 4'). */
export const COOKING_STEP_TOTAL = 4;

export interface CookingStage {
  /** Bilingual chip line; unknown statuses fall back to the raw status. */
  copy: string;
  /** 1-based pipeline step, or null when not a numbered step (terminal/unknown). */
  step: number | null;
  total: number;
}

const STAGES: Record<string, { copy: string; step: number | null }> = {
  pending: { copy: 'in the queue… 排队中', step: 1 },
  downloading: { copy: 'fetching the video… 取片中', step: 2 },
  extracting: { copy: 'reading the recipe… 正在读菜谱', step: 3 },
  validating: { copy: 'checking the notes… 校对中', step: 4 },
  stored: { copy: 'plated! 上菜了', step: null },
};

export function cookingStage(status: string): CookingStage {
  const stage = STAGES[status];
  if (stage === undefined) {
    return { copy: status, step: null, total: COOKING_STEP_TOTAL };
  }
  return { ...stage, total: COOKING_STEP_TOTAL };
}
