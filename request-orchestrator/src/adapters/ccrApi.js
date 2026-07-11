// Adapter: create + poll a Claude Code Remote (cloud) session over its HTTP API.
//
// NOTE: the exact Claude Code Remote REST endpoints/shape must be filled in by Eyal
// (see the single TODO below). Everything around it — auth header, env id, polling,
// status mapping — is wired. Config comes from .env (CCR_API_URL/TOKEN/ENV_ID).
import { config } from "../config.js";

function assertConfigured() {
  const { apiUrl, apiToken, envId } = config.ccr;
  if (!apiUrl || !apiToken || !envId) {
    throw new Error(
      "ccrApi adapter not configured — set CCR_API_URL, CCR_API_TOKEN, CCR_ENV_ID in .env"
    );
  }
}

async function api(path, options = {}) {
  const res = await fetch(config.ccr.apiUrl.replace(/\/$/, "") + path, {
    ...options,
    headers: {
      Authorization: `Bearer ${config.ccr.apiToken}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`CCR API ${path} -> ${res.status} ${await res.text()}`);
  return res.json();
}

export async function createSession(prompt, meta) {
  assertConfigured();
  // TODO(eyal): confirm the create-session endpoint + payload for your CCR API.
  const data = await api("/v1/sessions", {
    method: "POST",
    body: JSON.stringify({
      environment_id: config.ccr.envId,
      prompt,
      name: meta?.title?.slice(0, 80) || "request",
    }),
  });
  return { sessionId: data.id, sessionUrl: data.url || null };
}

export async function getStatus(sessionId) {
  assertConfigured();
  const data = await api(`/v1/sessions/${sessionId}`);
  // Map the provider's state to our three states.
  const s = (data.state || data.status || "").toLowerCase();
  if (["completed", "done", "succeeded", "idle", "finished"].includes(s)) return "done";
  if (["failed", "error", "cancelled", "canceled"].includes(s)) return "failed";
  return "running";
}
