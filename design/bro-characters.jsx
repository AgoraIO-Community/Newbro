/* bro-characters.jsx — per-bro character glyphs + a BroAvatar wrapper.
 *
 * Used everywhere a bro avatar appears so each bro has personality.
 * Four character kinds (rabbit / cat / fox / person), drawn in a simple
 * hand-drawn (简笔画) line style. Each character has expressive eyes
 * (open / closed for sleep / squint for work).
 *
 * Avatar wrapper handles:
 *   - sleep mode: closed eyes + zzz puffs
 *   - work mode:  open eyes + breathing halo + tiny ear-twitch
 *   - offline:    grayscale, eyes closed
 *   - newbro:     the dispatcher glyph (clipboard with antenna)
 *
 * Renders inline SVG so we can size + tint via CSS.
 */

// ─── Character primitives ──────────────────────────────────────────
// All draw inside a 64×64 viewBox. The body is anchored low so the head
// shows up well even at small sizes.

function CRabbit({ asleep, working }) {
  const eyeY = 28;
  return (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {/* ears */}
      <path d="M22 22 L20 8 L25 18" />
      <path d="M34 22 L36 8 L31 18" transform={working ? "rotate(8 36 8)" : ""} />
      {/* head */}
      <ellipse cx="28" cy="34" rx="14" ry="13" />
      {/* eyes */}
      {asleep ? (
        <>
          <path d="M21 28 q2 2 4 0" />
          <path d="M31 28 q2 2 4 0" />
        </>
      ) : working ? (
        <>
          <path d={`M21 ${eyeY} q2 -1 4 0`} />
          <path d={`M31 ${eyeY} q2 -1 4 0`} />
        </>
      ) : (
        <>
          <circle cx="23" cy={eyeY} r="1.5" fill="currentColor" />
          <circle cx="33" cy={eyeY} r="1.5" fill="currentColor" />
        </>
      )}
      {/* nose + whiskers */}
      <path d="M28 36 l-1.5 2 h3 z" fill="currentColor" stroke="none" />
      <path d="M21 38 l-3 0" opacity="0.6" />
      <path d="M35 38 l3 0" opacity="0.6" />
      {/* body / paws hint */}
      <path d="M18 48 q10 6 20 0" />
    </g>
  );
}

function CCat({ asleep, working }) {
  const eyeY = 30;
  return (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {/* ears */}
      <path d="M16 20 L20 10 L24 22 Z" />
      <path d="M40 20 L36 10 L32 22 Z" />
      {/* head */}
      <ellipse cx="28" cy="34" rx="15" ry="12" />
      {/* eyes */}
      {asleep ? (
        <>
          <path d="M21 30 q2 2 5 0" />
          <path d="M31 30 q2 2 5 0" />
        </>
      ) : working ? (
        <>
          {/* squint */}
          <path d={`M21 ${eyeY} q2 -2 5 0`} />
          <path d={`M31 ${eyeY} q2 -2 5 0`} />
        </>
      ) : (
        <>
          <ellipse cx="23" cy={eyeY} rx="1.5" ry="2.4" fill="currentColor" />
          <ellipse cx="33" cy={eyeY} rx="1.5" ry="2.4" fill="currentColor" />
        </>
      )}
      {/* nose + mouth */}
      <path d="M28 36 l-1.5 2 h3 z" fill="currentColor" stroke="none" />
      <path d="M28 38 q-2 2 -3 1" />
      <path d="M28 38 q2 2 3 1" />
      {/* whiskers */}
      <path d="M20 36 l-4 -1" opacity="0.6" />
      <path d="M36 36 l4 -1" opacity="0.6" />
      <path d="M20 38 l-4 1" opacity="0.6" />
      <path d="M36 38 l4 1" opacity="0.6" />
      {/* tail */}
      <path d="M42 44 q4 -1 4 -5" />
    </g>
  );
}

