// The rising-steam trio — one shared drawing for the jobs drawer's simmer
// accent, the job chip's pot, and the cover fallback art. Animation rides the
// .steam-wisp classes (src/index.css), which are reduced-motion-guarded.
//
// Renders an SVG <g> (not a full <svg>) so hosts embed it in their own
// viewBox coordinate space; the trio is drawn at x 20–44 / y 7–22 (the job
// chip's 64-unit space) and `transform` places/scales it elsewhere.

export interface SteamWispsProps {
  /** SVG transform placing/sizing the trio in the host's viewBox space. */
  transform?: string;
  /** Stroke color; 'currentColor' lets the host's text-* class drive it. */
  stroke?: string;
  /** Stroke width in the host's viewBox units. */
  strokeWidth?: number;
  /** Per-wisp opacity, left to right; omit to render fully opaque. */
  opacities?: [number, number, number];
}

export function SteamWisps({
  transform,
  stroke = '#f4e9d4',
  strokeWidth = 2.4,
  opacities,
}: SteamWispsProps) {
  return (
    <g
      stroke={stroke}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      fill="none"
      transform={transform}
    >
      <path
        className="steam-wisp"
        d="M22 22 C20 18 24 15 22 10"
        opacity={opacities?.[0]}
      />
      <path
        className="steam-wisp steam-wisp-2"
        d="M32 20 C30 16 34 13 32 7"
        opacity={opacities?.[1]}
      />
      <path
        className="steam-wisp steam-wisp-3"
        d="M42 22 C40 18 44 15 42 10"
        opacity={opacities?.[2]}
      />
    </g>
  );
}
