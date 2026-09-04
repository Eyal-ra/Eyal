'use strict';
/**
 * Dashboard routes:
 *   GET /api/connected-employees  - who is clocked in right now
 *   GET /api/presence-log         - today's arrivals and departures
 *
 * Mount on the existing dashboard server (EYAL only - see the COMPUTERNAME
 * guard in the start*.bat files). Credentials never leave the server: the
 * browser receives names and times only.
 *
 *   const { registerConnectedEmployees } = require('./connected-employees/server-endpoint');
 *   registerConnectedEmployees(app, {
 *     watchNames: ['ברינה'],
 *     notify: (event) => { ... your alert here, see README ... },
 *   });
 *
 * These routes expose where staff are, so mount them behind whatever already
 * gates the dashboard's private section - do not serve them to everyone.
 */

const { getConnectedEmployees, loadConfig } = require('./timewatch-client');
const { createWatcher } = require('./presence-watcher');

function registerConnectedEmployees(app, options = {}) {
  const cfg = options.config || loadConfig();
  const cacheMs = (options.cacheSeconds ?? 60) * 1000;
  const watcher = createWatcher({
    logDir: options.logDir || 'presence-log',
    watchNames: options.watchNames || cfg.watchNames,
    notify: options.notify,
  });

  let cache = { at: 0, payload: null };
  let inFlight = null;

  const fetchPresence = options.fetchPresence || getConnectedEmployees;

  async function refresh() {
    // Collapse concurrent dashboard refreshes into a single TimeWatch login.
    inFlight = inFlight || fetchPresence({ config: cfg })
      .finally(() => { inFlight = null; });
    const payload = await inFlight;
    // Only a successful read may move the watcher's state: treating a failed
    // fetch as "nobody is in" would fire a departure alert for everyone. A
    // warning is such a failure - it just came back resolved instead of
    // thrown, which makes it the easier one to get wrong.
    if (!payload.warning) watcher.update(payload.connected);
    cache = { at: Date.now(), payload };
    return payload;
  }

  app.get(options.path || '/api/connected-employees', async (req, res) => {
    res.set('cache-control', 'no-store');
    if (cache.payload && Date.now() - cache.at < cacheMs) {
      return res.json({ ...cache.payload, cached: true });
    }
    try {
      res.json({ ...(await refresh()), cached: false });
    } catch (err) {
      // Never leak credentials or upstream HTML into the dashboard.
      console.error('[connected-employees]', err);
      res.status(502).json({
        error: 'timewatch_unavailable', connected: [], away: [], errors: [], warning: null,
      });
    }
  });

  app.get(options.logPath || '/api/presence-log', (req, res) => {
    res.set('cache-control', 'no-store');
    try {
      res.json({ events: watcher.today() });
    } catch (err) {
      console.error('[presence-log]', err);
      res.status(500).json({ error: 'log_unavailable', events: [] });
    }
  });

  // Poll independently of anyone having the dashboard open, so an alert
  // arrives even when no browser is looking.
  if (options.pollSeconds) {
    const timer = setInterval(() => {
      refresh().catch((err) => console.error('[connected-employees] poll', err));
    }, options.pollSeconds * 1000);
    if (timer.unref) timer.unref();
  }

  return watcher;
}

module.exports = { registerConnectedEmployees };
