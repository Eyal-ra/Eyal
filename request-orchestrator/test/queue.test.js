// Verifies the core guarantee: with maxConcurrency=1, only one request is ever
// "running" at a time, claims are FIFO, and enqueue is idempotent per id.
process.env.QUEUE_FILE = "data/test-queue.json";

import { test } from "node:test";
import assert from "node:assert/strict";
import { rmSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

// Dynamic import so QUEUE_FILE above is read by config before the queue loads.
const { config, DATA_DIR } = await import("../src/config.js");
rmSync(config.queueFile, { force: true });
mkdirSync(dirname(config.queueFile), { recursive: true });

const { enqueue, claimNext, markDone, all } = await import("../src/queue.js");

test("enqueue is idempotent per id", () => {
  enqueue({ id: "A", title: "first" });
  const r = enqueue({ id: "A", title: "dup" });
  assert.equal(r.added, false);
  assert.equal(all().filter((i) => i.id === "A").length, 1);
});

test("claimNext enforces no-overlap and FIFO", () => {
  enqueue({ id: "B", title: "second" });
  const first = claimNext(1);
  assert.equal(first.id, "A"); // FIFO: A before B
  // A is now running -> nothing else can be claimed at concurrency 1
  assert.equal(claimNext(1), null);
  // finish A, then B becomes claimable
  markDone("A", "ok");
  const second = claimNext(1);
  assert.equal(second.id, "B");
});

test("running count never exceeds concurrency", () => {
  const running = all().filter((i) => i.status === "running").length;
  assert.ok(running <= 1);
});
