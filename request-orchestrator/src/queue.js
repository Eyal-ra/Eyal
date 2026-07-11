// File-backed FIFO queue of approved requests. Persisted so a crash never loses
// or double-runs a request. Single-writer (the orchestrator process) + atomic rename.
import { readFileSync, writeFileSync, renameSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { DATA_DIR } from "./config.js";

const QUEUE_FILE = join(DATA_DIR, "approved-queue.json");

// status: "pending" -> "running" -> "done" | "failed"
function load() {
  if (!existsSync(QUEUE_FILE)) return [];
  try {
    return JSON.parse(readFileSync(QUEUE_FILE, "utf8"));
  } catch {
    return [];
  }
}

function save(items) {
  mkdirSync(DATA_DIR, { recursive: true });
  const tmp = QUEUE_FILE + ".tmp";
  writeFileSync(tmp, JSON.stringify(items, null, 2));
  renameSync(tmp, QUEUE_FILE); // atomic on same filesystem
}

export function enqueue(request) {
  const items = load();
  if (items.some((i) => i.id === request.id && i.status !== "failed")) {
    return { added: false, reason: "duplicate-id" }; // idempotent: never enqueue same live request twice
  }
  items.push({
    ...request,
    status: "pending",
    enqueuedAt: new Date().toISOString(),
    claimedAt: null,
    finishedAt: null,
    sessionId: null,
    sessionUrl: null,
    result: null,
    error: null,
  });
  save(items);
  return { added: true };
}

// Claim the oldest pending item (FIFO). Returns null if none / something already running.
export function claimNext(maxConcurrency) {
  const items = load();
  const running = items.filter((i) => i.status === "running").length;
  if (running >= maxConcurrency) return null; // enforce no-overlap
  const next = items.find((i) => i.status === "pending");
  if (!next) return null;
  next.status = "running";
  next.claimedAt = new Date().toISOString();
  save(items);
  return next;
}

export function markSession(id, { sessionId, sessionUrl }) {
  patch(id, { sessionId, sessionUrl });
}

export function markDone(id, result) {
  patch(id, { status: "done", result: result ?? null, finishedAt: new Date().toISOString() });
}

export function markFailed(id, error) {
  patch(id, { status: "failed", error: String(error), finishedAt: new Date().toISOString() });
}

function patch(id, fields) {
  const items = load();
  const it = items.find((i) => i.id === id);
  if (it) Object.assign(it, fields);
  save(items);
}

export function all() {
  return load();
}
