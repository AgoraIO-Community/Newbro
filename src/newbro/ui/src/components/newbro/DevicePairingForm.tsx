import { useState, type FormEvent } from "react";

export interface DevicePairingFormProps {
  onClaim: (userCode: string) => Promise<void>;
}

type Status = { kind: "idle" } | { kind: "ok" } | { kind: "error"; message: string };

export function DevicePairingForm({ onClaim }: DevicePairingFormProps) {
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const userCode = code.trim().toUpperCase();
    if (!userCode || pending) return;
    setPending(true);
    setStatus({ kind: "idle" });
    try {
      await onClaim(userCode);
      setStatus({ kind: "ok" });
      setCode("");
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "Pairing failed." });
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="nb-device-pairing">
      <label htmlFor="device-code">Device code</label>
      <input
        id="device-code"
        value={code}
        onChange={(event) => setCode(event.target.value)}
        autoComplete="off"
        maxLength={8}
        placeholder="e.g. 7QF2"
      />
      <button type="submit" disabled={pending}>
        {pending ? "Pairing…" : "Pair device"}
      </button>
      {status.kind === "ok" && <p role="status">Device paired.</p>}
      {status.kind === "error" && <p role="alert">{status.message}</p>}
    </form>
  );
}
