import { useMemo, useRef, useState, type FormEvent, type PointerEvent, type ReactNode } from "react";
import { Phone, Send } from "lucide-react";
import type { BroCardModel } from "../types";
import { MobileCharacter } from "./characters";

const ACCENT = "#ff6a45";
const ITEM_WIDTH = 108;

type MobileBroChannel = {
  kind: "bro";
  id: string;
  key: string;
  role: string;
  status: "LIVE" | "QUEUED" | "IDLE";
  activity: string;
  meta: string;
  progress: number | null;
  details: string[];
  character: "cat" | "rabbit" | "fox" | "person";
};

type RouterChannel = {
  kind: "router";
  id: "newbro";
  key: "NewBro";
};

type MobileChannel = RouterChannel | MobileBroChannel;

export function MobileWalkie({
  bros,
  onSubmitMessage,
}: {
  bros: BroCardModel[];
  onSubmitMessage: (text: string) => boolean;
}) {
  const channels = useMemo<MobileChannel[]>(() => {
    const broChannels = bros.map(toMobileBroChannel);
    const routerIndex = Math.min(3, broChannels.length);
    return [
      ...broChannels.slice(0, routerIndex),
      { kind: "router", id: "newbro", key: "NewBro" },
      ...broChannels.slice(routerIndex),
    ];
  }, [bros]);
  const routerIndex = channels.findIndex((channel) => channel.kind === "router");
  const [idx, setIdx] = useState(routerIndex >= 0 ? routerIndex : 0);
  const [draft, setDraft] = useState("");
  const selected = channels[Math.min(idx, Math.max(channels.length - 1, 0))] ?? { kind: "router", id: "newbro", key: "NewBro" };
  const isRouter = selected.kind === "router";

  const liveCount = channels.filter((channel) => channel.kind === "bro" && channel.status === "LIVE").length;
  const queuedCount = channels.filter((channel) => channel.kind === "bro" && channel.status === "QUEUED").length;
  const idleCount = channels.filter((channel) => channel.kind === "bro" && channel.status === "IDLE").length;
  const cta = ctaForChannel(selected);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    if (onSubmitMessage(text)) {
      setDraft("");
    }
  }

  return (
    <div className="nb-mobile-stage" data-testid="mobile-walkie">
      <div className="nb-mobile-phone">
        <div className="nb-mobile-status">
          <span>9:41</span>
          <span className="nb-mobile-battery" aria-hidden="true"><span /></span>
        </div>

        <div className="nb-mobile-content">
          <header className="nb-mobile-heading">
            <div className="nb-mobile-crumb">
              <span>Workspace</span>
              <span>/</span>
              <strong>Walkie</strong>
            </div>
            <div className="nb-mobile-title-row">
              <h1>Walkie</h1>
              <Pill>{channels.filter((channel) => channel.kind === "bro").length} configured</Pill>
              <Pill tone="live" dot pulse>{liveCount} live</Pill>
            </div>
          </header>

          <main className="nb-mobile-scroll">
            {isRouter ? (
              <RouterView
                channels={channels}
                liveCount={liveCount}
                queuedCount={queuedCount}
                idleCount={idleCount}
              />
            ) : (
              <BroFocusView bro={selected} />
            )}
          </main>

          <section className="nb-mobile-channel-section" aria-label="Channel selector">
            <SectionLabel right={isRouter ? "NewBro · default" : `${selected.key} · ${selected.role}`}>Channel</SectionLabel>
            <ChannelWheel channels={channels} idx={idx} onChangeIdx={setIdx} />
          </section>

          <button className="nb-mobile-cta" type="button" aria-label={cta.title}>
            <span className="nb-mobile-cta-icon"><Phone size={18} strokeWidth={2.2} /></span>
            <span className="nb-mobile-cta-copy">
              <strong>{cta.title}</strong>
              <span>{cta.sub}</span>
            </span>
            <span className="nb-mobile-cta-hint">{cta.hint}</span>
          </button>

          <form className="nb-mobile-input" onSubmit={submit}>
            <input
              aria-label="Message"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={isRouter ? "或打字..." : `或直接打字给 ${selected.key}...`}
            />
            <button type="submit" aria-label="Send message">
              <Send size={15} strokeWidth={2.1} />
            </button>
          </form>
        </div>
        <div className="nb-mobile-home-indicator" aria-hidden="true" />
      </div>
    </div>
  );
}

