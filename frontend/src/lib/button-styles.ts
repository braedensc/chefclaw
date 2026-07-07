// Shared action-button class strings — the settings-page variants are
// canonical; library-page's recovery/CTA buttons compose these with their
// own margins (and the empty-state CTA adds its glow-chili halo).

// `tap-target` gives both a ≥44px hit area on touch devices (V2-C); the desktop
// mouse UI is a fine pointer and stays the compact caps button.

/** Chili primary action — the neon-tube button for the loud recovery path. */
export const CHILI_BTN =
  'tap-target rounded-field border border-chili/70 bg-chili/10 px-3 py-1.5 font-display text-xs font-bold uppercase tracking-[0.14em] text-chili-bright glow-text-chili transition-colors hover:bg-chili/20';

/** Cyan ghost action — the quiet retry affordance. */
export const CYAN_BTN =
  'tap-target rounded-field border border-cyan/50 px-3 py-1.5 font-display text-xs font-semibold uppercase tracking-[0.14em] text-cyan transition-colors hover:bg-cyan/10 hover:glow-text-cyan';
