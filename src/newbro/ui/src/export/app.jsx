// NewBro Walkie — main React app.
//
// Plain React (no build step needed — loaded via Babel-in-browser from
// index.html). For production, port to your build toolchain and switch
// `React.useState` etc. to named imports.

const { useState, useRef, useEffect } = React;

// ─── Theme ─────────────────────────────────────────────────────────
// Single source of truth for the accent color. Change this (or wire it
// up to a context / settings store) to re-skin the app.
const ACCENT = '#ff6a45';

// Build a 8%-alpha tint of the accent for soft backgrounds.
function applyAccent(hex) {
  document.documentElement.style.setProperty('--coral', hex);
  document.documentElement.style.setProperty('--coral-soft', hex + '14');
}

// ─── primitives ────────────────────────────────────────────────────

function CleanPhone({ children }) {
  return (
    <div style={{
      width: 390, height: 820,
      border: '1px solid var(--hairline)',
      borderRadius: 44,
      background: 'var(--bg)',
      overflow: 'hidden',
      position: 'relative',
      boxShadow: '0 30px 70px -22px rgba(16,17,20,0.22), 0 6px 14px -6px rgba(16,17,20,0.06)',
      display: 'flex', flexDirection: 'column',
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '16px 28px 4px', fontSize: 14, fontWeight: 600,
      }}>
        <span>9:41</span>
        <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: 12, color: 'var(--muted)' }}>
          <span style={{ width: 16, height: 10, border: '1px solid var(--ink)', borderRadius: 2, position: 'relative' }}>
            <span style={{ position: 'absolute', inset: 1, background: 'var(--ink)', width: '70%', borderRadius: 1 }}/>
          </span>
        </span>
      </div>
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', padding: '4px 18px 18px' }}>
        {children}
      </div>
      <div style={{
        position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)',
        width: 120, height: 4, background: 'var(--ink)', borderRadius: 4, opacity: 0.85,
      }}/>
    </div>
  );
}

function Pill({ children, tone = 'default', dot, pulse }) {
  const tones = {
    default: { bg: 'var(--card)', fg: 'var(--ink)', border: 'var(--hairline)' },
    muted:   { bg: 'transparent', fg: 'var(--muted)', border: 'var(--hairline)' },
    live:    { bg: 'var(--green-soft)', fg: 'var(--green-ink)', border: 'transparent' },
    accent:  { bg: 'var(--coral-soft)', fg: 'var(--coral)', border: 'transparent' },
    solid:   { bg: 'var(--ink)', fg: '#fff', border: 'transparent' },
  }[tone];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      background: tones.bg, color: tones.fg,
      border: `1px solid ${tones.border}`,
      borderRadius: 999, padding: '3px 10px',
      fontSize: 12, fontWeight: 500, lineHeight: 1.4,
      whiteSpace: 'nowrap',
    }}>
      {dot && <span style={{
        width: 7, height: 7, borderRadius: '50%', background: dot,
        animation: pulse ? 'pulse-dot 1.6s ease-out infinite' : undefined,
      }}/>}
      {children}
    </span>
  );
}

function SectionLabel({ children, right }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', margin: '0 4px 10px' }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', letterSpacing: 1.4, textTransform: 'uppercase' }}>{children}</span>
      {right && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{right}</span>}
    </div>
  );
}

