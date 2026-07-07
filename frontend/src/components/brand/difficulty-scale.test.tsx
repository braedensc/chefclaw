import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DifficultyScale } from './difficulty-scale';

function filledCount(container: HTMLElement): number {
  return container.querySelectorAll('[data-filled="true"]').length;
}

describe('DifficultyScale', () => {
  it('renders nothing for a null level (never fabricate)', () => {
    const { container } = render(<DifficultyScale level={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for an undefined level', () => {
    const { container } = render(<DifficultyScale level={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    [0, 0, 'very easy'],
    [1, 1, 'easy'],
    [2, 2, 'medium'],
    [3, 3, 'hard'],
  ])(
    'fills %i of 3 bars and shows "%s" for level %i',
    (level, expectedFilled, word) => {
      const { container } = render(<DifficultyScale level={level} />);
      // Always a 3-segment meter, distinct from the chili scale.
      expect(container.querySelectorAll('rect')).toHaveLength(3);
      expect(filledCount(container)).toBe(expectedFilled);
      expect(screen.getByText(word)).toBeInTheDocument();
    },
  );

  it('exposes an estimated difficulty aria-label', () => {
    render(<DifficultyScale level={3} />);
    expect(
      screen.getByLabelText('Difficulty: hard (estimated)'),
    ).toBeInTheDocument();
  });
});
