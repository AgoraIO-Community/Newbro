import { motion } from "framer-motion";
import { useEffect, useRef } from "react";
import type { ConversationHistoryEntry } from "../../types";
import { SectionHeader } from "./SectionHeader";

export function ConversationMemory({
  phase,
  messages,
  error,
  lastToolkitMessage,
}: {
  phase: "idle" | "loading" | "connected" | "error";
  messages: ConversationHistoryEntry[];
  error: string | null;
  lastToolkitMessage: string | null;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const messageItems = messages.filter((item) => Boolean(item.text?.trim()));
  const showMetaChips = messageItems.length > 0;

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
  }, [phase, messageItems.length]);

  return (
    <div data-testid="conversation-memory" className="flex min-h-0 flex-1 flex-col gap-4">
      <SectionHeader
        title="Interaction memory"
        trailing={
          showMetaChips ? (
            <div className="flex items-center gap-2">
              {messageItems.length > 0 ? (
                <div className="rounded-full border border-white/80 bg-white/76 px-3 py-1 text-[11px] text-muted-foreground">
                  {messageItems.length} turns
                </div>
              ) : null}
            </div>
          ) : null
        }
      />

      <div
        ref={viewportRef}
        className="subtle-scrollbar min-h-[220px] flex-1 overflow-y-auto pr-1 md:min-h-[280px] xl:min-h-[340px]"
      >
        {phase === "error" && messageItems.length === 0 ? (
          <div className="serif-flow px-2 py-6 text-[17px] leading-8 text-[#8d5a62]">
            {error ?? lastToolkitMessage ?? "Voice session failed to start."}
          </div>
        ) : messageItems.length === 0 ? (
          <div className="serif-flow flex h-full min-h-[220px] items-center justify-center text-center text-[18px] leading-9 text-muted-foreground md:min-h-[240px] xl:min-h-[280px]">
            Transcript will appear here.
          </div>
        ) : (
          <div className="space-y-4 pb-1">
            {messageItems.map((item, index) => {
              const localSpeaker = item.role === "user";
              return (
                <motion.div
                  key={`${item.message_id}-${index}`}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.22, ease: "easeOut" }}
                  className={localSpeaker ? "pl-8 md:pl-14" : "pr-8 md:pr-14"}
                >
                  <div
                    className={`rounded-[22px] border px-4 py-3 ${
                      localSpeaker
                        ? "rounded-tr-md border-white/80 bg-white/82 shadow-[0_18px_40px_-34px_rgba(15,23,42,0.18)]"
                        : "rounded-tl-md border-white/80 bg-[hsl(var(--paper))] shadow-[0_18px_40px_-34px_rgba(15,23,42,0.12)]"
                    }`}
                  >
                    <div className="mb-2 text-[10px] uppercase tracking-normal text-muted-foreground">
                      {item.role === "user" ? "Me" : "NewBro"}
                    </div>
                    <div className="serif-flow whitespace-pre-wrap text-[15px] leading-7 text-foreground/92">
                      {item.text}
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
