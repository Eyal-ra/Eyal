'use strict';
/**
 * Dashboard route: GET /api/connected-employees
 *
 * Mount on the existing dashboard server (EYAL only - see COMPUTERNAME guard
 * in the start*.bat files). Credentials never leave the server: the browser
 * receives names and times only.
 *
 * Usage in the dashboard server:
 *   const { registerConnectedEmployees } = require('./connected-employees/server-endpoint');
 *   registerConnectedEmployees(app);
 */

const { getConnectedEmployees, loadConfig } = require('./timewatch-client');

let cache = { at: 0, payload: null };
let inFlight = null;

function registerConnectedEmployees(app, options = {}) {
  const path = options.path || '/api/connected-employees';
  const cacheMs = (options.cacheSeconds ?? 60) * 1000;

  app.get(path, async (req, res) => {
    const now = Date.now();
    if (cache.payload && now - cache.at < cacheMs) {
      res.set('cache-control', 'no-store');
      return res.json({ ...cache.payload, cached: true });
    }
    try {
      // Collapse concurrent dashboard refreshes into a single TimeWatch login.
      inFlight = inFlight || getConnectedEmployees({ config: options.config || loadConfig() })
        .finally(() => { inFlight = null; });
      const payload = await inFlight;
      cache = { at: Date.now(), payload };
      res.set('cache-control', 'no-store');
      res.json({ ...payload, cached: false });
    } catch (err) {
      // Never leak credentials or upstream HTML into the dashboard.
      console.error('[connected-employees]', err);
      res.status(502).json({ error: 'timewatch_unavailable', connected: [], away: [], errors: [] });
    }
  });
}

module.exports = { registerConnectedEmployees };
