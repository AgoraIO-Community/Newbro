// ReasoningPhase is no longer exported from lib/reasoningPhase (superseded by
// LiveTurnState). Keep the type local so the component compiles until Task 5
// removes this file entirely.
type ReasoningPhase = "ack" | "streaming" | "done";

export interface ReasoningStepView {
  id: string;
  label: string;
}

const WINDOW = 3;
const FADE = [1, 0.55, 0.26];

function windowed(steps: ReasoningStepView[]) {
  const startAt = Math.max(0, steps.length - WINDOW);
  return steps.slice(startAt, steps.length);
}

function StreamingProgress({ mobile }: { mobile: boolean }) {
  const prefix = mobile ? "thr" : "dt";

  return (
    <div className={`${prefix}-reason-stream-progress`} aria-hidden="true">
      <span />
      <span />
    </div>
  );
}

/**
 * The assistant's live reasoning bubble for the `ack` and `streaming` phases.
 * (The `done` phase is rendered by SettledAnswerBubble.)
 */
export function ReasoningBubble({
  broName,
  phase,
  steps,
  mobile,
  canStop,
  onStop,
}: {
  broName: string;
  phase: Exclude<ReasoningPhase, "done">; // "ack" | "streaming" — done is rendered by SettledAnswerBubble
  steps: ReasoningStepView[];
  mobile: boolean;
  canStop: boolean;
  onStop: () => void;
}) {
  const stopButton = canStop ? (
    <button
      type="button"
      className={mobile ? "thr-reason-stop" : "dt-reason-stop"}
      onClick={onStop}
      aria-label="Stop"
    >
      Stop
    </button>
  ) : null;

  if (mobile) {
    return (
      <div className="thr-turn thr-turn-bro">
        <div className="thr-bubble thr-bubble-bro thr-reason" aria-live="polite">
          <div className="thr-reason-head">
            <span className="thr-reason-kicker">
              <span className="thr-reason-orb" aria-hidden="true"><span /><span /><span /></span>
              {broName} is working
            </span>
            {stopButton}
          </div>
          {phase === "ack" ? (
            <div className="thr-reason-skeleton" aria-hidden="true">
              <span style={{ width: "82%" }} />
              <span style={{ width: "61%" }} />
            </div>
          ) : (
            <>
              <ol className="thr-reason-steps">
                {windowed(steps).map((s, j, vis) => {
                  const dist = vis.length - 1 - j;
                  const isLast = dist === 0;
                  return (
                    <li
                      key={s.id}
                      className={`thr-reason-step${isLast ? " thr-reason-step-active" : " thr-reason-step-done"}`}
                      style={{ opacity: FADE[dist] ?? 0.26 }}
                    >
                      <span className="thr-reason-mark" aria-hidden="true" />
                      <span className="thr-reason-text">{s.label}</span>
                    </li>
                  );
                })}
              </ol>
              <StreamingProgress mobile />
            </>
          )}
        </div>
        <div className="thr-meta">{broName} · updating live</div>
      </div>
    );
  }

  return (
    <div className="dt-turn dt-turn-bro">
      <div className="dt-bubble dt-bubble-bro dt-bubble-reason" aria-live="polite">
        <div className="dt-reason-head">
          <span className="dt-reason-kicker">
            <span className="dt-reason-orb" aria-hidden="true"><span /><span /><span /></span>
            {broName} is working
          </span>
          {stopButton}
        </div>
        {phase === "ack" ? (
          <div className="dt-reason-skeleton" aria-hidden="true">
            <span style={{ width: "82%" }} />
            <span style={{ width: "61%" }} />
          </div>
        ) : (
          <>
            <ol className="dt-reason-steps">
              {windowed(steps).map((s, j, vis) => {
                const dist = vis.length - 1 - j;
                const isLast = dist === 0;
                return (
                  <li
                    key={s.id}
                    className={`dt-reason-step${isLast ? " dt-reason-step-active" : " dt-reason-step-done"}`}
                    style={{ opacity: FADE[dist] ?? 0.26 }}
                  >
                    <span className="dt-reason-step-mark" aria-hidden="true" />
                    <span className="dt-reason-step-text">{s.label}</span>
                  </li>
                );
              })}
            </ol>
            <StreamingProgress mobile={false} />
          </>
        )}
      </div>
    </div>
  );
}
