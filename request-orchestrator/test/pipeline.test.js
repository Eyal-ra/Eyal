// End-to-end: approve -> queue -> orchestrator tick -> mock session -> done.
// Uses the mock adapter and a tiny poll interval so it runs fast.
process.env.ADAPTER = "mock";
process.env.POLL_INTERVAL_MS = "5";
process.env.SESSION_TIMEOUT_MS = "10000";
process.env.QUEUE_FILE = "data/test-pipeline-queue.json";

import { test } from "node:test";
import assert from "node:assert/strict";
import { rmSync, mkdirSync } from "node:fs";
import { join } from "node:path";

// Dynamic import so the env vars above are set BEFORE config.js reads them
// (static imports are hoisted and would run first).
const { DATA_DIR } = await import("../src/config.js");
rmSync(join(DATA_DIR, "approved-queue.json"), { force: true });
mkdirSync(DATA_DIR, { recursive: true });

const { enqueue, all } = await import("../src/queue.js");
const { tick } = await import("../src/orchestrator.js");

test("approved request runs to done via the mock adapter", async () => {
  enqueue({ id: "P1", title: "בדיקת פייפליין", body: "do it", requester: "אייל" });
  await tick(); // claims P1, runs the mock session to completion
  const it = all().find((i) => i.id === "P1");
  assert.equal(it.status, "done");
  assert.ok(it.sessionId && it.sessionId.startsWith("mock-"));
  assert.ok(it.finishedAt);
});

test("a second request waits until the first is finished (serialized)", async () => {
  enqueue({ id: "P2", title: "שני" });
  enqueue({ id: "P3", title: "שלישי" });
  await tick(); // P2
  await tick(); // P3
  const done = all().filter((i) => ["P2", "P3"].includes(i.id) && i.status === "done");
  assert.equal(done.length, 2);
});
