/** Soft blurred-blob backdrop — a genuinely faint atmospheric glow, not a
 * colored background. Matches talyntlabs.com's own restraint: its hero
 * uses exactly one such glow, at 7% opacity, contained to one corner
 * (`bg-signal/[0.07] blur-[140px]`) — not a saturated wash spanning the
 * whole viewport. A vivid, highly-saturated accent (signal orange) reads
 * as a color bleed at the opacities that worked for the prior pastel
 * lavender --wash, so this is tuned down accordingly: real backdrop for
 * data-dense cards, never competing with them, never confusable with a
 * status/action color. `strength="hero"` (login) goes slightly
 * brighter/larger; `"ambient"` (every workspace page) is the quiet
 * default. */
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
      <g filter="url(#mesh-blur)" opacity={hero ? 0.45 : 0.3}>
        <ellipse cx="8%" cy="0%" rx="26%" ry="34%" fill="var(--wash)" />
        <ellipse cx="88%" cy="4%" rx="22%" ry="26%" fill="var(--accent)" opacity="0.25" />
        {hero && <ellipse cx="45%" cy="85%" rx="24%" ry="22%" fill="var(--wash)" opacity="0.7" />}
      </g>
    </svg>
  );
}