function toMobileBroChannel(bro: BroCardModel): MobileBroChannel {
  const status = bro.status === "busy" && bro.liveState === "live" ? "LIVE" : bro.status === "busy" ? "QUEUED" : "IDLE";
  return {
    kind: "bro",
    id: bro.id,
    key: bro.name,
    role: bro.role,
    status,
    activity: bro.taskTitle,
    meta: status === "LIVE" ? bro.progressLabel : status === "QUEUED" ? "queued" : "idle",
    progress: status === "IDLE" ? null : Math.max(0, Math.min(100, bro.progress)) / 100,
    details: bro.progressDetails,
    character: avatarToCharacter(bro.avatarType),
  };
}

function avatarToCharacter(avatar: BroCardModel["avatarType"]): MobileBroChannel["character"] {
  if (avatar === "bunny") return "rabbit";
  if (avatar === "bro") return "person";
  return avatar;
}

function ctaForChannel(channel: MobileChannel) {
  if (channel.kind === "router") {
    return { title: "Call NewBro", sub: "Hands-free · 边说边干", hint: "HOLD" };
  }
  if (channel.status === "LIVE") {
    return { title: `Listen in to ${channel.key}`, sub: "直连频道 · 听它边干边讲", hint: "TUNE" };
  }
  if (channel.status === "QUEUED") {
    return { title: `Brief ${channel.key}`, sub: "直接给它派活 (跳过 NewBro)", hint: "OVERRIDE" };
  }
  return { title: `Wake up ${channel.key}`, sub: "直接给它派活 (跳过 NewBro)", hint: "OVERRIDE" };
}

function RouterView({
  channels,
  liveCount,
  queuedCount,
  idleCount,
}: {
  channels: MobileChannel[];
  liveCount: number;
  queuedCount: number;
  idleCount: number;
}) {
  const broChannels = channels.filter((channel): channel is MobileBroChannel => channel.kind === "bro");
  return (
    <div className="nb-mobile-view-stack">
      <div className="nb-mobile-route-card">
        <div>
          <div className="nb-mobile-route-title">自由分派模式</div>
          <div className="nb-mobile-muted">NewBro 决定派给谁 · 你说事就行</div>
        </div>
        <span>FREE ROUTE</span>
      </div>
      <SectionLabel right={`${liveCount} live · ${queuedCount} queued · ${idleCount} idle`}>Worker Bros</SectionLabel>
      <div className="nb-mobile-rows">
        {broChannels.map((bro) => <DashboardRow key={bro.id} bro={bro} />)}
      </div>
    </div>
  );
}

function DashboardRow({ bro }: { bro: MobileBroChannel }) {
  const isLive = bro.status === "LIVE";
  const isQueued = bro.status === "QUEUED";
  const isIdle = bro.status === "IDLE";
  return (
    <article className={`nb-mobile-row ${isIdle ? "nb-mobile-row-idle" : ""}`} data-testid={`mobile-bro-row-${bro.id}`}>
      <div className="nb-mobile-row-main">
        <div className="nb-mobile-row-avatar">
          <MobileCharacter kind={bro.character} size={26} sleeping={isIdle} />
          {isLive ? <span className="nb-mobile-live-dot" /> : null}
        </div>
        <div className="nb-mobile-row-copy">
          <div className="nb-mobile-row-title">
            <strong>{bro.key}</strong>
            <Pill tone="muted">{bro.role}</Pill>
            {isLive ? <Pill tone="live" dot pulse>live</Pill> : null}
            {isQueued ? <Pill tone="accent">queued</Pill> : null}
          </div>
          <div className="nb-mobile-row-activity">{bro.activity}</div>
        </div>
        <span className="nb-mobile-meta">{bro.meta}</span>
      </div>
      {bro.progress !== null ? (
        <div className="nb-mobile-progress"><span style={{ width: `${bro.progress * 100}%` }} /></div>
      ) : null}
    </article>
  );
}

