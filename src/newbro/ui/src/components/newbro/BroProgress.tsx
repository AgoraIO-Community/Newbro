import { MarkdownText } from "../ui/markdown-text";
import type { BroCardModel } from "./types";

export function BroProgress({
  bro,
  talking,
  compact = false,
}: {
  bro: BroCardModel;
  talking: boolean;
  compact?: boolean;
}) {
  const isBusy = bro.status === "busy";

  if (!isBusy) {
    if (compact) {
      return (
        <div className="mt-2 space-y-1.5 lg:mt-4 lg:space-y-2.5">
          {bro.progressDetails.slice(0, 1).map((detail) => (
            <div
              key={detail}
              className="flex items-start gap-2 text-[12px] leading-5 text-muted-foreground lg:gap-2.5 lg:leading-6"
            >
              <div className={`mt-[7px] h-1.5 w-1.5 rounded-full lg:mt-[9px] ${talking ? "bg-primary/65" : "bg-muted-foreground/35"}`} />
              <MarkdownText className="text-muted-foreground">{detail}</MarkdownText>
            </div>
          ))}
        </div>
      );
    }

    return (
      <div
        className={`mt-5 rounded-[22px] border px-4 py-4 ${
          talking ? "border-primary/12 bg-primary/6" : "border-white/80 bg-[hsl(var(--paper))]"
        }`}
      >
        <div className="text-[10px] uppercase tracking-normal text-muted-foreground">Current state</div>
        <div className={`serif-flow mt-3 text-[21px] leading-tight tracking-normal ${talking ? "text-primary" : "text-foreground"}`}>
          {bro.taskTitle}
        </div>
        <div className="mt-2 text-[12px] leading-6 text-muted-foreground">
          {bro.idleNote}
        </div>

        <div className="mt-4 space-y-2.5">
          {bro.progressDetails.map((detail) => (
            <div
              key={detail}
              className="flex items-start gap-2.5 text-[12px] leading-6 text-muted-foreground"
            >
              <div className={`mt-[9px] h-1.5 w-1.5 rounded-full ${talking ? "bg-primary/65" : "bg-muted-foreground/35"}`} />
              <MarkdownText className="text-muted-foreground">{detail}</MarkdownText>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div
      className={compact
        ? "mt-4"
        : `mt-5 rounded-[22px] border px-4 py-4 ${
            talking ? "border-primary/12 bg-primary/6" : "border-white/80 bg-[hsl(var(--paper))]"
          }`
      }
    >
      {!compact ? (
        <>
          <div className="flex items-center justify-between gap-3">
            <div className="text-[10px] uppercase tracking-normal text-muted-foreground">Current task</div>
            <div className={`text-[11px] ${talking ? "text-primary" : "text-muted-foreground"}`}>
              {bro.progressLabel}
            </div>
          </div>

          <div className={`serif-flow mt-3 text-[21px] leading-tight tracking-normal ${talking ? "text-primary" : "text-foreground"}`}>
            {bro.taskTitle}
          </div>
        </>
      ) : null}

      <div className={`${compact ? "" : "mt-4"} h-1.5 w-full overflow-hidden rounded-full ${talking ? "bg-primary/14" : "bg-border/70"}`}>
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${bro.progress}%` }}
        />
      </div>

      {bro.progressDetails.length > 0 ? <div className="mt-2 space-y-1.5 lg:mt-4 lg:space-y-2.5">
        {bro.progressDetails.map((detail) => (
          <div
            key={detail}
            className="flex items-start gap-2 text-[12px] leading-5 text-muted-foreground lg:gap-2.5 lg:leading-6"
          >
            <div className={`mt-[7px] h-1.5 w-1.5 rounded-full lg:mt-[9px] ${talking ? "bg-primary/65" : "bg-muted-foreground/35"}`} />
            <MarkdownText className="text-muted-foreground">{detail}</MarkdownText>
          </div>
        ))}
      </div> : null}
    </div>
  );
}
