/**
 * SkillPicker — reusable skill catalog picker UI.
 *
 * Ported from:
 *   prototypes/design/variants-desktop.jsx  (SKILL_DEFAULT_ICON, DTSkillMenu, DTComposerBar lead cluster)
 *   prototypes/design/variants-mobile.jsx   (ThrSkillSheet)
 *
 * Exports:
 *   SKILL_DEFAULT_ICON       — generic skill glyph JSX
 *   filterSkills             — filter helper used by menu + inline "/" trigger
 *   DesktopSkillMenu         — popover list (ports DTSkillMenu)
 *   MobileSkillSheet         — bottom sheet (ports ThrSkillSheet)
 *   SkillLeadCluster         — desktop chip↔pill + popover wrapper
 */

import React, { useEffect, useRef, useState } from "react";
import type { ExecutorSkill } from "../../types";

// ─────────────────────────────────────────────────────────────
// Default icon — used for every row (no per-skill icons in the
// real catalog, unlike the prototype's hardcoded list).
// ─────────────────────────────────────────────────────────────
export const SKILL_DEFAULT_ICON = (
  <svg
    viewBox="0 0 24 24"
    width="13"
    height="13"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.9"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M12 3l1.9 4.7L19 9l-4.1 2.3L13 16l-1-4.5L7 9l4.1-1.3z" />
    <path d="M19 15l.7 1.8L21.5 18l-1.8.7L19 21l-.7-2.3L16.5 18l1.8-1.2z" />
  </svg>
);

// ─────────────────────────────────────────────────────────────
// filterSkills — matches display_name, name, and description
// (case-insensitive). Empty query returns all.
// ─────────────────────────────────────────────────────────────
export function filterSkills(skills: ExecutorSkill[], query: string): ExecutorSkill[] {
  const q = query.trim().toLowerCase();
  if (!q) return skills;
  return skills.filter((s) =>
    (s.display_name + " " + s.name + " " + s.description).toLowerCase().includes(q)
  );
}

// ─────────────────────────────────────────────────────────────
// Prop interfaces
// ─────────────────────────────────────────────────────────────
interface SkillMenuProps {
  skills: ExecutorSkill[];
  query: string;
  selected: ExecutorSkill | null;
  broName: string;
  onChoose: (skill: ExecutorSkill) => void;
  onClose: () => void;
}

interface MobileSkillSheetProps extends SkillMenuProps {
  open: boolean;
}

export interface SkillLeadClusterProps {
  skills: ExecutorSkill[];
  selected: ExecutorSkill | null;
  broName: string;
  disabled?: boolean;
  onChoose: (skill: ExecutorSkill) => void;
  onClear: () => void;
}

