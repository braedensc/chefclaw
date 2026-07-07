import { describe, expect, it } from 'vitest';

import { COOKING_STEP_TOTAL, cookingStage } from './cooking-stages';

describe('cookingStage', () => {
  it('maps the four pipeline statuses to numbered bilingual steps', () => {
    expect(cookingStage('pending')).toEqual({
      copy: 'in the queue… 排队中',
      step: 1,
      total: COOKING_STEP_TOTAL,
    });
    expect(cookingStage('downloading')).toEqual({
      copy: 'fetching the video… 取片中',
      step: 2,
      total: COOKING_STEP_TOTAL,
    });
    expect(cookingStage('extracting')).toEqual({
      copy: 'reading the recipe… 正在读菜谱',
      step: 3,
      total: COOKING_STEP_TOTAL,
    });
    expect(cookingStage('validating')).toEqual({
      copy: 'checking the notes… 校对中',
      step: 4,
      total: COOKING_STEP_TOTAL,
    });
  });

  it('maps stored to the plated line with no step number', () => {
    expect(cookingStage('stored')).toEqual({
      copy: 'plated! 上菜了',
      step: null,
      total: COOKING_STEP_TOTAL,
    });
  });

  it('falls back to the raw status for unknown statuses (failed included)', () => {
    expect(cookingStage('failed')).toEqual({
      copy: 'failed',
      step: null,
      total: COOKING_STEP_TOTAL,
    });
    expect(cookingStage('mystery_status')).toEqual({
      copy: 'mystery_status',
      step: null,
      total: COOKING_STEP_TOTAL,
    });
  });

  it('exposes a 4-step total', () => {
    expect(COOKING_STEP_TOTAL).toBe(4);
  });
});
