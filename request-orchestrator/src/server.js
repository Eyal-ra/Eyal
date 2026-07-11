// Tiny HTTP API the /requests app talks to. No framework — Node's http only.
//   POST /approve  { id, title, body, system?, requester?, acceptance? }
//   GET  /status   -> current queue with per-request state
import { createServer } from "node:http";
import { config } from "./config.js";
import { enqueue, all } from "./queue.js";

function send(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { "Content-Type": "application/json; charset=utf-8" });
  res.end(body);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (c) => (data += c));
    req.on("end", () => {
      try {
        resolve(data ? JSON.parse(data) : {});
      } catch (e) {
        reject(e);
      }
    });
    req.on("error", reject);
  });
}

export function startServer() {
  const server = createServer(async (req, res) => {
    try {
      if (req.method === "POST" && req.url === "/approve") {
        const body = await readJson(req);
        if (!body.id || !body.title) {
          return send(res, 400, { ok: false, error: "id and title are required" });
        }
        const result = enqueue({
          id: String(body.id),
          title: String(body.title),
          body: body.body ? String(body.body) : "",
          system: body.system ? String(body.system) : null,
          requester: body.requester ? String(body.requester) : null,
          acceptance: body.acceptance ? String(body.acceptance) : null,
        });
        return send(res, result.added ? 202 : 200, { ok: true, ...result });
      }
      if (req.method === "GET" && req.url === "/status") {
        return send(res, 200, { ok: true, requests: all() });
      }
      send(res, 404, { ok: false, error: "not found" });
    } catch (err) {
      send(res, 500, { ok: false, error: String(err) });
    }
  });
  server.listen(config.port, () => {
    console.log(`[server] listening on http://localhost:${config.port}  (adapter=${config.adapter})`);
  });
  return server;
}
