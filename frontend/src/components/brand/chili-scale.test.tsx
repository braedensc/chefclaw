import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ChiliScale } from './chili-scale';

function litCount(container: HTMLElement): number {
  return container.querySelectorAll('[data-lit="true"]').length;
}

describe('ChiliScale', () => {
  it('lights 1 of 3 chilis for easy and shows the word', () => {
    const { container } = render(<ChiliScale difficulty="easy" />);
    expect(container.querySelectorAll('svg')).toHaveLength(3);
    expect(litCount(container)).toBe(1);
    expect(screen.getByText('easy')).toBeInTheDocument();
  });

  it('lights 2 of 3 chilis for medium', () => {
    const { container } = render(<ChiliScale difficulty="medium" />);
    expect(litCount(container)).toBe(2);
    expect(screen.getByText('medium')).toBeInTheDocument();
  });

  it('lights 3 of 3 chilis for hard', () => {
    const { container } = render(<ChiliScale difficulty="hard" />);
    expect(litCount(container)).toBe(3);
    expect(screen.getByText('hard')).toBeInTheDocument();
  });

  it('renders nothing for an unknown difficulty (never fabricate)', () => {
    const { container } = render(<ChiliScale difficulty="超级辣" />);
    expect(container).toBeEmptyDOMElement();
  });
});
