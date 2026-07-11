# מסמך העברה — מערכת הבקשות → סשן Claude אוטומטי

עודכן: 11.07.2026 · נכתב בסשן ענן (Claude Code on the web) בזמן שאייל ישן.

## המטרה (מהבקשה של אייל)

> "הציפייה שלי שאוכל לאשר בקשות ולגבי כל בקשה יהיה אוטומט סשן בקלוד … בצורה חכמה ונכונה,
> ושלא יקרה מצב שסשן אחד מתלבש על אחר. שתהיה איזושהי אינטגרציה."

## מה נבנה (מוכן ובדוק)

| רכיב | קובץ | מצב |
|------|------|-----|
| תור בקשות מאושרות (FIFO, נשמר לדיסק, crash-safe) | `src/queue.js` | ✅ + טסטים |
| סריאליזציה — בקשה אחת בכל רגע (`MAX_CONCURRENCY=1`) | `src/orchestrator.js` | ✅ + טסטים |
| נעילת מופע-יחיד | `src/lock.js` | ✅ |
| timeout לסשן תקוע (ברירת מחדל שעה) | `src/orchestrator.js` | ✅ |
| API: `POST /approve`, `GET /status` | `src/server.js` | ✅ smoke |
| לוח בקשות/סשנים בעברית (מתעדכן לבד) | `public/dashboard.html` | ✅ הדגמה נשלחה |
| Adapter ענן (Claude Code Remote) | `src/adapters/ccrApi.js` | ⚠️ TODO אחד (endpoint) |
| Adapter מקומי (`claude -p`) | `src/adapters/localCli.js` | ✅ |
| Adapter דמה (בדיקות/הדגמה) | `src/adapters/mock.js` | ✅ + טסטים |

בדיקות: `node --test` → 5/5 עוברים. הדגמה חיה עם `ADAPTER=mock` רצה מקצה-לקצה
(אישור → תור → סשן → done) והלוח הציג את המצב.

## הזרימה

```
/requests (פורט 3000)  →(אישור: POST /approve)→  תור  →  orchestrator (concurrency=1)  →  סשן Claude  →  /status  →  לוח בעברית
```

## מה צריך ממך כדי לעלות לאוויר (3 דברים)

1. **פרטי Claude Code Remote API** — כתובת + טוקן + `env id`, ל-`.env`
   (`CCR_API_URL`, `CCR_API_TOKEN`, `CCR_ENV_ID`). יש `TODO` אחד ב-`ccrApi.js` על ה-endpoint המדויק
   של יצירת סשן — צריך לאמת מול התיעוד שלך. **עד אז אפשר להריץ כבר היום עם `ADAPTER=localCli`**
   (הרצה מקומית על EYAL) או `ADAPTER=mock` (הדגמה).
2. **hook בצד `/requests`** — שורת `fetch("http://localhost:4500/approve", …)` בכפתור "אשר"
   (קוד מלא ב-`README.md`).
3. **ייצוא הבקשות הקיימות** (JSON/CSV) — כדי שאעבור על הפתוחות, תגובות לברינה/לך, וניסוחים לא-ברורים.
   הסשן בענן לא מגיע ל-localhost:3000.

## איך להריץ עכשיו (בלי שום פרט חסר)

```bash
cd request-orchestrator
cp .env.example .env         # ADAPTER=mock כדי לראות את הלוח עובד
node src/index.js            # פותח http://localhost:4500 (לוח) + API
# בטרמינל אחר:
curl -X POST http://localhost:4500/approve -H "Content-Type: application/json" \
  -d '{"id":"T1","title":"בדיקה","requester":"אייל"}'
# פתח בדפדפן http://localhost:4500 — הבקשה תופיע ותעבור pending→running→done
```

## החלטות עיצוב

- **למה תור-קובץ ולא ישר API?** כדי שאישור לא ילך לאיבוד אם ה-orchestrator לא רץ רגע,
  וכדי שקריסה באמצע לא תריץ בקשה פעמיים (כל פריט מקבל `claimedAt`).
- **למה concurrency=1?** זו הדרישה המפורשת שלך — "שלא יתלבש סשן על סשן". ניתן להגדיל ב-.env
  אם תרצה מקביליות מבוקרת בעתיד.
- **למה adapters?** כדי שאותה לוגיקה תרוץ גם בענן (CCR) וגם מקומית (CLI) בלי לשכתב —
  והבחירה היא שורה אחת ב-.env.

## פתוח לשיקולך (לא בוצע בכוונה)

- לא יצרתי טריגר/סשן חי ב-Claude Code Remote — לא רציתי להריץ אוטומציה חיה בלי אישורך
  (כלל: לא לגעת במערכת חיה בלי תיאום). ברגע שתיתן אור — אפעיל בזהירות.
