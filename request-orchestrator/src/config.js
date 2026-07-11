// Minimal .env loader (no external deps) + typed config accessors.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, isAbsolute } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
export const ROOT = join(here, "..");
export const DATA_DIR = join(ROOT, "data");

function loadDotEnv() {
  try {
    const raw = readFileSync(join(ROOT, ".env"), "utf8");
    for (const line of raw.split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (m && process.env[m[1]] === undefined) {
        process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
      }
    }
  } catch {
    // no .env file — rely on real environment variables
  }
}
loadDotEnv();

export const config = {
  adapter: process.env.ADAPTER || "ccrApi",
  port: Number(process.env.PORT || 4500),
  maxConcurrency: Math.max(1, Number(process.env.MAX_CONCURRENCY || 1)),
  pollIntervalMs: Number(process.env.POLL_INTERVAL_MS || 15000),
  // A session running longer than this is force-failed so the queue never wedges.
  sessionTimeoutMs: Number(process.env.SESSION_TIMEOUT_MS || 60 * 60 * 1000),
  ccr: {
    apiUrl: process.env.CCR_API_URL || "",
    apiToken: process.env.CCR_API_TOKEN || "",
    envId: process.env.CCR_ENV_ID || "",
  },
  claudeCli: process.env.CLAUDE_CLI || "claude",
  // Where the persisted queue lives. Overridable (mainly so tests can isolate).
  queueFile: process.env.QUEUE_FILE
    ? (isAbsolute(process.env.QUEUE_FILE) ? process.env.QUEUE_FILE : join(ROOT, process.env.QUEUE_FILE))
    : join(DATA_DIR, "approved-queue.json"),
};