function CFox({ asleep, working }) {
  const eyeY = 30;
  return (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {/* ears (triangular, set wide) */}
      <path d="M14 22 L18 8 L24 22 Z" />
      <path d="M42 22 L38 8 L32 22 Z" />
      {/* head — fox snout sharper */}
      <path d="M14 30 q0 -8 14 -10 q14 2 14 10 q0 14 -14 16 q-14 -2 -14 -16 Z" />
      {/* eyes */}
      {asleep ? (
        <>
          <path d="M21 30 q2 2 5 0" />
          <path d="M31 30 q2 2 5 0" />
        </>
      ) : working ? (
        <>
          <path d={`M21 ${eyeY} q2 -1 5 0`} />
          <path d={`M31 ${eyeY} q2 -1 5 0`} />
        </>
      ) : (
        <>
          <circle cx="23" cy={eyeY} r="1.5" fill="currentColor" />
          <circle cx="33" cy={eyeY} r="1.5" fill="currentColor" />
        </>
      )}
      {/* snout / nose */}
      <path d="M28 38 l-2 3 h4 z" fill="currentColor" stroke="none" />
      <path d="M28 41 v3" />
    </g>
  );
}

function CPerson({ asleep, working }) {
  const eyeY = 28;
  return (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {/* hair tuft */}
      <path d="M19 18 q2 -5 9 -5 q7 0 9 5" />
      {/* head */}
      <circle cx="28" cy="30" r="13" />
      {/* eyes */}
      {asleep ? (
        <>
          <path d="M22 28 q2 2 4 0" />
          <path d="M30 28 q2 2 4 0" />
        </>
      ) : working ? (
        <>
          <path d={`M22 ${eyeY} q2 -1 4 0`} />
          <path d={`M30 ${eyeY} q2 -1 4 0`} />
        </>
      ) : (
        <>
          <circle cx="24" cy={eyeY} r="1.5" fill="currentColor" />
          <circle cx="32" cy={eyeY} r="1.5" fill="currentColor" />
        </>
      )}
      {/* nose hint + mouth */}
      <path d="M28 32 l0 3" opacity="0.6" />
      <path d="M25 38 q3 2 6 0" />
      {/* shoulders */}
      <path d="M14 52 q4 -8 14 -8 q10 0 14 8" />
    </g>
  );
}

// NewBro router glyph — small clipboard with an antenna on top.
function CNewBro() {
  return (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M28 8 L28 14" />
      <path d="M32 10 L34 8" opacity="0.7" />
      <path d="M32 14 L34 16" opacity="0.7" />
      <rect x="18" y="14" width="22" height="34" rx="3.5" />
      <path d="M22 21 L36 21" />
      <path d="M22 25 L34 25" />
      <rect x="22" y="30" width="14" height="8" rx="1.5" />
      <circle cx="29" cy="43" r="2" fill="currentColor" stroke="none" />
    </g>
  );
}

const CHARS = {
  rabbit: CRabbit,
  cat:    CCat,
  fox:    CFox,
  person: CPerson,
  newbro: CNewBro,
};

// ─── Avatar wrapper ────────────────────────────────────────────────
// state: 'working' | 'idle' | 'offline' | null (just renders the char)
// Renders the SVG plus optional sleep zzz + working halo decoration.
function BroAvatar({ character = "person", state = null, size = 48, tone = "ink" }) {
  const Char = CHARS[character] || CHARS.person;
  const asleep  = state === "idle" || state === "offline";
  const working = state === "working";
  const isRouter = character === "newbro";

  const colorMap = {
    ink:    "var(--nb-ink)",
    soft:   "var(--nb-ink-soft)",
    coral:  "var(--nb-coral)",
    warn:   "var(--nb-warn-ink)",
    invert: "white",
  };
  const color = colorMap[tone] || tone;

  return (
    <span
      className={`bro-av bro-av-${character}${asleep ? " bro-av-asleep" : ""}${working ? " bro-av-working" : ""}${state === "offline" ? " bro-av-offline" : ""}`}
      style={{ width: size, height: size, color }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 64 64" width={size} height={size}>
        <Char asleep={asleep} working={working} />
      </svg>

      {asleep && !isRouter && (
        <span className="bro-av-zzz" aria-hidden="true">
          <i style={{ fontSize: Math.max(8, size * 0.18) }}>z</i>
          <i style={{ fontSize: Math.max(10, size * 0.22) }}>z</i>
        </span>
      )}
      {working && !isRouter && (
        <span className="bro-av-halo" aria-hidden="true" />
      )}
    </span>
  );
}

window.BroAvatar = BroAvatar;
window.BRO_CHARACTERS = ["rabbit", "cat", "fox", "person"];
