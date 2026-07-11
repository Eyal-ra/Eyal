// Entry point: acquire the single-instance lock, start the HTTP API, run the loop.
import { config } from "./config.js";
import { acquire, release } from "./lock.js";
import { startServer } from "./server.js";
import { start } from "./orchestrator.js";

if (!acquire()) {
  console.error("[index] another orchestrator instance is already running — exiting.");
  process.exit(1);
}

const server = startServer();
const stop = start();
console.log(`[index] request-orchestrator up (maxConcurrency=${config.maxConcurrency})`);

function shutdown() {
  console.log("[index] shutting down...");
  stop();
  server.close();
  release();
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
