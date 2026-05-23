// Cute hand-drawn (简笔画) style Bro characters: cat, rabbit, fox, person.
// Style: thin pen strokes, no heavy fills, round friendly shapes,
// dot eyes and a tiny curved smile. Slightly off-center curves give
// a hand-drawn feel without looking sloppy.

function Character({ kind, size = 48, sleeping = false, working = false }) {
  const ink = '#1a1a1d';
  const props = { ink, sleeping, working };
  const Comp = ({
    cat: CatFace,
    rabbit: RabbitFace,
    fox: FoxFace,
    person: PersonFace,
  })[kind] || CatFace;
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none"
      strokeLinecap="round" strokeLinejoin="round"
      style={{ display: 'block', overflow: 'visible' }}>
      <Comp {...props}/>
    </svg>
  );
}

// Eyes — two filled dots, or sleepy little arcs.
function Eyes({ ink, sleeping, x1 = 26, x2 = 38, y = 34, r = 1.6 }) {
  if (sleeping) {
    return (
      <g stroke={ink} strokeWidth="1.8" fill="none">
        <path d={`M${x1-2.6} ${y-0.5} Q${x1} ${y+1.8} ${x1+2.6} ${y-0.5}`}/>
        <path d={`M${x2-2.6} ${y-0.5} Q${x2} ${y+1.8} ${x2+2.6} ${y-0.5}`}/>
      </g>
    );
  }
  return (
    <g fill={ink} stroke="none">
      <circle cx={x1} cy={y} r={r}/>
      <circle cx={x2} cy={y} r={r}/>
    </g>
  );
}

// Tiny smile
function Smile({ ink, x = 32, y = 40, w = 2.4 }) {
  return (
    <path d={`M${x-w} ${y} Q${x} ${y+1.8} ${x+w} ${y}`}
      stroke={ink} strokeWidth="1.6" fill="none"/>
  );
}

// Shared stroke props for the outlines
function strokeProps(ink, w = 1.8) {
  return { stroke: ink, strokeWidth: w, fill: 'none' };
}

// ─── PERSON — round face, little hair tuft ──────────────────
function PersonFace({ ink, sleeping }) {
  const s = strokeProps(ink, 1.8);
  return (
    <g>
      {/* round head */}
      <circle cx="32" cy="34" r="18" {...s}/>
      {/* hair — soft cap on top */}
      <path d="M16 30 Q18 17 32 16 Q46 17 48 30" {...s}/>
      {/* little hair tuft */}
      <path d="M30 16 Q33 13 36 16" {...s}/>
      <Eyes ink={ink} sleeping={sleeping} x1={27} x2={37} y={34} r={1.6}/>
      {/* cheeks — tiny dots */}
      <circle cx="22" cy="39" r="1" fill={ink} opacity="0.25"/>
      <circle cx="42" cy="39" r="1" fill={ink} opacity="0.25"/>
      <Smile ink={ink} x={32} y={40} w={2.2}/>
    </g>
  );
}

// ─── CAT — round head with two pointy ears ─────────────────
function CatFace({ ink, sleeping }) {
  const s = strokeProps(ink, 1.8);
  return (
    <g>
      {/* ears (drawn as part of the head outline) */}
      <path d="M19 22 L22 12 L28 20" {...s}/>
      <path d="M45 22 L42 12 L36 20" {...s}/>
      {/* head */}
      <path d="M28 20 Q14 22 14 36 Q14 52 32 52 Q50 52 50 36 Q50 22 36 20" {...s}/>
      <Eyes ink={ink} sleeping={sleeping} x1={26} x2={38} y={34} r={1.6}/>
      {/* nose — tiny triangle */}
      <path d="M30.5 39 L33.5 39 L32 41 Z" fill={ink} stroke="none"/>
      {/* mouth — little w */}
      <path d="M32 41 Q30 43 28.5 42 M32 41 Q34 43 35.5 42" {...s} strokeWidth="1.4"/>
      {/* whiskers */}
      <g {...s} strokeWidth="1" opacity="0.55">
        <path d="M22 41 L17 40"/>
        <path d="M22 43 L17 44"/>
        <path d="M42 41 L47 40"/>
        <path d="M42 43 L47 44"/>
      </g>
    </g>
  );
}

// ─── RABBIT — round head, long floppy ears ─────────────────
function RabbitFace({ ink, sleeping }) {
  const s = strokeProps(ink, 1.8);
  return (
    <g>
      {/* long ears */}
      <path d="M25 22 Q22 14 24 6 Q28 6 28 18" {...s}/>
      <path d="M39 22 Q42 14 40 6 Q36 6 36 18" {...s}/>
      {/* inner ear lines */}
      <path d="M25 18 Q24 12 25 8" {...s} strokeWidth="1.2" opacity="0.5"/>
      <path d="M39 18 Q40 12 39 8" {...s} strokeWidth="1.2" opacity="0.5"/>
      {/* head */}
      <circle cx="32" cy="38" r="16" {...s}/>
      <Eyes ink={ink} sleeping={sleeping} x1={26} x2={38} y={36} r={1.6}/>
      {/* nose — small Y */}
      <path d="M32 41 L32 43 M31 41 L33 41" {...s} strokeWidth="1.4"/>
      <Smile ink={ink} x={32} y={44} w={2.2}/>
      {/* cheek blush */}
      <circle cx="21" cy="40" r="1.2" fill={ink} opacity="0.22"/>
      <circle cx="43" cy="40" r="1.2" fill={ink} opacity="0.22"/>
    </g>
  );
}

// ─── FOX — round head with pointed ears ────────────────────
function FoxFace({ ink, sleeping }) {
  const s = strokeProps(ink, 1.8);
  return (
    <g>
      {/* ears as part of head outline */}
      <path d="M17 26 L19 12 L27 22" {...s}/>
      <path d="M47 26 L45 12 L37 22" {...s}/>
      {/* head with little snout */}
      <path d="M27 22 Q15 24 15 36 Q15 46 23 50 Q28 52 32 48 Q36 52 41 50 Q49 46 49 36 Q49 24 37 22" {...s}/>
      {/* inner ear marks */}
      <path d="M21 18 L23 22" {...s} strokeWidth="1.2" opacity="0.5"/>
      <path d="M43 18 L41 22" {...s} strokeWidth="1.2" opacity="0.5"/>
      <Eyes ink={ink} sleeping={sleeping} x1={26} x2={38} y={34} r={1.6}/>
      {/* fox nose */}
      <ellipse cx="32" cy="41" rx="1.6" ry="1.2" fill={ink} stroke="none"/>
      {/* mouth */}
      <path d="M32 42 L32 44 M32 44 Q30 45.5 28.5 45 M32 44 Q34 45.5 35.5 45" {...s} strokeWidth="1.4"/>
    </g>
  );
}
