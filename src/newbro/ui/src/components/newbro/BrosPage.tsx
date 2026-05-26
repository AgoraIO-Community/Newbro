/**
 * BrosPage — management view for worker bro prompts and bindings.
 * Keeps the Newbro visual language while exposing executor-node assignment.
 */

import { useEffect, useState } from "react";
import { Plus, Pencil, Trash2, Link2, Server } from "lucide-react";
import {
  createPersona,
  deletePersona,
  listExecutorNodes,
  listPersonas,
  updatePersona,
} from "../../lib/session-client";
import { SectionHeader } from "./SectionHeader";
import { BroPortrait } from "./BroPortrait";
import type { BroCardModel, AvatarType } from "./types";
import type { ExecutorNodeRecord, Persona } from "../../types";

function nodeStateLabel(persona: Persona, nodesById: Map<string, ExecutorNodeRecord>) {
  if (!persona.executor_node_id) {
    return "unbound";
  }
  const node = nodesById.get(persona.executor_node_id);
  if (node?.connection_status === "connected") {
    return "live";
  }
  return "bound offline";
}

function nodeStateClasses(persona: Persona, nodesById: Map<string, ExecutorNodeRecord>) {
  const state = nodeStateLabel(persona, nodesById);
  if (state === "live") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (state === "bound offline") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  return "border-[#e5e7eb] bg-[#f1f3f5] text-[#6b7280]";
}

const AVATAR_TYPES = ["fox", "cat", "bunny", "bro"] as const;

