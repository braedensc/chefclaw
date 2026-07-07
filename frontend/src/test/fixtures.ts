// Canned API shapes for component tests — mirrors the FakeExtractor's default
// bilingual dish (backend/src/chefclaw/extractors/fake.py) so tests exercise
// realistic data: 原文 fields, verbatim raw_text quantities ("适量" included).

import type {
  HealthResponse,
  JobOut,
  RecipeDetail,
  RecipePage,
  RecipeSummary,
  SpendSummaryOut,
} from '../client/types.gen';

export function jobOut(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: 'job-1',
    type: 'extract',
    status: 'pending',
    platform: 'bilibili',
    canonical_id: 'fake-golden-1',
    attempts: 0,
    error_type: null,
    error_detail: null,
    result_recipe_ids: [],
    recipe_ids: [],
    created_at: '2026-07-06T00:00:00Z',
    updated_at: '2026-07-06T00:00:00Z',
    url: 'fake://golden-1',
    ...overrides,
  };
}

export function cannedDocument(): Record<string, unknown> {
  return {
    dish_name: { en: 'Red-braised pork belly', original: '红烧肉' },
    cuisine_type: 'Chinese (Jiangnan)',
    difficulty: 'medium',
    total_time_minutes: 75,
    servings: null,
    ingredients: [
      {
        raw_text: '五花肉500克',
        name: { en: 'pork belly', original: '五花肉' },
        quantity: {
          raw_text: '500克',
          value: 500,
          unit: 'g',
          unit_type: 'mass',
        },
        quantity_grams_stated: 500,
        prep_state: 'raw',
        notes: null,
        nutrition_ref: null,
      },
      {
        raw_text: '盐适量',
        name: { en: 'salt', original: '盐' },
        quantity: {
          raw_text: '适量',
          value: null,
          unit: null,
          unit_type: 'approx',
        },
        quantity_grams_stated: null,
        prep_state: null,
        notes: null,
        nutrition_ref: null,
      },
    ],
    equipment: ['炒锅 (wok)'],
    steps: [
      {
        step_number: 1,
        instruction: 'Blanch the pork belly cubes. 五花肉切块，冷水下锅焯水。',
        duration: null,
        visual_cues: 'Skim until the surface foam is gone.',
        technique_notes: 'Start from cold water so the blood draws out.',
      },
      {
        step_number: 2,
        instruction: 'Simmer covered, then reduce. 小火炖煮收汁。',
        duration: '1小时 (1 hour)',
        visual_cues: null,
        technique_notes: null,
      },
    ],
    tips: ['Skim early; a clean braise keeps the sauce clear.'],
    source: {
      platform: 'bilibili',
      url: 'fake://golden-1',
      creator: 'fake-creator',
      video_duration_seconds: 300,
    },
  };
}

export function recipeSummary(
  overrides: Partial<RecipeSummary> = {},
): RecipeSummary {
  return {
    id: 'r1',
    platform: 'bilibili',
    canonical_id: 'fake-golden-1',
    dish_index: 0,
    title_en: 'Red-braised pork belly',
    title_original: '红烧肉',
    tags: [],
    status: 'stored',
    created_at: '2026-07-06T00:00:00Z',
    // Card projections mirror cannedDocument(); has_image false = the
    // gradient-fallback path, so image tests opt in explicitly.
    has_image: false,
    difficulty: 'medium',
    estimated_spiciness_level: 2,
    estimated_difficulty_level: 1,
    estimated_source: 'derived',
    total_time_minutes: 75,
    ingredient_count: 2,
    ...overrides,
  };
}

export function recipeDetail(
  overrides: Partial<RecipeDetail> = {},
): RecipeDetail {
  return {
    id: 'r1',
    platform: 'bilibili',
    canonical_id: 'fake-golden-1',
    dish_index: 0,
    title_en: 'Red-braised pork belly',
    title_original: '红烧肉',
    tags: [],
    status: 'stored',
    created_at: '2026-07-06T00:00:00Z',
    has_image: false,
    difficulty: 'medium',
    estimated_spiciness_level: 2,
    estimated_difficulty_level: 1,
    estimated_source: 'derived',
    total_time_minutes: 75,
    ingredient_count: 2,
    source_url: 'fake://golden-1',
    user_notes: null,
    document: cannedDocument(),
    extraction_meta: { model_id: 'fake-extractor', prompt_version: 'v1' },
    ...overrides,
  };
}

export function recipePage(items: RecipeSummary[]): RecipePage {
  return { items, total: items.length, limit: 50, offset: 0 };
}

/** A healthy /api/health payload (guest-tier cookie posture, fresh backup). */
export function healthResponse(
  overrides: Partial<HealthResponse> = {},
): HealthResponse {
  return {
    status: 'ok',
    db: 'ok',
    sidecar: 'ok',
    cookie_freshness: 'not_configured',
    cookie_set_date: null,
    backup: 'fresh',
    backup_finished_at: '2026-07-06T03:30:00+00:00',
    extractor: 'gemini',
    model: 'gemini-2.5-flash',
    spend_month_usd: 0.2,
    budget_monthly_usd: 10,
    daily_attempt_cap: 25,
    attempts_today: 1,
    worker: 'alive',
    sentry_enabled: false,
    ...overrides,
  };
}

/** A /api/spend payload: two models on the newest day + one older day. */
export function spendSummary(
  overrides: Partial<SpendSummaryOut> = {},
): SpendSummaryOut {
  return {
    period_days: 30,
    total_usd: 1.25,
    month_to_date_usd: 1.25,
    attempts_today: 3,
    budget_monthly_usd: 10,
    daily_attempt_cap: 25,
    days: [
      {
        date: '2026-07-06',
        cost_usd: 0.4,
        attempts: 3,
        models: [
          {
            model: 'gemini-2.5-flash',
            cost_usd: 0.3,
            attempts: 2,
            tokens_in: 1000,
            tokens_out: 200,
            tokens_thinking: 0,
          },
          {
            model: 'qwen3-vl-plus',
            cost_usd: 0.1,
            attempts: 1,
            tokens_in: 500,
            tokens_out: 100,
            tokens_thinking: 0,
          },
        ],
      },
      {
        date: '2026-07-04',
        cost_usd: 0.85,
        attempts: 4,
        models: [
          {
            model: 'gemini-2.5-flash',
            cost_usd: 0.85,
            attempts: 4,
            tokens_in: 4000,
            tokens_out: 800,
            tokens_thinking: 50,
          },
        ],
      },
    ],
    ...overrides,
  };
}
