const http = require('http');
const { describeError, isTransient, httpFetch } = require('./timewatch-client.js');

let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}

// Node reports every network failure as the same three words and hides the
// reason in err.cause. "fetch failed" alone costs a round trip through a
// person every time it happens.
{
  const withCause = new TypeError('fetch failed');
  withCause.cause = Object.assign(new Error('getaddrinfo EAI_AGAIN a.timewatch.co.il'), { code: 'EAI_AGAIN' });
  eq('the cause reaches the message', describeError(withCause), 'fetch failed (EAI_AGAIN)');

  const noCode = new TypeError('fetch failed');
  noCode.cause = new Error('certificate has expired');
  eq('a cause without a code still says something',
    describeError(noCode), 'fetch failed (certificate has expired)');

  eq('a plain error is left alone', describeError(new Error('nope')), 'nope');
  eq('no duplication when the cause is already in the message',
    describeError(Object.assign(new Error('boom: ETIMEDOUT'), { cause: { code: 'ETIMEDOUT' } })),
    'boom: ETIMEDOUT');
}

{
  eq('a refused connection is transient',
    isTransient(Object.assign(new TypeError('fetch failed'), { cause: { code: 'ECONNREFUSED' } })), true);
  eq('a timeout is transient', isTransient(Object.assign(new Error('t'), { name: 'TimeoutError' })), true);
  // The server spoke; asking again will not change its mind.
  eq('an HTTP answer is not transient', isTransient(new Error('update.php returned 403')), false);
}

(async () => {
  const cfg = { requestTimeoutMs: 3000 };

  // A blip should not cost a poll: the alert this exists to send would be
  // delayed by a whole cycle.
  {
    let hits = 0;
    const server = await new Promise((resolve) => {
      const s = http.createServer((req, res) => {
        hits += 1;
        if (hits < 3) { req.socket.destroy(); return; }   // two blips, then fine
        res.end('ok');
      });
      s.listen(0, '127.0.0.1', () => resolve(s));
    });
    const url = `http://127.0.0.1:${server.address().port}/`;
    const res = await httpFetch(cfg, url, { retryDelayMs: 10 });
    eq('a transient failure is retried', [res.status, hits], [200, 3]);
    server.close();
  }

  // Nothing listening: every attempt fails, and the reason survives. The
  // port is one the OS just handed back, so it is closed rather than one of
  // the ports fetch refuses outright.
  {
    const closed = await new Promise((resolve) => {
      const s = http.createServer();
      s.listen(0, '127.0.0.1', () => {
        const { port } = s.address();
        s.close(() => resolve(port));
      });
    });
    let message = null;
    try {
      await httpFetch(cfg, `http://127.0.0.1:${closed}/`, { retryDelayMs: 5 });
    } catch (err) { message = err.message; }
    eq('giving up names the real reason, not "fetch failed"',
      /ECONNREFUSED/.test(message || ''), true);
  }

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
