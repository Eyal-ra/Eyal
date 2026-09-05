const {
  extractDayPunches, minutesSince, punchColumnsFromHeader,
} = require('./timewatch-client.js');

let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}
const pick = (r) => ({ connected: r.connected, since: r.since, pairs: r.pairs, found: r.found });

// Replica of a.timewatch.co.il/update.php rows:
// date | type | dayname | standard | e1 | x1 | e2 | x2 | e3 | x3 | absence | notes | total
const page = `<table>
<tr><td>ג 01-09-2026</td><td>שלישי</td><td>8 שעות ו36 דקות</td><td>9:06</td>
    <td><img src="mobile.png">10:41</td><td><img src="person.png">19:00</td>
    <td></td><td></td><td></td><td></td><td></td><td></td><td>8:19</td></tr>
<tr><td>ד 02-09-2026</td><td>רביעי</td><td>8 שעות ו36 דקות</td><td>9:06</td>
    <td><img src="mobile.png">08:13</td><td><img src="mobile.png">17:03</td>
    <td></td><td></td><td></td><td></td><td></td><td></td><td>8:50</td></tr>
<tr><td>ה 03-09-2026</td><td>חמישי</td><td>7 ו36 דקות</td><td>8:06</td>
    <td></td><td></td><td></td><td></td><td></td><td></td><td></td><td>חסרה כניסה/יציאה</td><td></td></tr>
</table>`;

eq('closed day', pick(extractDayPunches(page, new Date(2026, 8, 1))),
  { connected: false, since: null, pairs: [{ entry: '10:41', exit: '19:00' }], found: true });
eq('standard and total hours are not punches', pick(extractDayPunches(page, new Date(2026, 8, 2))),
  { connected: false, since: null, pairs: [{ entry: '08:13', exit: '17:03' }], found: true });
eq('day with no punches', pick(extractDayPunches(page, new Date(2026, 8, 3))),
  { connected: false, since: null, pairs: [], found: true });
eq('day absent from page', pick(extractDayPunches(page, new Date(2026, 8, 20))),
  { connected: false, since: null, pairs: [], found: false });

// Stepped out and came back - a single-pair reader calls this "left for the day".
const back = `<table><tr><td>ד 02-09-2026</td><td>רביעי</td><td>8 שעות</td><td>9:06</td>
 <td>08:13</td><td>12:30</td><td>13:15</td><td></td><td></td><td></td><td></td><td></td><td>4:17</td></tr></table>`;
eq('back from a break, still in', pick(extractDayPunches(back, new Date(2026, 8, 2))),
  { connected: true, since: '13:15', pairs: [{ entry: '08:13', exit: '12:30' }, { entry: '13:15', exit: null }], found: true });

const out = `<table><tr><td>ד 02-09-2026</td><td>רביעי</td><td>8 שעות</td><td>9:06</td>
 <td>08:13</td><td>12:30</td><td></td><td></td><td></td><td></td><td></td><td></td><td>4:17</td></tr></table>`;
eq('out on a break right now', pick(extractDayPunches(out, new Date(2026, 8, 2))),
  { connected: false, since: null, pairs: [{ entry: '08:13', exit: '12:30' }], found: true });

const three = `<table><tr><td>ד 02-09-2026</td><td>ד</td><td>8</td><td>9:06</td>
 <td>07:00</td><td>09:00</td><td>10:00</td><td>12:00</td><td>13:00</td><td></td><td></td><td></td><td>4:00</td></tr></table>`;
eq('three pairs, open on the third', pick(extractDayPunches(three, new Date(2026, 8, 2))),
  { connected: true, since: '13:00', pairs: [{ entry: '07:00', exit: '09:00' }, { entry: '10:00', exit: '12:00' }, { entry: '13:00', exit: null }], found: true });

const morning = `<table><tr><td>ד 02-09-2026</td><td>ד</td><td>8</td><td>9:06</td>
 <td>09:04</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td>3:30</td></tr></table>`;
eq('in this morning, total already accruing', pick(extractDayPunches(morning, new Date(2026, 8, 2))),
  { connected: true, since: '09:04', pairs: [{ entry: '09:04', exit: null }], found: true });

