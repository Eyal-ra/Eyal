// Adapter: run the request as a local headless Claude CLI session on the office
// machine. Fully self-contained (no cloud API needed). The orchestrator controls
// concurrency, so serialization is guaranteed regardless of adapter.
import { spawn } from "node:child_process";
import { config } from "../config.js";

const sessions = new Map(); // sessionId -> { state, output }

export async function createSession(prompt, meta) {
  const sessionId = `local-${meta?.id ?? Date.now()}`;
  const child = spawn(config.claudeCli, ["-p", prompt], {
    shell: process.platform === "win32",
  });
  const entry = { state: "running", output: "" };
  sessions.set(sessionId, entry);

  child.stdout.on("data", (d) => (entry.output += d.toString()));
  child.stderr.on("data", (d) => (entry.output += d.toString()));
  child.on("close", (code) => {
    entry.state = code === 0 ? "done" : "failed";
  });
  child.on("error", () => (entry.state = "failed"));

  return { sessionId, sessionUrl: null };
}

export async function getStatus(sessionId) {
  return sessions.get(sessionId)?.state || "failed";
}
