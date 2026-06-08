type CharacterKind = "cat" | "rabbit" | "fox" | "person";

export function MobileCharacter({
  kind,
  size = 48,
  sleeping = false,
}: {
  kind: CharacterKind;
  size?: number;
  sleeping?: boolean;
}) {
  const ink = "#1a1a1d";
  const Component = {
    cat: CatFace,
    rabbit: RabbitFace,
    fox: FoxFace,
    person: PersonFace,
  }[kind];

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="nb-mobile-character"
      aria-hidden="true"
    >
      <Component ink={ink} sleeping={sleeping} />
    </svg>
  );
}

function Eyes({
  ink,
  sleeping,
  x1 = 26,
  x2 = 38,
  y = 34,
  r = 1.6,
}: {
  ink: string;
  sleeping?: boolean;
  x1?: number;
  x2?: number;
  y?: number;
  r?: number;
}) {
  if (sleeping) {
    return (
      <g stroke={ink} strokeWidth="1.8" fill="none">
        <path d={`M${x1 - 2.6} ${y - 0.5} Q${x1} ${y + 1.8} ${x1 + 2.6} ${y - 0.5}`} />
        <path d={`M${x2 - 2.6} ${y - 0.5} Q${x2} ${y + 1.8} ${x2 + 2.6} ${y - 0.5}`} />
      </g>
    );
  }
  return (
    <g fill={ink} stroke="none">
      <circle cx={x1} cy={y} r={r} />
      <circle cx={x2} cy={y} r={r} />
    </g>
  );
}

function Smile({ ink, x = 32, y = 40, w = 2.4 }: { ink: string; x?: number; y?: number; w?: number }) {
  return <path d={`M${x - w} ${y} Q${x} ${y + 1.8} ${x + w} ${y}`} stroke={ink} strokeWidth="1.6" fill="none" />;
}

function strokeProps(ink: string, width = 1.8) {
  return { stroke: ink, strokeWidth: width, fill: "none" };
}

function PersonFace({ ink, sleeping }: { ink: string; sleeping?: boolean }) {
  const s = strokeProps(ink);
  return (
    <g>
      <circle cx="32" cy="34" r="18" {...s} />
      <path d="M16 30 Q18 17 32 16 Q46 17 48 30" {...s} />
      <path d="M30 16 Q33 13 36 16" {...s} />
      <Eyes ink={ink} sleeping={sleeping} x1={27} x2={37} y={34} />
      <circle cx="22" cy="39" r="1" fill={ink} opacity="0.25" />
      <circle cx="42" cy="39" r="1" fill={ink} opacity="0.25" />
      <Smile ink={ink} x={32} y={40} w={2.2} />
    </g>
  );
}

function CatFace({ ink, sleeping }: { ink: string; sleeping?: boolean }) {
  const s = strokeProps(ink);
  return (
    <g>
      <path d="M19 22 L22 12 L28 20" {...s} />
      <path d="M45 22 L42 12 L36 20" {...s} />
      <path d="M28 20 Q14 22 14 36 Q14 52 32 52 Q50 52 50 36 Q50 22 36 20" {...s} />
      <Eyes ink={ink} sleeping={sleeping} />
      <path d="M30.5 39 L33.5 39 L32 41 Z" fill={ink} stroke="none" />
      <path d="M32 41 Q30 43 28.5 42 M32 41 Q34 43 35.5 42" {...s} strokeWidth="1.4" />
      <g {...s} strokeWidth="1" opacity="0.55">
        <path d="M22 41 L17 40" />
        <path d="M22 43 L17 44" />
        <path d="M42 41 L47 40" />
        <path d="M42 43 L47 44" />
      </g>
    </g>
  );
}

function RabbitFace({ ink, sleeping }: { ink: string; sleeping?: boolean }) {
  const s = strokeProps(ink);
  return (
    <g>
      <path d="M25 22 Q22 14 24 6 Q28 6 28 18" {...s} />
      <path d="M39 22 Q42 14 40 6 Q36 6 36 18" {...s} />
      <path d="M25 18 Q24 12 25 8" {...s} strokeWidth="1.2" opacity="0.5" />
      <path d="M39 18 Q40 12 39 8" {...s} strokeWidth="1.2" opacity="0.5" />
      <circle cx="32" cy="38" r="16" {...s} />
      <Eyes ink={ink} sleeping={sleeping} x1={26} x2={38} y={36} />
      <path d="M32 41 L32 43 M31 41 L33 41" {...s} strokeWidth="1.4" />
      <Smile ink={ink} x={32} y={44} w={2.2} />
      <circle cx="21" cy="40" r="1.2" fill={ink} opacity="0.22" />
      <circle cx="43" cy="40" r="1.2" fill={ink} opacity="0.22" />
    </g>
  );
}

function FoxFace({ ink, sleeping }: { ink: string; sleeping?: boolean }) {
  const s = strokeProps(ink);
  return (
    <g>
      <path d="M17 26 L19 12 L27 22" {...s} />
      <path d="M47 26 L45 12 L37 22" {...s} />
      <path d="M27 22 Q15 24 15 36 Q15 46 23 50 Q28 52 32 48 Q36 52 41 50 Q49 46 49 36 Q49 24 37 22" {...s} />
      <path d="M21 18 L23 22" {...s} strokeWidth="1.2" opacity="0.5" />
      <path d="M43 18 L41 22" {...s} strokeWidth="1.2" opacity="0.5" />
      <Eyes ink={ink} sleeping={sleeping} />
      <ellipse cx="32" cy="41" rx="1.6" ry="1.2" fill={ink} stroke="none" />
      <path d="M32 42 L32 44 M32 44 Q30 45.5 28.5 45 M32 44 Q34 45.5 35.5 45" {...s} strokeWidth="1.4" />
    </g>
  );
}
