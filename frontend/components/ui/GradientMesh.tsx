/** Soft blurred-blob backdrop (Sarvam's atmospheric wash, ShopOS's dreamy
 * softness) rendered as real SVG art rather than a flat CSS gradient —
 * gaussian-blurred shapes read as a painted background image, not a
 * mathematical color ramp, and are the concrete answer to "I want
 * images." Fixed behind everything, non-interactive, capped opacity so
 * it stays a backdrop for data-dense cards, never competes with them.
 * `strength="hero"` (login) goes brighter/larger; `"ambient"` (every
 * workspace page) is the quiet default. */
export function GradientMesh({ strength = "ambient" }: { strength?: "ambient" | "hero" }) {
  const hero = strength === "hero";
  return (
    <svg
      className="pointer-events-none fixed inset-0 -z-10 h-full w-full"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <defs>
        <filter id="mesh-blur" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation={hero ? 110 : 90} />
        </filter>
      </defs>
      <g filter="url(#mesh-blur)" opacity={hero ? 0.85 : 0.55}>
        <ellipse cx="8%" cy="0%" rx="26%" ry="34%" fill="var(--wash)" />
        <ellipse cx="88%" cy="4%" rx="22%" ry="26%" fill="var(--accent)" opacity="0.55" />
        {hero && <ellipse cx="45%" cy="85%" rx="24%" ry="22%" fill="var(--wash)" opacity="0.7" />}
      </g>
    </svg>
  );
}