const named = `<table><tr><td>ברינה</td><td>ד 02-09-2026</td><td>ד</td><td>8</td><td>9:06</td>
 <td>09:04</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td>3:30</td></tr></table>`;
eq('extra leading column does not shift the mapping', pick(extractDayPunches(named, new Date(2026, 8, 2))),
  { connected: true, since: '09:04', pairs: [{ entry: '09:04', exit: null }], found: true });

// The real update.php is hand-written HTML that never closes <tr> or <td>.
// A <tr>...</tr> matcher found two rows in a 150KB page - the filter bar,
// which happens to be well formed - and missed the attendance table entirely.
const loose = `<table><tr><td>\u05d1\u05e8\u05d9\u05e0\u05d4</table>
<table>
<tr><td>\u05d3 02-09-2026<td>\u05e8\u05d1\u05d9\u05e2\u05d9<td>8 \u05e9\u05e2\u05d5\u05ea<td>9:06
    <td><img src="mobile.png">08:13<td>12:30<td>13:15<td><td><td><td><td><td>4:17
<tr><td>\u05d4 03-09-2026<td>\u05d7\u05de\u05d9\u05e9\u05d9<td>8 \u05e9\u05e2\u05d5\u05ea<td>9:06
    <td><td><td><td><td><td><td><td><td>
</table>`;
eq('unclosed tr and td still parse', pick(extractDayPunches(loose, new Date(2026, 8, 2))),
  { connected: true, since: '13:15', pairs: [{ entry: '08:13', exit: '12:30' }, { entry: '13:15', exit: null }], found: true });
eq('unclosed row with no punches', pick(extractDayPunches(loose, new Date(2026, 8, 3))),
  { connected: false, since: null, pairs: [], found: true });

// Same day number in two different months must not cross-match.
const twoMonths = `<table><tr><td>\u05d3 02-08-2026<td>\u05d3<td>8<td>9:06<td>07:00<td>15:00<td><td><td><td><td><td><td>8:00
<tr><td>\u05d3 02-09-2026<td>\u05d3<td>8<td>9:06<td>09:04<td><td><td><td><td><td><td><td>3:30
</table>`;
eq('picks the right month', pick(extractDayPunches(twoMonths, new Date(2026, 8, 2))),
  { connected: true, since: '09:04', pairs: [{ entry: '09:04', exit: null }], found: true });

// When the page labels its own columns, believe the page rather than the
// layout this one account happens to have.
const headed = `<table>
<tr><th>\u05ea\u05d0\u05e8\u05d9\u05da<th>\u05d9\u05d5\u05dd<th>\u05e9\u05e2\u05d5\u05ea \u05ea\u05e7\u05df<th>\u05db\u05e0\u05d9\u05e1\u05d4<th>\u05d9\u05e6\u05d9\u05d0\u05d4<th>\u05db\u05e0\u05d9\u05e1\u05d4<th>\u05d9\u05e6\u05d9\u05d0\u05d4<th>\u05e1\u05d4"\u05db
<tr><td>\u05d3 02-09-2026<td>\u05e8\u05d1\u05d9\u05e2\u05d9<td>9:06<td>08:13<td>12:30<td>13:15<td><td>4:17
</table>`;
eq('the header names the punch columns', punchColumnsFromHeader(headed), [[3, 4], [5, 6]]);
eq('a header layout with fewer columns is read correctly',
  pick(extractDayPunches(headed, new Date(2026, 8, 2))),
  { connected: true, since: '13:15', pairs: [{ entry: '08:13', exit: '12:30' }, { entry: '13:15', exit: null }], found: true });

// The standard-hours column sits between the date and the first punch here,
// which the fixed offsets would have read as an entry.
eq('the header keeps standard hours out of the punches',
  extractDayPunches(headed, new Date(2026, 8, 2)).pairs.some((p) => p.entry === '9:06'), false);

eq('a page with no header falls back to the offsets', punchColumnsFromHeader(page), null);
eq('an explicit override beats the header',
  extractDayPunches(headed, new Date(2026, 8, 2), [[2, 3]]).pairs,
  [{ entry: '9:06', exit: '08:13' }]);

eq('minutesSince 09:04 -> 12:34', minutesSince('09:04', new Date(2026, 8, 2, 12, 34)), 210);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