function BroFocusView({ bro }: { bro: MobileBroChannel }) {
  const isLive = bro.status === "LIVE";
  const isQueued = bro.status === "QUEUED";
  const isIdle = bro.status === "IDLE";
  return (
    <div className="nb-mobile-view-stack" data-testid={`mobile-bro-focus-${bro.id}`}>
      <section className="nb-mobile-focus-card">
        <div className="nb-mobile-focus-avatar">
          <MobileCharacter kind={bro.character} size={64} sleeping={isIdle} />
          {isIdle ? <SleepZs /> : null}
          {isLive ? <span className="nb-mobile-working-dot" /> : null}
        </div>
        <div className="nb-mobile-focus-copy">
          <div className="nb-mobile-focus-role">{bro.role}</div>
          <h2>{bro.key}</h2>
          <div className="nb-mobile-pill-row">
            {isLive ? <Pill tone="live" dot pulse>live</Pill> : null}
            {isQueued ? <Pill tone="accent">queued</Pill> : null}
            {isIdle ? <Pill tone="muted">resting</Pill> : null}
            <Pill tone="muted">{bro.meta}</Pill>
          </div>
        </div>
      </section>
      {isLive ? <LiveBody bro={bro} /> : null}
      {isQueued ? <QueuedBody bro={bro} /> : null}
      {isIdle ? <IdleBody bro={bro} /> : null}
    </div>
  );
}

function LiveBody({ bro }: { bro: MobileBroChannel }) {
  return (
    <>
      <section className="nb-mobile-card">
        <div className="nb-mobile-card-header">
          <span>当前任务</span>
          <strong>{Math.round((bro.progress ?? 0) * 100)}%</strong>
        </div>
        <p>{bro.activity}</p>
        <div className="nb-mobile-progress nb-mobile-progress-large"><span style={{ width: `${(bro.progress ?? 0) * 100}%` }} /></div>
      </section>
      {bro.details.length > 0 ? (
        <section className="nb-mobile-log">
          <div>进度</div>
          {bro.details.slice(0, 3).map((detail, index) => (
            <p key={`${detail}-${index}`}><span>{index === 0 ? "▸" : "✓"}</span>{detail}</p>
          ))}
        </section>
      ) : null}
    </>
  );
}

function QueuedBody({ bro }: { bro: MobileBroChannel }) {
  return (
    <section className="nb-mobile-card">
      <div className="nb-mobile-card-kicker">待办</div>
      <p>{bro.activity}</p>
      <div className="nb-mobile-wait">WAIT · 等 NewBro 或上游输出后自动开工</div>
    </section>
  );
}

function IdleBody({ bro }: { bro: MobileBroChannel }) {
  return (
    <section className="nb-mobile-card">
      <div className="nb-mobile-card-kicker">状态</div>
      <p className="nb-mobile-idle-note">{idleNoteFor(bro.character)}</p>
      <div className="nb-mobile-suggestions">
        <span>派个研究任务</span>
        <span>让它做调研</span>
        <span>+ 自定义</span>
      </div>
    </section>
  );
}

function idleNoteFor(character: MobileBroChannel["character"]) {
  return {
    rabbit: "兔子蜷起来打盹了 · 给它派点活吧",
    cat: "猫咪在窗台上眯着 · 想出去探探吗",
    fox: "狐狸在巢里转圈圈 · 准备研究新东西",
    person: "人在椅子上发呆 · 等你说一声",
  }[character];
}

function ChannelWheel({
  channels,
  idx,
  onChangeIdx,
}: {
  channels: MobileChannel[];
  idx: number;
  onChangeIdx: (idx: number) => void;
}) {
  const [dragOffset, setDragOffset] = useState(0);
  const dragRef = useRef<{ startX: number; startIdx: number } | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const virtIdx = idx - dragOffset / ITEM_WIDTH;
  const translate = -virtIdx * ITEM_WIDTH;
  const isDragging = dragRef.current !== null;

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    dragRef.current = { startX: event.clientX, startIdx: idx };
    trackRef.current?.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!dragRef.current) return;
    setDragOffset(event.clientX - dragRef.current.startX);
  }

  function onPointerUp() {
    if (!dragRef.current) return;
    const moved = -Math.round(dragOffset / ITEM_WIDTH);
    const next = Math.max(0, Math.min(channels.length - 1, dragRef.current.startIdx + moved));
    if (next !== idx) onChangeIdx(next);
    setDragOffset(0);
    dragRef.current = null;
  }

  return (
    <div className="nb-mobile-wheel">
      <div className="nb-mobile-wheel-fade" />
      <div
        ref={trackRef}
        className="nb-mobile-wheel-track"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div
          className="nb-mobile-wheel-items"
          style={{
            transform: `translateX(calc(-${ITEM_WIDTH / 2}px + ${translate}px))`,
            transition: isDragging ? "none" : "transform 320ms cubic-bezier(0.22, 1, 0.36, 1)",
          }}
        >
          {channels.map((channel, index) => {
            const dist = Math.abs(index - virtIdx);
            const active = dist < 0.5;
            return (
              <button
                key={channel.id}
                type="button"
                data-testid={`mobile-channel-${channel.id}`}
                onClick={() => {
                  if (!isDragging) onChangeIdx(index);
                }}
                className="nb-mobile-channel-chip"
                style={{
                  opacity: Math.max(0.25, 1 - dist * 0.32),
                  transform: `scale(${Math.max(0.78, 1 - dist * 0.08)})`,
                  transition: isDragging ? "none" : "opacity 220ms, transform 220ms",
                }}
              >
                <ChannelChip channel={channel} active={active} />
              </button>
            );
          })}
        </div>
      </div>
      <DialMarks />
    </div>
  );
}

