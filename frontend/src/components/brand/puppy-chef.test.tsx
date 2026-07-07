import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PuppyChef } from './puppy-chef';

describe('PuppyChef', () => {
  it('is decorative (aria-hidden) by default', () => {
    const { container } = render(<PuppyChef />);
    const svg = container.querySelector('svg');
    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('exposes an accessible name when label is given', () => {
    render(<PuppyChef label="chefclaw puppy chef mascot" />);
    expect(
      screen.getByRole('img', { name: 'chefclaw puppy chef mascot' }),
    ).toBeInTheDocument();
  });

  it('renders the hero variant at the requested size', () => {
    const { container } = render(<PuppyChef variant="hero" size={200} />);
    const svg = container.querySelector('svg');
    expect(svg).toHaveAttribute('data-variant', 'hero');
    expect(svg).toHaveAttribute('width', '200');
  });

  it('only animates the hero when asked, via the reduced-motion-guarded neon flicker', () => {
    const { container: still } = render(<PuppyChef variant="hero" />);
    expect(still.querySelector('.neon-flicker')).toBeNull();

    const { container: moving } = render(<PuppyChef variant="hero" animated />);
    expect(moving.querySelector('.neon-flicker')).not.toBeNull();
  });

  it('renders the mark variant as the full pup (224:200 aspect)', () => {
    const { container } = render(<PuppyChef variant="mark" size={32} />);
    const svg = container.querySelector('svg');
    expect(svg).toHaveAttribute('data-variant', 'mark');
    expect(svg).toHaveAttribute('width', '32');
    expect(svg).toHaveAttribute('height', String((32 * 200) / 224));
  });

  it('renders the sleeping variant', () => {
    const { container } = render(<PuppyChef variant="sleeping" />);
    expect(container.querySelector('svg')).toHaveAttribute(
      'data-variant',
      'sleeping',
    );
    // the z z nap glyphs are part of the pose
    expect(container.querySelectorAll('text')).toHaveLength(2);
  });
});
