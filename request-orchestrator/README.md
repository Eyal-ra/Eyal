# Request Orchestrator — אישור בקשה → סשן Claude אוטומטי

מנוע אינטגרציה שמחבר את **מערכת הבקשות** (מודול המשימות/בקשות ב-OfficeChatServer, פורט 3000,
`/requests`) ל-**Claude Code Remote**: כל בקשה שאייל מאשר יוצרת אוטומטית סשן Claude שמבצע אותה —
**בטור, בלי שסשן אחד יתלבש על אחר**.

## הזרימה

```
מערכת הבקשות (/requests, פורט 3000)
   │  אייל לוחץ "אשר"
   ▼
POST /approve  →  approved-queue.json  (תור FIFO, נשמר לדיסק)
   │
   ▼
Orchestrator loop  (MAX_CONCURRENCY = 1, נעילה)
   │  שולף את הבקשה הבאה → בונה prompt → adapter.createSession()
   ▼
Claude Code Remote — סשן ענן שמריץ את הבקשה
   │  polling לסטטוס עד done / failed
   ▼
results.json  (סטטוס + סיכום + קישור לסשן)  →  מערכת הבקשות מציגה סטטוס
```

## למה זה לא מתנגש

- ה-orchestrator מעבד **בקשה אחת בכל רגע** (`MAX_CONCURRENCY=1`). הבא בתור מתחיל רק אחרי
  שהקודם הגיע ל-`done`/`failed`.
- קובץ נעילה (`data/orchestrator.lock`) מונע שתי מופעים במקביל של ה-orchestrator עצמו.
- כל פריט בתור מקבל `claimedAt` — פריט "תפוס" לא נלקח שוב, כך שגם קריסה באמצע לא מריצה כפול.

## התקנה והרצה

```bash
cd request-orchestrator
npm install            # אין תלויות חיצוניות — רק Node 18+
cp .env.example .env   # מלא CCR_API_URL / CCR_API_TOKEN / CCR_ENV_ID
node src/index.js      # מריץ HTTP server (POST /approve, GET /status) + לולאת עיבוד
```

## החיבור למערכת הבקשות (הקוד שצריך להוסיף שם)

בכפתור "אשר" של `/requests`, אחרי שהבקשה מסומנת מאושרת, שלח אותה ל-orchestrator:

```js
await fetch("http://localhost:4500/approve", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    id: request.id,               // מזהה ייחודי מהמערכת
    title: request.title,         // כותרת הבקשה
    body: request.body,           // הטקסט המלא / מה לבצע
    system: request.system,       // שם המערכת (מהמרשם) — אופציונלי
    requester: request.requester, // מי ביקש (אייל / ברינה...) — אופציונלי
    acceptance: request.acceptance// קריטריון "בוצע" — אופציונלי אך מומלץ
  })
});
```

לתצוגת סטטוס: `GET http://localhost:4500/status` מחזיר את מצב כל הבקשות (ממתין / רץ / הושלם / נכשל).

## Adapters — איך נוצר הסשן

`src/adapters/` מפריד בין הלוגיקה לבין *איך* מריצים סשן Claude. שני מימושים:

| adapter | מתי | מה צריך |
|---|---|---|
| `localCli` (ברירת מחדל) | הרצה מקומית על מכונת המשרד דרך `claude -p` | ה-CLI של Claude מותקן על המכונה — בלי סודות |
| `ccrApi` | סשן בענן Claude Code Remote | `CCR_API_URL`, `CCR_API_TOKEN` ב-.env (`CCR_ENV_ID` כבר ממולא) |

בחירת adapter דרך `ADAPTER=ccrApi` / `ADAPTER=localCli` ב-.env.

## מה עוד צריך ממך (אייל) כדי לסגור את המעגל

1. **פרטי ה-API של Claude Code Remote** — כתובת + טוקן ליצירת סשן פרוגרמטית (למילוי ב-.env).
   *כרגע `ccrApi.js` מכיל את מבנה הקריאה עם TODO אחד במקום ה-endpoint המדויק.*
2. **ה-hook בצד `/requests`** — הוספת ה-`fetch` לכפתור "אשר" (הקוד למעלה).
3. **ייצוא הבקשות הקיימות** (JSON/CSV) — כדי שאעבור על הפתוחות, תגובות לברינה/לך, וניסוחים לא-ברורים.
   הסשן הזה בענן לא מגיע ל-localhost:3000 שלך.
