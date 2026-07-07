// Client-side view of the recipes.document JSONB. The document is validated
// strictly server-side (backend/src/chefclaw/documents.py) before it is ever
// stored, so this module does not re-validate — it types the shape and fills
// safe defaults so rendering never crashes on an older/partial document.
// NEVER mutate or "fix" values here: quantities render verbatim (Hard Rule 7).

export interface BilingualText {
  en: string | null;
  original: string | null;
}

export interface QuantityDoc {
  raw_text: string;
  value: number | null;
  unit: string | null;
  unit_type: string | null;
}

// Clean display of a JSON-sourced number: drop float noise and trailing zeros
// (500 → "500", 0.5 → "0.5"). The value comes verbatim from the source's stated
// amount — this only formats it for display, it never rounds or converts.
function formatQuantityValue(value: number): string {
  return Number.parseFloat(value.toFixed(4)).toString();
}

/**
 * The English-unit rendering of a quantity for English mode — e.g. "2 tbsp",
 * "500 g", "3 piece". Returns null when the source did not state an unambiguous
 * value + unit (e.g. "适量", or a "碗" of unknown size); callers fall back to
 * `raw_text` (the verbatim original) in that case.
 *
 * This never derives, estimates, or converts: `value`/`unit` are the
 * extractor's explicit, unambiguous split of a *stated* amount (郫县豆瓣酱两大勺
 * → value 2 / unit "tbsp"), the same faithful translation as `name.en` — not a
 * fabricated number. Hard Rule 7 stays intact.
 */
export function englishQuantity(quantity: QuantityDoc): string | null {
  if (quantity.value == null || quantity.unit == null) {
    return null;
  }
  return `${formatQuantityValue(quantity.value)} ${quantity.unit}`;
}

export interface IngredientDoc {
  raw_text: string;
  name: BilingualText;
  quantity: QuantityDoc | null;
  quantity_grams_stated: number | null;
  prep_state: string | null;
  notes: string | null;
}

export interface StepDoc {
  step_number: number;
  instruction: string;
  duration: string | null;
  visual_cues: string | null;
  technique_notes: string | null;
}

export interface SourceDoc {
  platform: string;
  url: string;
  creator: string | null;
  video_duration_seconds: number | null;
}

export interface RecipeDoc {
  dish_name: BilingualText;
  cuisine_type: string | null;
  difficulty: string | null;
  total_time_minutes: number | null;
  servings: number | null;
  ingredients: IngredientDoc[];
  equipment: string[];
  steps: StepDoc[];
  tips: string[];
  source: SourceDoc | null;
}

/**
 * Narrow the untyped `document: { [key: string]: unknown }` from the generated
 * client into the typed shape, with list/null defaults for anything absent.
 */
export function asRecipeDoc(document: Record<string, unknown>): RecipeDoc {
  const doc = document as Partial<RecipeDoc>;
  return {
    dish_name: doc.dish_name ?? { en: null, original: null },
    cuisine_type: doc.cuisine_type ?? null,
    difficulty: doc.difficulty ?? null,
    total_time_minutes: doc.total_time_minutes ?? null,
    servings: doc.servings ?? null,
    ingredients: doc.ingredients ?? [],
    equipment: doc.equipment ?? [],
    steps: doc.steps ?? [],
    tips: doc.tips ?? [],
    source: doc.source ?? null,
  };
}
