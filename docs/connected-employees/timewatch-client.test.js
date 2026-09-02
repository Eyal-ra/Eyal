const { extractDayTimes, minutesSince } = require('./timewatch-client.js');
let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}
const d = new Date(2026, 8, 2); // 2/9/2026

// Realistic month page: date | entry | exit | total, today still open.
const month = `<table>
<tr class="tr"><td>01/09/2026</td><td>08:31</td><td>17:02</td><td>8:31</td></tr>
<tr class="tr"><td>02/09/2026</td><td>09:04</td><td>&nbsp;</td><td>3:30</td></tr>
<tr class="tr"><td>03/09/2026</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>
</table>`;

eq('open day: total cell is NOT an exit', extractDayTimes(month, d), {entry:'09:04', exit:null, found:true});
eq('closed day', extractDayTimes(month, new Date(2026,8,1)), {entry:'08:31', exit:'17:02', found:true});
eq('empty day', extractDayTimes(month, new Date(2026,8,3)), {entry:null, exit:null, found:true});
eq('day not in page', extractDayTimes(month, new Date(2026,8,25)), {entry:null, exit:null, found:false});

// Early starter whose accrued total exceeds the entry clock time.
const early = `<table>
<tr class="tr"><td>01/09/2026</td><td>06:00</td><td>15:00</td><td>9:00</td></tr>
<tr class="tr"><td>02/09/2026</td><td>06:00</td><td>&nbsp;</td><td>7:15</td></tr>
</table>`;
eq('early starter, total > entry', extractDayTimes(early, d), {entry:'06:00', exit:null, found:true});

// Layout with a leading employee-name column.
const shifted = `<table>
<tr class="tr"><td>ויולטה</td><td>01/09/2026</td><td>08:00</td><td>16:00</td><td>8:00</td></tr>
<tr class="tr"><td>ויולטה</td><td>02/09/2026</td><td>08:12</td><td>&nbsp;</td><td>2:00</td></tr>
</table>`;
eq('shifted columns self-calibrate', extractDayTimes(shifted, d), {entry:'08:12', exit:null, found:true});

// No closed day anywhere -> fall back to order of appearance.
eq('uncalibratable falls back', extractDayTimes('<tr class="tr"><td>02/09/2026</td><td>07:15</td><td>&nbsp;</td></tr>', d), {entry:'07:15', exit:null, found:true});
eq('single-digit date format', extractDayTimes('<tr class="tr"><td>2.9.2026</td><td>07:15</td></tr>', d), {entry:'07:15', exit:null, found:true});
eq('config override wins', extractDayTimes('<tr><td>02/09/2026</td><td>9:00</td><td>08:00</td><td>17:30</td></tr>', d, [2,3]), {entry:'08:00', exit:'17:30', found:true});
eq('minutesSince 09:04 -> 12:34', minutesSince('09:04', new Date(2026,8,2,12,34)), 210);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
