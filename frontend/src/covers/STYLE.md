# chefclaw dish-sprite style (neon night-market) — locked 2026-07-07

NEON NIGHT-MARKET DISH-SPRITE STYLE SPEC (self-contained — reproduce without the reference)

PURPOSE
Every sprite is a default recipe-card cover: a single centered dish motif in a 夜市-at-midnight (night-market) aesthetic — black pavement, lit neon tubes, a sizzling wok/plate. Original authored art only; never traced from photos. One sprite = one <svg> file, self-contained (xmlns present, no external refs, no <script>, no <use> pointing outside the file).

CANVAS / VIEWBOX (SHARED CONVENTION — all sprites identical)
- viewBox="0 0 320 200" (landscape 16:10, matches the .nn-cover aspect-ratio 16/10).
- Root attrs verbatim: xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200" preserveAspectRatio="xMidYMid slice" aria-hidden="true".
- The whole 320×200 is painted (full-bleed background rect); the card applies its own legibility gradient + neon spill on top via CSS, so leave the bottom ~30% able to be darkened by a gradient (keep the dish motif roughly centered/upper-centered, nothing critical below y≈160).

BACKGROUND / TILE TREATMENT
- NOT transparent. Each sprite opens with <rect width="320" height="200" fill="url(#<id>bg)"/>.
- The bg is a radialGradient anchored top-right: cx="85%" cy="-5%" r="100%" with 3 stops — a dim cuisine-tinted glow at the top-right corner (offset 0%), fading through near-black (offset 45% ≈ #0b090a) to true black (offset 100% ≈ #060506). The corner-glow hue is chosen per dish family: teal/cyan (#123138, #113036, #102e35) for savory/Sichuan/braise, warm rose (#3a1120, #38101e) for tomato/sweet/rednote dishes, amber (#332818) for noodle/oil dishes. Keep it SUBTLE — this is ambient neon spill, not a spotlight.
- No rounded tile inside the SVG; the card element provides the 12px radius + border + glow. Sprites are rectangular full-bleed art.

PALETTE (exact hex — the locked night-market tokens)
Base:   #050505 base black · #060506 canvas floor · #0b0b0d panel · #0d0d10 pan-body.
Neon accents: #ff2d55 chili neon · #ff4d6d chili bright · #35e0ff electric cyan · #ffd60a signage gold · #b478ff violet wash · #ffe9c9 warm white.
Food browns/reds (braise family): #6b4029→#3d2113→#1c0d06 (pot), #9c2b10→#661408→#3b0b05 (braising liquid), #cf5226→#82200e (glazed skin), #f6ddb2→#d8b47f (fat layer), #5e2410/#7c3a20/#6b2f16 (meat strata).
Chili-oil red (Sichuan): #ef5520→#b02408→#7a1305.
Tofu/egg cream: #f9f2df→#e3cda4 (tofu), #ffeaa6→#f6ac25 (egg), #fff3c8 (egg highlight).
Tomato: #ff7350→#dd3320 (flesh), #c31f12 (skin edge), #ff9d7d (inner wall), #ffd9a2 (seed pockets).
Aubergine: #5c2c52→#7a3a4e→#96502a (fish-fragrant eggplant baton).
Noodles: #d9bd85 / #e6cf9d / #cdb078 base strands, #fff1c9 highlight strand, #7a4c14 / #8a5a1e shadow strand.
Garnish greens: #58c14a / #5ecb4e / #6abf5a fresh scallion, #2f7d2b / #3f9c37 dark scallion, crispy-shallot #6b5420 / #4d3b17.
Aromatics: #f2ddb0 minced garlic dots, #e0341f diced red chili, #260903 black peppercorn, #f8eed6 sesame.
Glaze/wing browns: #c17232→#94481a→#6e2f0d.
Rule: neon color is used as GLOW and thin accent strokes (the cyan/rose steam-lick arcs, corner spill), NEVER as a flat fill of the food itself. Food is rendered in appetizing naturalistic warm tones; the "neon" reads through the dark base, the corner glow, one cyan/rose steam arc, and the card's CSS halo.

STROKE WIDTHS
- Food outlines / cube borders: 1.2–1.6px hairline, low-opacity dark (#240a03 @ .55, #a3300f @ .4).
- Neon steam-lick accent arc: 2.5px, the cuisine neon (#35e0ff for cyan families, #ff4d6d for rose families, #ffe9c9 for warm/local), opacity .35–.45, stroke-linecap round — ONE per sprite, sweeping from lower-left up toward upper-center behind the food.
- Rising-steam wisps (top): stroke #fff, 6–7px, opacity .08–.10, filter="url(#nnBlur3)" — 1–2 soft blurred vertical S-curves above the dish.
- Noodle strands: 6–7px body strands + a 2px #fff1c9 highlight and a 2–2.4px dark shadow strand for depth; stroke-linecap round; fill none.
- Chopsticks: 5px, warm wood (#b98a4e / #a67a40).
- Garnish flecks (scallion/chili/shallot): tiny rounded rects ~5–7px long × 2.4–3.4px, rx≈1.3, rotated random angles.

COMPOSITION RULES (single centered dish motif)
1. One dish, centered horizontally around x=160, sitting on a vessel. Vessel is an ellipse "plate/wok/pan" (cx≈160, cy≈114–140) OR a curved-wall pot silhouette. Under it: a soft cast shadow ellipse (cx160, cy≈184–190, rx≈150–160, ry≈20–24, fill #000 opacity .5).
2. Vessel = dark ring: outer ellipse fill #0d0d10–#1a1420 + a 2.5–3px rim stroke (#26262e / #2c2136 / #271b22) + an inner darker ellipse; then the food/sauce pooled inside.
3. Food = 4–8 repeated hero units (pork cubes, tofu cubes, eggplant batons, egg curds, wings, tomato wedges) scattered with slight per-unit rotate(-10..+14) and translate offsets to feel tossed/piled, front units larger/brighter than back units (scale .82 for back layer). Each unit gets a small warm highlight ellipse/dot (#fff or #ffc491 @ .4–.9) for gloss.
4. Garnish pass on top: scattered scallion/chili/garlic/sesame flecks + 1–3 tiny white gloss dots (#fff opacity .5–.65) to make it look oily/fresh.
5. Depth order back-to-front: bg rect → cast shadow → blurred steam wisps → vessel → neon steam arc → sauce pool → back food units → front food units → sauce laps/drizzle → garnish → gloss dots.
6. Motif fills roughly the central 60–70% width; generous black margin left/right on purpose (the glow does the softening). Keep it readable at ~310px card width AND legible when the card's bottom-darkening gradient covers y>140.

COMPLEXITY LEVEL
Medium-detailed flat vector illustration — richer than a pictogram, simpler than realism. ~40–120 elements per sprite: a handful of gradients in <defs>, one full-bleed bg, a vessel, 4–8 repeated food units each with 3–6 sub-shapes, and a garnish/gloss sprinkle. Depth comes from layered gradients + per-unit highlights + one blurred steam wisp, NOT from complex filters. Hand-authored paths; no auto-traced noise.

GRADIENT SET (per sprite, id-prefixed to stay unique across inlined SVGs)
Give every gradient/filter an id prefixed with the sprite's short code (e.g. a1*, a2*…) so multiple sprites can coexist inline without id collisions. Typical set: one radial bg, one linear/radial for the sauce or braising liquid, one linear for the hero food (skin/tofu/egg/wing), optionally one for the fat/inner layers.

THE NEON GLOW TECHNIQUE (reusable — inline these defs)
Two mechanisms, layered:
(A) Soft blur for steam and mascot tubes — inline this filter in any sprite that uses blurred steam wisps:
  <filter id="nnBlur3" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="3"/></filter>
  Apply as filter="url(#nnBlur3)" on low-opacity white steam strokes.
(B) The full neon-tube halo (used for line-art motifs like the mascot / signage glyphs, if a sprite is pure neon outline rather than filled food) — inline this filter and stroke the art with it:
  <filter id="nnNeon" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur in="SourceGraphic" stdDeviation="2" result="b1"/><feGaussianBlur in="SourceGraphic" stdDeviation="6" result="b2"/><feMerge><feMergeNode in="b2"/><feMergeNode in="b1"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  Technique: draw open paths (fill none, round caps/joins) in a vivid neon hex, wrap them in <g filter="url(#nnNeon)"> — the stacked 2px+6px gaussian blurs merged under the crisp source line read as a glowing tube. Use this for neon-line sprites; use naturalistic filled food + corner-glow bg for photographic-style dish sprites (the majority). Most dish sprites rely on the CSS card halo (box-shadow/text-shadow) + the bg corner glow + the cyan/rose steam arc for their neon feel, and only need nnBlur3.
IMPORTANT: if a sprite does NOT use a given filter/gradient, do not declare it (keep files lean). Every id referenced must be defined in the same file (self-contained).

TYPE / TEXT
Sprites carry NO text — titles are HTML overlaid by the card. Do not bake dish names into the SVG.

ACCESSIBILITY / SAFETY
aria-hidden="true" on root (decorative; the card supplies the accessible name). No <script>, no external hrefs, no <image>, no remote fonts. All color literal hex or local url(#id).
