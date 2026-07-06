// Canned API shapes for component tests — mirrors the FakeExtractor's default
// bilingual dish (backend/src/chefclaw/extractors/fake.py) so tests exercise
// realistic data: 原文 fields, verbatim raw_text quantities ("适量" included).

import type {
  HealthResponse,
  JobOut,
  RecipeDetail,
  RecipePage,
  RecipeSummary,
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
    ...overrides,
  };
}