function BroForm({
  initial,
  nodes,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  initial?: { name: string; basePrompt: string; avatarType: string; executorNodeId: string | null };
  nodes: ExecutorNodeRecord[];
  onSubmit: (data: {
    name: string;
    basePrompt: string;
    avatarType: string;
    executorNodeId: string | null;
  }) => void;
  onCancel: () => void;
  submitLabel: string;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [basePrompt, setBasePrompt] = useState(initial?.basePrompt ?? "");
  const [avatarType, setAvatarType] = useState(initial?.avatarType ?? "fox");
  const [executorNodeId, setExecutorNodeId] = useState(initial?.executorNodeId ?? "");

  return (
    <div className="nb-card nb-form-card space-y-3 sm:px-6 sm:py-5">
      <input
        type="text"
        placeholder="Bro name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="command-field w-full px-4 py-2.5 text-[14px] text-[#111827] placeholder-[#9ca3af] outline-none transition focus:border-[#ffb89e] focus:ring-2 focus:ring-[#ff6a3d]/10"
      />

      <div className="flex flex-wrap gap-2">
        {AVATAR_TYPES.map((type) => (
          <button
            key={type}
            type="button"
            onClick={() => setAvatarType(type)}
            className={`nb-toggle-chip ${avatarType === type ? "nb-toggle-chip-active" : ""}`}
          >
            {type}
          </button>
        ))}
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 text-[12px] uppercase tracking-normal text-[#9ca3af]">
          <Link2 className="h-3.5 w-3.5" strokeWidth={1.8} />
          Executor Node
        </div>
        <select
          value={executorNodeId}
          onChange={(e) => setExecutorNodeId(e.target.value)}
          className="command-field w-full px-4 py-2.5 text-[14px] text-[#111827] outline-none transition focus:border-[#ffb89e] focus:ring-2 focus:ring-[#ff6a3d]/10"
        >
          <option value="">Unbound</option>
          {nodes.map((node) => (
            <option key={node.node_id} value={node.node_id}>
              {node.name} · {node.connection_status === "connected" ? "live" : "offline"}
            </option>
          ))}
        </select>
        <div className="text-[12px] leading-5 text-[#6b7280]">
          Unbound Bros stay dark until you attach them to a local executor node.
        </div>
      </div>

      <textarea
        placeholder="Base prompt — personality and instructions for this worker"
        value={basePrompt}
        onChange={(e) => setBasePrompt(e.target.value)}
        rows={2}
        className="command-field w-full px-4 py-3 text-[14px] text-[#111827] placeholder-[#9ca3af] outline-none transition focus:border-[#ffb89e] focus:ring-2 focus:ring-[#ff6a3d]/10"
      />

      <div className="flex flex-col gap-2 sm:flex-row">
        <button
          onClick={() =>
            onSubmit({
              name: name.trim(),
              basePrompt,
              avatarType,
              executorNodeId: executorNodeId || null,
            })
          }
          disabled={!name.trim()}
          className="nb-page-primary-action"
        >
          {submitLabel}
        </button>
        <button
          onClick={onCancel}
          className="nb-secondary-action"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Worker Bro Row                                                    */
/* ------------------------------------------------------------------ */

const VALID_AVATARS = new Set<string>(["fox", "cat", "bunny", "bro"]);

function personaToBroCard(persona: Persona): BroCardModel {
  const avatarType: AvatarType = VALID_AVATARS.has(persona.avatar) ? (persona.avatar as AvatarType) : "bro";
  return {
    id: persona.persona_id,
    name: persona.name,
    role: "",
    status: "idle",
    liveState: "unbound",
    executorNodeId: persona.executor_node_id,
    nodeName: null,
    avatarType,
    taskTitle: "",
    progress: 0,
    progressLabel: "",
    progressDetails: [],
    idleNote: "",
    source: "runtime",
  };
}

function BroRow({
  persona,
  nodesById,
  onEdit,
  onDelete,
}: {
  persona: Persona;
  nodesById: Map<string, ExecutorNodeRecord>;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const avatarType = VALID_AVATARS.has(persona.avatar) ? persona.avatar : "bro";
  const node = persona.executor_node_id ? nodesById.get(persona.executor_node_id) : null;
  const nodeState = nodeStateLabel(persona, nodesById);

  return (
    <div className="nb-card nb-list-card flex flex-col gap-4 sm:flex-row sm:items-center sm:px-5">
      <BroPortrait bro={personaToBroCard(persona)} talking={false} />

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <div className="text-[15px] font-medium tracking-normal text-[#111827]">
            {persona.name}
          </div>
          <div className="nb-chip nb-chip-muted uppercase">
            {avatarType}
          </div>
          <div
            className={`nb-chip uppercase ${nodeStateClasses(persona, nodesById)}`}
          >
            {nodeState}
          </div>
        </div>
        {persona.base_prompt ? (
          <div className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-neutral-500">
            {persona.base_prompt}
          </div>
        ) : (
          <div className="mt-1 text-[12px] italic text-neutral-400">No prompt configured</div>
        )}
        <div className="mt-3 flex min-w-0 items-center gap-2 text-[12px] text-neutral-500">
          <Server className="h-3.5 w-3.5 text-neutral-400" strokeWidth={1.8} />
          <span className="min-w-0 break-words">
            {node
              ? `${node.name} · ${node.connection_status === "connected" ? "connected" : "offline"}`
              : "No executor node bound"}
          </span>
        </div>
      </div>

      <div className="flex w-full shrink-0 gap-1.5 self-end sm:w-auto sm:self-auto">
        <button
          onClick={onEdit}
          className="nb-icon-action"
          aria-label={`Edit ${persona.name}`}
        >
          <Pencil className="h-3.5 w-3.5" strokeWidth={1.8} />
        </button>
        <button
          onClick={onDelete}
          className="nb-icon-action nb-danger-action"
          aria-label={`Delete ${persona.name}`}
        >
          <Trash2 className="h-3.5 w-3.5" strokeWidth={1.8} />
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main BrosPage                                                     */
/* ------------------------------------------------------------------ */

export function BrosPage({
  sessionId,
  initialPersonas,
  initialNodes,
}: {
  sessionId: string;
  initialPersonas: Persona[];
  initialNodes: ExecutorNodeRecord[];
}) {
  const [personas, setPersonas] = useState<Persona[]>(initialPersonas);
  const [nodes, setNodes] = useState<ExecutorNodeRecord[]>(initialNodes);
  const [mode, setMode] = useState<"list" | "add" | "edit">("list");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    setPersonas(initialPersonas);
  }, [initialPersonas]);

  useEffect(() => {
    setNodes(initialNodes);
  }, [initialNodes]);

  async function refreshData() {
    try {
      const [loadedPersonas, loadedNodes] = await Promise.all([
        listPersonas(sessionId),
        listExecutorNodes(sessionId),
      ]);
      setPersonas(Array.isArray(loadedPersonas) ? loadedPersonas : []);
      setNodes(Array.isArray(loadedNodes) ? loadedNodes : []);
      setError(null);
    } catch (e: unknown) {
      const detail = e instanceof Error ? e.message : "Could not refresh Bro data.";
      setError(`${detail} Showing the latest shell snapshot instead.`);
    }
  }

  useEffect(() => {
    void refreshData();
  }, [sessionId]);

  async function handleCreate(data: {
    name: string;
    basePrompt: string;
    avatarType: string;
    executorNodeId: string | null;
  }) {
    setError(null);
    setStatus(null);
    try {
      await createPersona(sessionId, {
        name: data.name,
        avatar: data.avatarType,
        base_prompt: data.basePrompt,
        executor_node_id: data.executorNodeId,
      });
      setMode("list");
      setStatus("Bro created.");
      await refreshData();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create");
    }
  }

  async function handleUpdate(data: {
    name: string;
    basePrompt: string;
    avatarType: string;
    executorNodeId: string | null;
  }) {
    if (!editingId) return;
    setError(null);
    setStatus(null);
    try {
      await updatePersona(sessionId, editingId, {
        name: data.name,
        avatar: data.avatarType,
        base_prompt: data.basePrompt,
        executor_node_id: data.executorNodeId,
      });
      setMode("list");
      setEditingId(null);
      setStatus("Bro updated.");
      await refreshData();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update");
    }
  }

  async function handleDelete(personaId: string) {
    setError(null);
    setStatus(null);
    try {
      await deletePersona(sessionId, personaId);
      setStatus("Bro removed.");
      await refreshData();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  function startEdit(persona: Persona) {
    setEditingId(persona.persona_id);
    setMode("edit");
  }

  const nodesById = new Map(nodes.map((node) => [node.node_id, node]));
  const liveCount = personas.filter((persona) => nodeStateLabel(persona, nodesById) === "live").length;

  return (
    <div className="dt-main-pad">
      <section className="dt-home-main">
        <div className="dt-page-head">
          <div>
            <div className="dt-detail-crumb">
              <span>Workspace</span>
              <span className="dt-detail-crumb-sep">/</span>
              <span className="dt-detail-crumb-cur">Bros</span>
            </div>
            <h1 className="dt-h1 mt-3">Worker Bros</h1>
            <p className="dt-sub">Manage worker personas, prompts, avatars, and their executor-node bindings.</p>
          </div>
          <div className="dt-page-actions">
            <span className="dt-home-chip dt-home-chip-calm">
              <span className="dt-home-chip-dot" />
              {personas.length} configured
            </span>
            <span className="dt-home-chip dt-home-chip-info">
              <span className="dt-home-chip-dot" />
              {liveCount} live
            </span>
          {!editingId && mode !== "add" && (
            <button
              onClick={() => {
                setMode("add");
                setEditingId(null);
                setError(null);
                setStatus(null);
              }}
              className="dt-page-action-primary"
            >
              <Plus strokeWidth={2} />
              New Bro
            </button>
          )}
          </div>
        </div>

        <div className="space-y-5 sm:space-y-6">
          <div className="hidden lg:block">
            <div className="command-label text-[#9ca3af]">
              Worker Prompts / Node Bindings
            </div>
          </div>
          <SectionHeader title="Prompts and bindings" />

          {error && (
            <div className="nb-status-banner nb-status-banner-error">
              {error}
            </div>
          )}
          {status && (
            <div className="nb-status-banner nb-status-banner-success">
              {status}
            </div>
          )}

          {mode === "add" && (
            <div>
              <BroForm
                nodes={nodes}
                submitLabel="Create"
                onSubmit={handleCreate}
                onCancel={() => setMode("list")}
              />
            </div>
          )}

          <div className="space-y-3">
            {personas.length === 0 && mode !== "add" ? (
              <div className="nb-empty-state">
                <div>No worker bros yet.</div>
                <div className="mt-1">
                  Create one, then bind it to a node to bring it live.
                </div>
              </div>
            ) : (
              personas.map((persona) =>
                editingId === persona.persona_id ? (
                  <BroForm
                    key={persona.persona_id}
                    nodes={nodes}
                    initial={{
                      name: persona.name,
                      basePrompt: persona.base_prompt || "",
                      avatarType: VALID_AVATARS.has(persona.avatar) ? persona.avatar : "bro",
                      executorNodeId: persona.executor_node_id,
                    }}
                    submitLabel="Save"
                    onSubmit={handleUpdate}
                    onCancel={() => {
                      setEditingId(null);
                      setMode("list");
                    }}
                  />
                ) : (
                  <BroRow
                    key={persona.persona_id}
                    persona={persona}
                    nodesById={nodesById}
                    onEdit={() => startEdit(persona)}
                    onDelete={() => handleDelete(persona.persona_id)}
                  />
                ),
              )
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
