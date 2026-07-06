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
