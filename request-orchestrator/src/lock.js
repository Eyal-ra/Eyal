// Single-instance lock so two orchestrator processes never run the queue at once.
import { openSync, closeSync, unlinkSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { DATA_DIR } from "./config.js";

const LOCK_FILE = join(DATA_DIR, "orchestrator.lock");

export function acquire() {
  try {
    // "wx" fails if the file already exists — atomic lock creation.
    const fd = openSync(LOCK_FILE, "wx");
    writeFileSync(fd, String(process.pid));
    closeSync(fd);
    return true;
  } catch {
    // Stale lock? If the recorded PID is gone, reclaim it.
    if (existsSync(LOCK_FILE)) {
      const pid = Number(readFileSync(LOCK_FILE, "utf8"));
      if (pid && !isAlive(pid)) {
        unlinkSync(LOCK_FILE);
        return acquire();
      }
    }
    return false;
  }
}

export function release() {
  try {
    unlinkSync(LOCK_FILE);
  } catch {
    /* already gone */
  }
}

function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
