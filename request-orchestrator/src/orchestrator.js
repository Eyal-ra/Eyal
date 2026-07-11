// The processing loop: claim the next approved request, create ONE Claude session,
// wait for it to finish, record the result, then move on. Concurrency is capped at
// config.maxConcurrency (default 1) so sessions never overlap.
import { config } from "./config.js";
import { claimNext, markSession, markDone, markFailed } from "./queue.js";
import { buildPrompt } from "./prompt.js";

async function loadAdapter() {
  const name = config.adapter === "localCli" ? "localCli" : "ccrApi";
  return import(`./adapters/${name}.js`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let running = false;

export async function tick() {
  if (running) return; // guard against re-entrancy while a session is in flight
  const req = claimNext(config.maxConcurrency);
  if (!req) return;

  running = true;
  const adapter = await loadAdapter();
  try {
    const { sessionId, sessionUrl } = await adapter.createSession(buildPrompt(req), req);
    markSession(req.id, { sessionId, sessionUrl });
    console.log(`[orchestrator] started ${req.id} -> session ${sessionId}`);

    // Poll until the session reaches a terminal state.
    let state = "running";
    while (state === "running") {
      await sleep(config.pollIntervalMs);
      state = await adapter.getStatus(sessionId);
    }

    if (state === "done") {
      markDone(req.id, `session ${sessionId} completed`);
      console.log(`[orchestrator] done ${req.id}`);
    } else {
      markFailed(req.id, `session ${sessionId} ended as ${state}`);
      console.log(`[orchestrator] failed ${req.id}: ${state}`);
    }
  } catch (err) {
    markFailed(req.id, err);
    console.error(`[orchestrator] error on ${req.id}:`, err.message);
  } finally {
    running = false;
  }
}

// Start the loop. Returns a stop() function.
export function start() {
  let stopped = false;
  (async function loop() {
    while (!stopped) {
      await tick();
      await sleep(2000); // small idle poll between claims
    }
  })();
  return () => {
    stopped = true;
  };
}