function ChannelChip({ channel, active }: { channel: MobileChannel; active: boolean }) {
  if (channel.kind === "router") {
    return (
      <>
        <span className={`nb-mobile-router-glyph ${active ? "is-active" : ""}`}><NewBroGlyph /></span>
        <span className={active ? "is-active" : ""}>{channel.key}</span>
      </>
    );
  }
  const statusClass = channel.status === "LIVE" ? "is-live" : channel.status === "QUEUED" ? "is-queued" : "";
  return (
    <>
      <span className={`nb-mobile-bro-chip-avatar ${active ? "is-active" : ""} ${statusClass}`}>
        <MobileCharacter kind={channel.character} size={32} sleeping={channel.status === "IDLE" && active} />
        {channel.status === "LIVE" ? <span className="nb-mobile-live-dot" /> : null}
      </span>
      <span className={active ? "is-active" : ""}>{channel.key}</span>
    </>
  );
}

function NewBroGlyph() {
  return (
    <svg width="32" height="32" viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M24 14 L24 22" />
      <path d="M28 12 L31 10" opacity="0.7" />
      <path d="M28 16 L31 17" opacity="0.7" />
      <rect x="18" y="22" width="22" height="30" rx="3.5" />
      <path d="M22 27 L36 27" />
      <path d="M22 30 L36 30" />
      <rect x="22" y="34" width="14" height="7" rx="1.2" />
      <circle cx="29" cy="46" r="2.2" fill="currentColor" stroke="none" />
    </svg>
  );
}

function DialMarks() {
  return (
    <div className="nb-mobile-dial">
      <svg width="100%" height="14" viewBox="-100 0 200 14" preserveAspectRatio="none">
        {Array.from({ length: 41 }).map((_, index) => {
          const off = index - 20;
          const x = off * 6;
          const isMajor = index % 5 === 0;
          const isCenter = index === 20;
          return (
            <line
              key={index}
              x1={x}
              y1={isCenter ? 0 : isMajor ? 4 : 7}
              x2={x}
              y2={12}
              stroke={isCenter ? ACCENT : isMajor ? "var(--nb-mobile-muted)" : "var(--nb-mobile-hairline)"}
              strokeWidth={isCenter ? 1.8 : 0.8}
              strokeLinecap="round"
            />
          );
        })}
      </svg>
      <span />
    </div>
  );
}

function Pill({
  children,
  tone = "default",
  dot = false,
  pulse = false,
}: {
  children: ReactNode;
  tone?: "default" | "muted" | "live" | "accent";
  dot?: boolean;
  pulse?: boolean;
}) {
  return (
    <span className={`nb-mobile-pill nb-mobile-pill-${tone}`}>
      {dot ? <span className={pulse ? "nb-mobile-pulse-dot" : ""} /> : null}
      {children}
    </span>
  );
}

function SectionLabel({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="nb-mobile-section-label">
      <span>{children}</span>
      {right ? <span>{right}</span> : null}
    </div>
  );
}

function SleepZs() {
  return (
    <div className="nb-mobile-sleep-zs" aria-hidden="true">
      <span>z</span>
      <span>Z</span>
    </div>
  );
}
