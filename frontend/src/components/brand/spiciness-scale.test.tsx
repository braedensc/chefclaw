import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SpicinessScale } from './spiciness-scale';

function litCount(container: HTMLElement): number {
  return container.querySelectorAll('[data-lit="true"]').length;
}

describe('SpicinessScale', () => {
  it('renders nothing for a null level (never fabricate)', () => {
    const { container } = render(<SpicinessScale level={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for an undefined level', () => {
    const { container } = render(<SpicinessScale level={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    [0, 0, 'not spicy'],
    [1, 1, 'mild'],
    [2, 2, 'medium'],
    [3, 3, 'hot'],
  ])(
    'lights %i of 3 chilis and shows "%s" for level %i',
    (level, expectedLit, word) => {
      const { container } = render(<SpicinessScale level={level} />);
      expect(container.querySelectorAll('svg')).toHaveLength(3);
      expect(litCount(container)).toBe(expectedLit);
      expect(screen.getByText(word)).toBeInTheDocument();
    },
  );

  it('exposes an estimated spiciness aria-label', () => {
    render(<SpicinessScale level={3} />);
    expect(
      screen.getByLabelText('Spiciness: hot (estimated)'),
    ).toBeInTheDocument();
  });
});
