import { useState } from "react";
import type { LiveTurnState } from "./lib/reasoningPhase";
import { MarkdownText, type MarkdownDownloadContext } from "./components/ui/markdown-text";

export interface ReasoningStepView {
  id: string;
  label: string;
}

const WINDOW = 3;
// Opacity per step by distance from the newest: [newest, -1, -2]. Older steps fade out.
const FADE = [1, 0.55, 0.26];
const SETTLED_COLLAPSED = 3;

function windowed(steps: ReasoningStepView[]) {
  const startAt = Math.max(0, steps.length - WINDOW);
  return steps.slice(startAt, steps.length);
}

interface ClassMap {
  turn: string;
  bubbleLive: string;
  bubbleSettled: string;
  head: string;
  kicker: string;
  orb: string;
  stop: string;
  skeleton: string;
  steps: string;
  stepsStatic: string;
  step: string;
  stepActive: string;
  stepDone: string;
  mark: string;
  text: string;
  streamProgress: string;
  divider: string;
  answer: string;
  caret: string;
  commentary: string;
  commentaryText: string;
  collapsed: string;
  collapsedOpen: string;
  chev: string;
  meta: string;
}

const DESKTOP: ClassMap = {
  turn: "dt-turn dt-turn-bro",
  bubbleLive: "dt-bubble dt-bubble-bro dt-bubble-reason",
  bubbleSettled: "dt-bubble dt-bubble-bro dt-bubble-answer",
  head: "dt-reason-head",
  kicker: "dt-reason-kicker",
  orb: "dt-reason-orb",
  stop: "dt-reason-stop",
  skeleton: "dt-reason-skeleton",
  steps: "dt-reason-steps",
  stepsStatic: "dt-reason-steps dt-reason-steps-static",
  step: "dt-reason-step",
  stepActive: "dt-reason-step-active",
  stepDone: "dt-reason-step-done",
  mark: "dt-reason-step-mark",
  text: "dt-reason-step-text",
  streamProgress: "dt-reason-stream-progress",
  divider: "dt-reason-divider",
  answer: "dt-answer-text",
  caret: "dt-reason-caret",
  commentary: "dt-commentary",
  commentaryText: "dt-commentary-text",
  collapsed: "dt-reason-collapsed",
  collapsedOpen: "dt-reason-collapsed-open",
  chev: "dt-reason-collapsed-chev",
  meta: "dt-bubble-meta",
};

const MOBILE: ClassMap = {
  turn: "thr-turn thr-turn-bro",
  bubbleLive: "thr-bubble thr-bubble-bro thr-reason",
  bubbleSettled: "thr-bubble thr-bubble-bro thr-bubble-answer",
  head: "thr-reason-head",
  kicker: "thr-reason-kicker",
  orb: "thr-reason-orb",
  stop: "thr-reason-stop",
  skeleton: "thr-reason-skeleton",
  steps: "thr-reason-steps",
  stepsStatic: "thr-reason-steps thr-reason-steps-static",
  step: "thr-reason-step",
  stepActive: "thr-reason-step-active",
  stepDone: "thr-reason-step-done",
  mark: "thr-reason-mark",
  text: "thr-reason-text",
  streamProgress: "thr-reason-stream-progress",
  divider: "thr-reason-divider",
  answer: "thr-answer-text",
  caret: "thr-reason-caret",
  commentary: "thr-commentary",
  commentaryText: "thr-commentary-text",
  collapsed: "thr-reason-collapsed",
  collapsedOpen: "thr-reason-collapsed-open",
  chev: "thr-reason-collapsed-chev",
  meta: "thr-meta",
};

function StreamingProgress({ className }: { className: string }) {
  return (
    <div className={className} aria-hidden="true">
      <span />
      <span />
    </div>
  );
}