// ─────────────────────────────────────────────────────────────
// DesktopSkillMenu — popover that floats above the composer's
// lead cluster. Ports DTSkillMenu from variants-desktop.jsx.
// ─────────────────────────────────────────────────────────────
export function DesktopSkillMenu({
  skills,
  query = "",
  selected,
  broName = "Atlas",
  onChoose,
  onClose,
}: SkillMenuProps) {
  const list = filterSkills(skills, query);

  return (
    <div className="dt-skill-pop" role="menu" aria-label="Run with a skill">
      <div className="dt-skill-pop-head">
        <span className="dt-skill-pop-title">Run with a skill</span>
        <span className="dt-skill-pop-hint">
          {query ? (
            <>
              filtering <span className="dt-skill-pop-q">/{query}</span>
            </>
          ) : (
            <>choose a skill</>
          )}
        </span>
      </div>
      {list.length === 0 ? (
        <div className="dt-skill-empty">
          No skill matches &ldquo;{query}&rdquo;. Just send and {broName} figures it out.
        </div>
      ) : (
        <ul className="dt-skill-pop-list">
          {list.map((s) => {
            const on = selected != null && selected.name === s.name;
            const isDisabled = s.enabled === false;
            return (
              <li key={s.name}>
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={!!on}
                  disabled={isDisabled}
                  className={[
                    "dt-skill-opt",
                    on ? "dt-skill-opt-on" : "",
                    isDisabled ? "dt-skill-opt-disabled" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => {
                    if (!isDisabled) onChoose(s);
                  }}
                >
                  <span className="dt-skill-opt-ic" aria-hidden="true">
                    {SKILL_DEFAULT_ICON}
                  </span>
                  <span className="dt-skill-opt-body">
                    <span className="dt-skill-opt-name">{s.display_name}</span>
                    <span className="dt-skill-opt-desc">{s.description}</span>
                  </span>
                  {on && (
                    <svg
                      className="dt-skill-opt-check"
                      viewBox="0 0 24 24"
                      width="14"
                      height="14"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <path d="M4 12.5L10 18L20 6" />
                    </svg>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="dt-skill-pop-foot">
        <span>Skills shape how {broName} works the turn</span>
        <kbd className="dt-kbd" onClick={onClose}>
          esc
        </kbd>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// MobileSkillSheet — bottom sheet. Ports ThrSkillSheet from
// variants-mobile.jsx. Mounts always; the open class drives
// the slide-up transform.
// ─────────────────────────────────────────────────────────────
export function MobileSkillSheet({
  open,
  skills,
  query = "",
  selected,
  broName = "Atlas",
  onChoose,
  onClose,
}: MobileSkillSheetProps) {
  const list = filterSkills(skills, query);

  return (
    <>
      <div
        className={`thr-skill-backdrop${open ? " thr-skill-backdrop-open" : ""}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className={`thr-skill-sheet${open ? " thr-skill-sheet-open" : ""}`}
        role="dialog"
        aria-label="Run with a skill"
        aria-hidden={!open}
      >
        <div className="thr-skill-grip" aria-hidden="true" />
        <header className="thr-skill-head">
          <div className="thr-skill-head-text">
            <div className="thr-skill-title">Run with a skill</div>
            <div className="thr-skill-sub">
              {query ? (
                <>
                  filtering <span className="thr-skill-q">/{query}</span>
                </>
              ) : (
                <>shapes how {broName} works this turn</>
              )}
            </div>
          </div>
          <button
            type="button"
            className="thr-skill-close"
            onClick={onClose}
            aria-label="Close"
          >
            <svg
              viewBox="0 0 24 24"
              width="18"
              height="18"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </header>
        {list.length === 0 ? (
          <div className="thr-skill-empty">
            No skill matches &ldquo;{query}&rdquo;.<br />
            Just send and {broName} figures it out.
          </div>
        ) : (
          <ul className="thr-skill-list">
            {list.map((s) => {
              const on = selected != null && selected.name === s.name;
              const isDisabled = s.enabled === false;
              return (
                <li key={s.name}>
                  <button
                    type="button"
                    disabled={isDisabled}
                    className={[
                      "thr-skill-opt",
                      on ? "thr-skill-opt-on" : "",
                      isDisabled ? "thr-skill-opt-disabled" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    onClick={() => {
                      if (!isDisabled) onChoose(s);
                    }}
                    aria-pressed={!!on}
                  >
                    <span className="thr-skill-opt-ic" aria-hidden="true">
                      {SKILL_DEFAULT_ICON}
                    </span>
                    <span className="thr-skill-opt-body">
                      <span className="thr-skill-opt-name">{s.display_name}</span>
                      <span className="thr-skill-opt-desc">{s.description}</span>
                    </span>
                    {on ? (
                      <span className="thr-skill-opt-check" aria-hidden="true">
                        <svg
                          viewBox="0 0 24 24"
                          width="15"
                          height="15"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.6"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="M4 12.5L10 18L20 6" />
                        </svg>
                      </span>
                    ) : (
                      <span className="thr-skill-opt-go" aria-hidden="true">
                        <svg
                          viewBox="0 0 24 24"
                          width="16"
                          height="16"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="M9 6l6 6-6 6" />
                        </svg>
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// SkillLeadCluster — desktop composer chip↔pill + popover
// wrapper. Owns skillOpen state. Ports the leadCluster JSX
// from DTComposerBar in variants-desktop.jsx.
//
// Does NOT own the "/" inline trigger — that lives in the
// composer (Task 18). Only chip/pill + click-to-open + outside-
// click/Escape close.
// ─────────────────────────────────────────────────────────────
export function SkillLeadCluster({
  skills,
  selected,
  broName = "Atlas",
  disabled = false,
  onChoose,
  onClear,
}: SkillLeadClusterProps) {
  const [skillOpen, setSkillOpen] = useState(false);
  const leadRef = useRef<HTMLDivElement>(null);

  // Close on outside click.
  useEffect(() => {
    if (!skillOpen) return;
    const onDown = (e: MouseEvent) => {
      if (leadRef.current && !leadRef.current.contains(e.target as Node)) {
        setSkillOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [skillOpen]);

  // Close on Escape.
  useEffect(() => {
    if (!skillOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSkillOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [skillOpen]);

  if (disabled) return null;

  return (
    <div className="dt-cmp-lead" ref={leadRef}>
      {selected ? (
        <span className={`dt-cmp-skillpill${skillOpen ? " dt-cmp-skillpill-open" : ""}`}>
          <button
            type="button"
            className="dt-cmp-skillpill-body"
            onClick={() => setSkillOpen((o) => !o)}
            aria-haspopup="menu"
            aria-expanded={skillOpen}
            title={`Skill: ${selected.display_name} — click to change`}
          >
            <span className="dt-cmp-skillpill-ic" aria-hidden="true">
              {SKILL_DEFAULT_ICON}
            </span>
            <span className="dt-cmp-skillpill-name">{selected.display_name}</span>
          </button>
          <button
            type="button"
            className="dt-cmp-skillpill-x"
            onClick={onClear}
            aria-label={`Remove ${selected.display_name} skill`}
            title="Remove skill"
          >
            <svg
              viewBox="0 0 24 24"
              width="12"
              height="12"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </span>
      ) : (
        <button
          type="button"
          className={`dt-cmp-skillchip${skillOpen ? " dt-cmp-skillchip-open" : ""}`}
          onClick={() => setSkillOpen((o) => !o)}
          aria-haspopup="menu"
          aria-expanded={skillOpen}
          title="Run this turn with a skill"
        >
          <span className="dt-cmp-skillchip-ic" aria-hidden="true">
            {SKILL_DEFAULT_ICON}
          </span>
          <span className="dt-cmp-skillchip-label">Skill</span>
        </button>
      )}
      {skillOpen && (
        <DesktopSkillMenu
          skills={skills}
          query=""
          selected={selected}
          broName={broName}
          onChoose={(s) => {
            onChoose(s);
            setSkillOpen(false);
          }}
          onClose={() => setSkillOpen(false)}
        />
      )}
    </div>
  );
}