// ─── data model ────────────────────────────────────────────────────
const CHANNELS = [
  { key: 'Forge',  kind: 'bro', character: 'rabbit', role: 'qa',       status: 'IDLE',
    activity: 'No task',           meta: '—', progress: null },
  { key: 'Scout',  kind: 'bro', character: 'cat',    role: 'recon',    status: 'IDLE',
    activity: 'No task',           meta: '—', progress: null },
  { key: 'Atlas',  kind: 'bro', character: 'fox',    role: 'research', status: 'LIVE',
    activity: '拆解 hero 视觉风格', meta: '0:24', progress: 0.6,
    log: [
      '01  fetch screenshot · ok',
      '02  extract palette · 6 colors',
      '03  identify type pairing · running…',
    ] },
  { key: 'NewBro', kind: 'router' },
  { key: 'Codex',  kind: 'bro', character: 'person', role: 'build',    status: 'QUEUED',
    activity: '等 Atlas 输出后开工',  meta: '排队 #1', progress: null,
    waitingOn: 'Atlas' },
];
const NEWBRO_INDEX = CHANNELS.findIndex(c => c.kind === 'router');
const BROS = CHANNELS.filter(c => c.kind === 'bro');

// ─── ChannelWheel ──────────────────────────────────────────────────
const ITEM_W = 108;

function ChannelWheel({ items, idx, onChangeIdx, accent }) {
  const [dragOffset, setDragOffset] = useState(0);
  const dragRef = useRef(null);
  const trackRef = useRef(null);

  const onPointerDown = (e) => {
    dragRef.current = { startX: e.clientX, startIdx: idx };
    trackRef.current?.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (!dragRef.current) return;
    setDragOffset(e.clientX - dragRef.current.startX);
  };
  const onPointerUp = () => {
    if (!dragRef.current) return;
    const moved = -Math.round(dragOffset / ITEM_W);
    const next = Math.max(0, Math.min(items.length - 1, dragRef.current.startIdx + moved));
    if (next !== idx) onChangeIdx(next);
    setDragOffset(0);
    dragRef.current = null;
  };

  const virtIdx = idx - dragOffset / ITEM_W;
  const translate = -virtIdx * ITEM_W;
  const isDragging = dragRef.current != null;

  return (
    <div style={{ position: 'relative', height: 110 }}>
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 2,
        background: 'linear-gradient(90deg, var(--bg) 0%, transparent 18%, transparent 82%, var(--bg) 100%)',
      }}/>
      <div className="wheel-track"
        ref={trackRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        style={{ position: 'absolute', inset: 0, overflow: 'hidden', cursor: isDragging ? 'grabbing' : 'grab' }}>
        <div style={{
          position: 'absolute', left: '50%', top: 0, height: '100%',
          display: 'flex', alignItems: 'center',
          transform: `translateX(calc(-${ITEM_W/2}px + ${translate}px))`,
          transition: isDragging ? 'none' : 'transform 320ms cubic-bezier(0.22, 1, 0.36, 1)',
        }}>
          {items.map((item, i) => {
            const dist = Math.abs(i - virtIdx);
            const opacity = Math.max(0.25, 1 - dist * 0.32);
            const scale = Math.max(0.78, 1 - dist * 0.08);
            const isCenter = dist < 0.5;
            return (
              <div key={item.key}
                onClick={() => !isDragging && onChangeIdx(i)}
                style={{
                  width: ITEM_W, height: '100%', flexShrink: 0,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  cursor: 'pointer',
                  opacity, transform: `scale(${scale})`,
                  transition: isDragging ? 'none' : 'opacity 220ms, transform 220ms',
                }}>
                <ChannelChip item={item} active={isCenter} accent={accent}/>
              </div>
            );
          })}
        </div>
      </div>
      <DialMarks idx={virtIdx} count={items.length} accent={accent}/>
    </div>
  );
}

