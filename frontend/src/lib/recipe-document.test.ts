import { describe, expect, it } from 'vitest';

import { englishQuantity, type QuantityDoc } from './recipe-document';

function quantity(overrides: Partial<QuantityDoc>): QuantityDoc {
  return {
    raw_text: '',
    value: null,
    unit: null,
    unit_type: null,
    ...overrides,
  };
}

describe('englishQuantity', () => {
  it('renders a stated value + unit as English units', () => {
    expect(
      englishQuantity(
        quantity({
          raw_text: '500克',
          value: 500,
          unit: 'g',
          unit_type: 'mass',
        }),
      ),
    ).toBe('500 g');
    expect(
      englishQuantity(
        quantity({
          raw_text: '两大勺',
          value: 2,
          unit: 'tbsp',
          unit_type: 'volume',
        }),
      ),
    ).toBe('2 tbsp');
    expect(
      englishQuantity(
        quantity({
          raw_text: '三个',
          value: 3,
          unit: 'piece',
          unit_type: 'count',
        }),
      ),
    ).toBe('3 piece');
  });

  it('formats fractional values without float noise or trailing zeros', () => {
    expect(
      englishQuantity(quantity({ raw_text: '半杯', value: 0.5, unit: 'cup' })),
    ).toBe('0.5 cup');
    // A float stored as a whole number drops its ".0" (500.0 → "500").
    expect(
      englishQuantity(
        quantity({ raw_text: '250毫升', value: 250.0, unit: 'ml' }),
      ),
    ).toBe('250 ml');
  });

  it('returns null when the source stated no unambiguous value+unit', () => {
    // "适量" / to taste — approx, no number to show in English.
    expect(
      englishQuantity(
        quantity({
          raw_text: '适量',
          value: null,
          unit: null,
          unit_type: 'approx',
        }),
      ),
    ).toBeNull();
    // A value with no unit (or a unit with no value) is not a renderable pair —
    // callers fall back to the verbatim raw_text.
    expect(
      englishQuantity(quantity({ raw_text: '一碗', value: 1, unit: null })),
    ).toBeNull();
    expect(
      englishQuantity(quantity({ raw_text: '少许', value: null, unit: 'g' })),
    ).toBeNull();
  });
});
