// The mark: two arches and a spore, on moss. `draw` animates it once (the sidebar, the hero).

const ARCHES = ["M12 50V32a10 10 0 0 1 20 0v18", "M32 32a10 10 0 0 1 20 0v18"];

export function Logo({ draw = false }: { draw?: boolean }) {
  const anim = (delay: number) => (draw ? { animation: `mz-draw .9s cubic-bezier(.6,0,.2,1) ${delay}s both` } : undefined);
  return (
    <svg viewBox="0 0 64 64" width="100%" height="100%" aria-hidden="true">
      <rect width="64" height="64" rx="15" className="fill-moss" />
      <svg x="10" y="10" width="44" height="44" viewBox="0 0 64 64" overflow="visible">
        {ARCHES.map((d, i) => (
          <path
            key={d}
            d={d}
            fill="none"
            className="stroke-white"
            strokeWidth="5.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength="100"
            strokeDasharray="100"
            style={anim(0.15 + i * 0.55)}
          />
        ))}
        <circle
          cx="52"
          cy="12"
          r="5"
          className="fill-moss-glow"
          style={{ transformOrigin: "52px 12px", ...(draw ? { animation: "mz-pop .5s ease-out 1.5s both" } : {}) }}
        />
      </svg>
    </svg>
  );
}

/** The same arches, bare, for the dark voice screen. */
export function Arches({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" className={className} overflow="visible">
      {ARCHES.map((d) => (
        <path key={d} d={d} fill="none" className="stroke-on-night" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" opacity={0.95} />
      ))}
      <circle cx="52" cy="12" r="5" className="fill-rpc" />
    </svg>
  );
}
