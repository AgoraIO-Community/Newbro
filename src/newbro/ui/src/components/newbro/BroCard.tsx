import { motion } from "framer-motion";
import { BroPortrait } from "./BroPortrait";
import type { BroCardModel } from "./types";

function broState(bro: BroCardModel): "working" | "offline" | "idle" {
  if (bro.status === "busy") return "working";
  if (bro.liveState === "offline" || bro.liveState === "unbound") return "offline";
  return "idle";
}

function stateLabel(bro: BroCardModel) {
  if (bro.status === "busy") return `${Math.round(bro.progress)}%`;
  if (bro.liveState === "live") return "ready";
  if (bro.liveState === "offline") return "offline";
  return "setup";
}

function nodeNote(bro: BroCardModel) {
  if (bro.liveState === "live") return bro.nodeName ? `on ${bro.nodeName}` : "node connected";
  if (bro.liveState === "offline") return bro.nodeName ? `${bro.nodeName} offline` : "node offline";
  return "needs node";
}

export function BroCard({
  bro,
  onClick,
}: {
  bro: BroCardModel;
  onClick?: (broId: string) => void;
}) {
  const state = broState(bro);
  const tone = state === "working" ? "info" : state === "offline" ? "warn" : "calm";

  return (
    <motion.button
      data-testid={`bro-card-${bro.id}`}
      type="button"
      whileTap={{ scale: 0.997 }}
      onClick={() => onClick?.(bro.id)}
      className={`dt-bro-card ${state === "offline" ? "dt-bro-card-warn" : ""}`}
    >
      <BroPortrait bro={bro} active={state === "working"} talking={false} />
      <div className="dt-bro-card-body">
        <div className="dt-bro-card-row">
          <span className="dt-bro-card-name">{bro.name}</span>
          <span className={`dt-home-chip dt-home-chip-${tone}`}>
            <span className="dt-home-chip-dot" />
            {stateLabel(bro)}
          </span>
        </div>
        <div className="dt-bro-card-meta">
          <span>{bro.role}</span>
          <span className="dt-bro-card-mono">{nodeNote(bro)}</span>
        </div>
        <div className="dt-bro-card-task">
          {state === "working" ? <span className="dt-bro-card-spin" /> : null}
          <span className="dt-bro-card-task-text">{bro.taskTitle || bro.idleNote}</span>
          <span className="dt-bro-card-arrow">›</span>
        </div>
        {state === "working" ? (
          <div className="dt-bro-card-bar">
            <span className="dt-bro-card-bar-fill" style={{ width: `${Math.max(5, Math.min(100, bro.progress))}%` }} />
          </div>
        ) : null}
        {bro.progressDetails[0] ? <div className="dt-bro-card-step">{bro.progressDetails[0]}</div> : null}
      </div>
    </motion.button>
  );
}