function ChannelChip({ item, active, accent }) {
  if (item.kind === 'router') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
        <div style={{
          width: 50, height: 50, borderRadius: 14,
          background: active ? accent : 'var(--card)',
          border: active ? 'none' : '1px solid var(--hairline)',
          color: active ? '#fff' : 'var(--ink)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 700, fontSize: 13, letterSpacing: -0.2,
          boxShadow: active ? `0 8px 18px -10px ${accent}` : 'none',
        }}>
          <NewBroGlyph color={active ? '#fff' : 'var(--ink)'}/>
        </div>
        <span style={{
          fontSize: 11, fontWeight: active ? 600 : 500,
          color: active ? 'var(--ink)' : 'var(--muted)', whiteSpace: 'nowrap',
        }}>{item.key}</span>
      </div>
    );
  }
  const ringColor =
    item.status === 'LIVE'   ? 'var(--green)' :
    item.status === 'QUEUED' ? accent :
    'var(--hairline)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
      <div style={{
        width: 50, height: 50, borderRadius: 14,
        background: active ? 'var(--card)' : 'transparent',
        border: `1.5px solid ${active ? ringColor : 'var(--hairline)'}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        position: 'relative',
        boxShadow: active ? '0 6px 14px -8px rgba(16,17,20,0.18)' : 'none',
      }}>
        <Character kind={item.character} size={32} sleeping={item.status === 'IDLE' && !active}/>
        {item.status === 'LIVE' && (
          <span style={{
            position: 'absolute', right: -2, bottom: -2,
            width: 12, height: 12, borderRadius: '50%',
            background: 'var(--green)', border: '2px solid var(--bg)',
            animation: 'pulse-dot 1.6s ease-out infinite',
          }}/>
        )}
      </div>
      <span style={{
        fontSize: 11, fontWeight: active ? 600 : 500,
        color: active ? 'var(--ink)' : 'var(--muted)', whiteSpace: 'nowrap',
      }}>{item.key}</span>
    </div>
  );
}

function NewBroGlyph({ color }) {
  return (
    <svg width="32" height="32" viewBox="0 0 64 64" fill="none"
      stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M24 14 L24 22"/>
      <path d="M28 12 L31 10" opacity="0.7"/>
      <path d="M28 16 L31 17" opacity="0.7"/>
      <rect x="18" y="22" width="22" height="30" rx="3.5"/>
      <path d="M22 27 L36 27"/>
      <path d="M22 30 L36 30"/>
      <rect x="22" y="34" width="14" height="7" rx="1.2"/>
      <circle cx="29" cy="46" r="2.2" fill={color} stroke="none"/>
    </svg>
  );
}

function DialMarks({ accent }) {
  const totalMarks = 41;
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 16 }}>
      <svg width="100%" height="14" viewBox="-100 0 200 14" preserveAspectRatio="none" style={{ display: 'block' }}>
        {Array.from({ length: totalMarks }).map((_, i) => {
          const off = (i - (totalMarks - 1) / 2);
          const x = off * 6;
          const isMajor = i % 5 === 0;
          const isCenter = i === (totalMarks - 1) / 2;
          return (
            <line key={i}
              x1={x} y1={isCenter ? 0 : (isMajor ? 4 : 7)}
              x2={x} y2={12}
              stroke={isCenter ? accent : (isMajor ? 'var(--muted)' : 'var(--hairline)')}
              strokeWidth={isCenter ? 1.8 : 0.8}
              strokeLinecap="round"/>
          );
        })}
      </svg>
      <svg width="14" height="8" style={{ position: 'absolute', left: '50%', transform: 'translateX(-50%)', top: -2 }}>
        <path d="M7 8 L1 0 L13 0 Z" fill={accent}/>
      </svg>
    </div>
  );
}

// ─── Views ─────────────────────────────────────────────────────────
function RouterView({ accent }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{
        padding: '12px 14px',
        background: 'var(--card)', border: '1px solid var(--hairline)', borderRadius: 14,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>自由分派模式</div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>NewBro 决定派给谁 · 你说事就行</div>
        </div>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: accent, letterSpacing: 0.4 }}>FREE ROUTE</span>
      </div>
      <SectionLabel right={`${BROS.filter(b=>b.status==='LIVE').length} live · ${BROS.filter(b=>b.status==='QUEUED').length} queued · ${BROS.filter(b=>b.status==='IDLE').length} idle`}>Worker Bros</SectionLabel>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {BROS.map(b => <DashboardRow key={b.key} b={b} accent={accent}/>)}
      </div>
    </div>
  );
}

function DashboardRow({ b, accent }) {
  const isLive = b.status === 'LIVE';
  const isQueued = b.status === 'QUEUED';
  const isIdle = b.status === 'IDLE';
  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--hairline)', borderRadius: 14,
      padding: '10px 12px', opacity: isIdle ? 0.78 : 1,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{
          width: 40, height: 40, borderRadius: 12,
          background: isIdle ? '#f4f4f6' : '#fafafb',
          border: '1px solid var(--hairline)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          position: 'relative', flexShrink: 0,
        }}>
          <Character kind={b.character} size={26} sleeping={isIdle}/>
          {isLive && (
            <span style={{
              position: 'absolute', right: -1, bottom: -1,
              width: 11, height: 11, borderRadius: '50%',
              background: 'var(--green)', border: '2px solid var(--card)',
            }}/>
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, fontSize: 14, color: isIdle ? 'var(--muted)' : 'var(--ink)' }}>{b.key}</span>
            <Pill tone="muted">{b.role}</Pill>
            {isLive   && <Pill tone="live"   dot="var(--green)" pulse>live</Pill>}
            {isQueued && <Pill tone="accent">queued</Pill>}
          </div>
          <div style={{
            fontSize: 12, marginTop: 3,
            color: isIdle ? 'var(--muted)' : 'var(--ink-soft)',
            fontStyle: isIdle ? 'italic' : 'normal',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>{b.activity}</div>
        </div>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--muted)' }}>{b.meta}</span>
      </div>
      {b.progress != null && (
        <div style={{ marginTop: 9, height: 3, background: 'var(--hairline-soft)', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{ width: `${b.progress*100}%`, height: '100%', background: accent }}/>
        </div>
      )}
    </div>
  );
}

function BroFocusView({ b, accent }) {
  const isLive = b.status === 'LIVE';
  const isQueued = b.status === 'QUEUED';
  const isIdle = b.status === 'IDLE';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{
        background: 'var(--card)', border: '1px solid var(--hairline)', borderRadius: 18,
        padding: 18, display: 'flex', alignItems: 'center', gap: 14,
        position: 'relative', overflow: 'hidden',
      }}>
        <div style={{
          width: 90, height: 90, borderRadius: 18,
          background: isIdle ? 'linear-gradient(180deg, #f5f5f7 0%, #ececef 100%)'
                            : 'linear-gradient(180deg, #fafafb 0%, #f1f1f4 100%)',
          border: '1px solid var(--hairline)',
          display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
          position: 'relative', flexShrink: 0, paddingBottom: 6,
        }}>
          <Character kind={b.character} size={64} sleeping={isIdle} working={isLive}/>
          {isIdle && <SleepZs/>}
          {isLive && <WorkingHalo accent={accent}/>}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', letterSpacing: 1.2, textTransform: 'uppercase' }}>
            {b.role}
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: -0.4, marginTop: 2 }}>{b.key}</div>
          <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {isLive   && <Pill tone="live"   dot="var(--green)" pulse>live</Pill>}
            {isQueued && <Pill tone="accent">queued</Pill>}
            {isIdle   && <Pill tone="muted">resting</Pill>}
            <Pill tone="muted">{b.meta}</Pill>
          </div>
        </div>
      </div>
      {isLive   && <LiveBody b={b} accent={accent}/>}
      {isQueued && <QueuedBody b={b} accent={accent}/>}
      {isIdle   && <IdleBody b={b} accent={accent}/>}
    </div>
  );
}

function LiveBody({ b, accent }) {
  return (
    <>
      <div style={{ background: 'var(--card)', border: '1px solid var(--hairline)', borderRadius: 14, padding: '12px 14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', letterSpacing: 1.2, textTransform: 'uppercase' }}>当前任务</div>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--muted)' }}>{Math.round(b.progress * 100)}%</span>
        </div>
        <div style={{ fontSize: 14, marginTop: 6, color: 'var(--ink)' }}>{b.activity}</div>
        <div style={{ marginTop: 10, height: 4, background: 'var(--hairline-soft)', borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ width: `${b.progress * 100}%`, height: '100%', background: accent, transition: 'width 400ms' }}/>
        </div>
      </div>
      {b.log && (
        <div style={{
          background: 'var(--card)', border: '1px solid var(--hairline)', borderRadius: 14,
          padding: '12px 14px',
          fontFamily: 'var(--mono)', fontSize: 11, lineHeight: 1.7, color: 'var(--ink-soft)',
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', letterSpacing: 1.2, textTransform: 'uppercase', fontFamily: 'var(--font)', marginBottom: 6 }}>进度</div>
          {b.log.map((line, i) => {
            const isLast = i === b.log.length - 1;
            return (
              <div key={i} style={{ display: 'flex', gap: 8, opacity: isLast ? 1 : 0.7 }}>
                <span style={{ color: isLast ? accent : 'var(--muted)' }}>{isLast ? '▸' : '✓'}</span>
                <span>{line}</span>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

function QueuedBody({ b, accent }) {
  return (
    <div style={{ background: 'var(--card)', border: '1px solid var(--hairline)', borderRadius: 14, padding: '14px 14px' }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', letterSpacing: 1.2, textTransform: 'uppercase' }}>待办</div>
      <div style={{ fontSize: 14, marginTop: 6 }}>{b.activity}</div>
      {b.waitingOn && (
        <div style={{
          marginTop: 12, padding: '10px 12px',
          background: 'var(--coral-soft)', border: `1px solid ${accent}33`,
          borderRadius: 10, fontSize: 12, color: 'var(--ink-soft)',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: accent }}>WAIT</span>
          等 <b style={{ color: 'var(--ink)' }}>{b.waitingOn}</b> 输出后自动开工
        </div>
      )}
    </div>
  );
}

function IdleBody({ b, accent }) {
  const briefs = {
    rabbit: '兔子蜷起来打盹了 · 给它派点活吧',
    cat:    '猫咪在窗台上眯着 · 想出去探探吗',
    fox:    '狐狸在巢里转圈圈 · 准备研究新东西',
    person: '人在椅子上发呆 · 等你说一声',
  };
  return (
    <div style={{ background: 'var(--card)', border: '1px solid var(--hairline)', borderRadius: 14, padding: '14px 14px' }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', letterSpacing: 1.2, textTransform: 'uppercase' }}>状态</div>
      <div style={{ fontSize: 14, marginTop: 6, fontStyle: 'italic', color: 'var(--ink-soft)' }}>
        {briefs[b.character] || '空闲中'}
      </div>
      <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Suggestion>派个研究任务</Suggestion>
        <Suggestion>让它做调研</Suggestion>
        <Suggestion>+ 自定义</Suggestion>
      </div>
    </div>
  );
}

function Suggestion({ children }) {
  return (
    <span style={{
      padding: '7px 12px',
      background: 'var(--bg)', border: '1px solid var(--hairline)', borderRadius: 999,
      fontSize: 12, color: 'var(--ink)', cursor: 'pointer',
    }}>{children}</span>
  );
}

function SleepZs() {
  return (
    <div style={{ position: 'absolute', top: 4, right: 6, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--muted)' }}>
      <span style={{ display: 'inline-block', animation: 'float-zzz 2.4s ease-in infinite' }}>z</span>
      <span style={{ display: 'inline-block', animation: 'float-zzz 2.4s ease-in 0.6s infinite', fontSize: 13 }}>Z</span>
    </div>
  );
}

function WorkingHalo({ accent }) {
  return (
    <div style={{
      position: 'absolute', top: 6, right: 6,
      width: 12, height: 12, borderRadius: '50%',
      background: accent,
      animation: 'breathe 1.8s ease-in-out infinite',
      boxShadow: `0 0 0 4px ${accent}22`,
    }}/>
  );
}

// ─── App ───────────────────────────────────────────────────────────
function App() {
  const accent = ACCENT;
  const [idx, setIdx] = useState(NEWBRO_INDEX);
  const selected = CHANNELS[idx];
  const isRouter = selected.kind === 'router';

  useEffect(() => { applyAccent(accent); }, [accent]);

  let ctaTitle, ctaSub, ctaHint;
  if (isRouter) {
    ctaTitle = 'Call NewBro';
    ctaSub   = 'Hands-free · 边说边干';
    ctaHint  = 'HOLD';
  } else if (selected.status === 'LIVE') {
    ctaTitle = `Listen in to ${selected.key}`;
    ctaSub   = '直连频道 · 听它边干边讲';
    ctaHint  = 'TUNE';
  } else if (selected.status === 'QUEUED') {
    ctaTitle = `Brief ${selected.key}`;
    ctaSub   = '直接给它派活 (跳过 NewBro)';
    ctaHint  = 'OVERRIDE';
  } else {
    ctaTitle = `Wake up ${selected.key}`;
    ctaSub   = '直接给它派活 (跳过 NewBro)';
    ctaHint  = 'OVERRIDE';
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '60px 20px',
      background: 'radial-gradient(ellipse at top, #f3f3f5 0%, #e6e6ea 100%)',
    }}>
      <CleanPhone>
        <div style={{ marginTop: 6 }}>
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>
            <span>Workspace</span>
            <span style={{ margin: '0 6px', color: '#c8c8cd' }}>/</span>
            <span style={{ color: 'var(--ink)', fontWeight: 500 }}>Walkie</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
            <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, letterSpacing: -0.6 }}>Walkie</h1>
            <Pill>4 configured</Pill>
            <Pill tone="live" dot="var(--green)" pulse>1 live</Pill>
          </div>
        </div>

        <div style={{ marginTop: 14, flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden', paddingRight: 2 }}>
          {isRouter
            ? <RouterView accent={accent}/>
            : <BroFocusView b={selected} accent={accent}/>}
        </div>

        <div style={{ marginTop: 10 }}>
          <SectionLabel right={isRouter ? 'NewBro · 默认' : `${selected.key} · ${selected.role}`}>
            Channel
          </SectionLabel>
          <ChannelWheel items={CHANNELS} idx={idx} onChangeIdx={setIdx} accent={accent}/>
        </div>

        <div style={{
          marginTop: 12,
          background: accent, color: '#fff', borderRadius: 16,
          padding: '13px 14px',
          display: 'flex', alignItems: 'center', gap: 12,
          boxShadow: `0 12px 26px -10px ${accent}`,
          cursor: 'pointer',
        }}>
          <div style={{
            width: 40, height: 40, borderRadius: '50%',
            background: 'rgba(255,255,255,0.2)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>
            </svg>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 15, lineHeight: 1.1 }}>{ctaTitle}</div>
            <div style={{ fontSize: 12, opacity: 0.85, marginTop: 2 }}>{ctaSub}</div>
          </div>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10, opacity: 0.85, letterSpacing: 0.4 }}>{ctaHint}</div>
        </div>

        <div style={{
          marginTop: 8,
          background: 'var(--card)', border: '1px solid var(--hairline)', borderRadius: 24,
          padding: 5,
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <div style={{ flex: 1, padding: '7px 12px', fontSize: 13, color: 'var(--muted)' }}>
            {isRouter ? '或打字…' : `或直接打字给 ${selected.key}…`}
          </div>
          <div style={{
            width: 32, height: 32, borderRadius: '50%',
            background: 'var(--bg)', border: '1px solid var(--hairline)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 13, color: 'var(--ink)',
          }}>↑</div>
        </div>
      </CleanPhone>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