function LiveSteps({ c, visible }: { c: ClassMap; visible: ReasoningStepView[] }) {
  if (visible.length === 0) return null;
  return (
    <ol className={c.steps}>
      {visible.map((s, j) => {
        const dist = visible.length - 1 - j;
        const isLast = dist === 0;
        return (
          <li
            key={s.id}
            className={`${c.step} ${isLast ? c.stepActive : c.stepDone}`}
            style={{ opacity: FADE[dist] ?? 0.26 }}
          >
            <span className={c.mark} aria-hidden="true" />
            <span className={c.text}>{s.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function SettledSteps({ c, steps }: { c: ClassMap; steps: ReasoningStepView[] }) {
  const [showAll, setShowAll] = useState(false);
  if (steps.length === 0) return null;
  const hasMore = steps.length > SETTLED_COLLAPSED;
  const visible = showAll ? steps : steps.slice(-SETTLED_COLLAPSED);
  return (
    <>
      {hasMore ? (
        <button
          type="button"
          className={`${c.collapsed}${showAll ? ` ${c.collapsedOpen}` : ""}`}
          onClick={() => setShowAll((v) => !v)}
          aria-expanded={showAll}
        >
          <span>{showAll ? "Hide steps" : `Show all ${steps.length} steps`}</span>
          <svg className={c.chev} viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      ) : null}
      <ol className={c.stepsStatic}>
        {visible.map((s) => (
          <li key={s.id} className={`${c.step} ${c.stepDone}`}>
            <span className={c.mark} aria-hidden="true" />
            <span className={c.text}>{s.label}</span>
          </li>
        ))}
      </ol>
    </>
  );
}

/**
 * The assistant's turn bubble across its whole lifecycle. "live" (connecting →
 * reasoning → answering) carries a persistent alive cue (orb, and a caret while
 * answering); "settled" drops the cue and collapses steps.
 *
 * The answer markdown lives in a single stable slot (the `showAnswer` block) used
 * by BOTH the answering and settled states, so it is NOT remounted when the turn
 * settles. NOTE: this relies on `<MarkdownText>` staying the FIRST child of the
 * answer div; the caret is rendered after it. Do not reorder them, or the markdown
 * node will remount on settle.
 */
export function LiveTurnBubble({
  broName,
  state,
  steps,
  answer,
  activeCommentary = null,
  mobile,
  canStop,
  onStop,
  downloadContext,
}: {
  broName: string;
  state: LiveTurnState;
  steps: ReasoningStepView[];
  answer: string;
  /** The currently-streaming commentary line, shown prominently above the
   * compact step list while reasoning; it collapses into `steps` once done. */
  activeCommentary?: string | null;
  mobile: boolean;
  canStop: boolean;
  onStop: () => void;
  downloadContext?: MarkdownDownloadContext;
}) {
  const c = mobile ? MOBILE : DESKTOP;
  const settled = state.kind === "settled";
  const sub = state.kind === "live" ? state.sub : null;
  const visibleSteps = windowed(steps);

  const header = settled ? null : (
    <div className={c.head}>
      <span className={c.kicker}>
        <span className={c.orb} aria-hidden="true"><span /><span /><span /></span>
        {broName} is working
      </span>
      {canStop ? (
        <button type="button" className={c.stop} onClick={onStop} aria-label="Stop">
          Stop
        </button>
      ) : null}
    </div>
  );

  let reasoningRegion = null;
  if (sub === "connecting") {
    reasoningRegion = (
      <div className={c.skeleton} aria-hidden="true">
        <span style={{ width: "82%" }} />
        <span style={{ width: "61%" }} />
      </div>
    );
  } else if (sub === "reasoning") {
    reasoningRegion = (
      <>
        {activeCommentary ? (
          <div className={c.commentary}>
            <span className={c.commentaryText}>{activeCommentary}</span>
            <span className={c.caret} aria-hidden="true" />
          </div>
        ) : (
          <StreamingProgress className={c.streamProgress} />
        )}
        <LiveSteps c={c} visible={visibleSteps} />
      </>
    );
  } else if (sub === "answering") {
    reasoningRegion = <LiveSteps c={c} visible={visibleSteps} />;
  } else if (settled) {
    reasoningRegion = <SettledSteps c={c} steps={steps} />;
  }

  const hasAnswer = answer !== "";
  const showDivider = sub === "answering" && hasAnswer && visibleSteps.length > 0;
  const showAnswer = (sub === "answering" || settled) && hasAnswer;

  return (
    <div className={c.turn}>
      <div className={settled ? c.bubbleSettled : c.bubbleLive} aria-live="polite">
        {header}
        {reasoningRegion}
        {showDivider ? <div className={c.divider} aria-hidden="true" /> : null}
        {showAnswer ? (
          <div className={c.answer}>
            <MarkdownText downloadContext={downloadContext}>{answer}</MarkdownText>
            {sub === "answering" ? <span className={c.caret} aria-hidden="true" /> : null}
          </div>
        ) : null}
      </div>
      {settled ? (
        <div className={c.meta}><span>{broName}</span></div>
      ) : mobile ? (
        <div className={c.meta}>{broName} · updating live</div>
      ) : null}
    </div>
  );
}
