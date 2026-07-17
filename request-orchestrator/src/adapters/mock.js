// Adapter: simulate a Claude session that finishes after a short delay. Lets you
// exercise the full approve -> queue -> run -> done pipeline (and the dashboard)
// with no CCR API and no Claude CLI. Select with ADAPTER=mock.
const sessions = new Map(); // sessionId -> finishAt (ms epoch-ish via counter)

let clock = 0; // monotonic counter; we avoid Date.now() so tests stay deterministic
const DEFAULT_STEPS = 2; // getStatus calls before the session reports "done"

export async function createSession(_prompt, meta) {
  const sessionId = `mock-${meta?.id ?? ++clock}`;
  sessions.set(sessionId, DEFAULT_STEPS);
  return { sessionId, sessionUrl: `mock://session/${sessionId}` };
}

export async function getStatus(sessionId) {
  const left = sessions.get(sessionId);
  if (left === undefined) return "failed";
  if (left <= 0) return "done";
  sessions.set(sessionId, left - 1);
  return "running";
}
