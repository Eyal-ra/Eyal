# Sync Customer Updates

שני כלים חצי-אוטומטיים למשרד:

1. **סנכרון עדכוני לקוח** בין **Jotform** (טופס הגשה אונליין), **Powerlink** (CRM בענן)
   ו**רבגונית** (תוכנת דסקטופ Windows).
2. **סוכן ווטסאפ** - מזהה למי טרם הגבת, ומציע לו שתי אפשרויות לפגישה מחר.

## איך זה עובד

1. הלקוח ממלא טופס Jotform עם הפרטים המעודכנים שלו.
2. הסקריפט מושך הגשות חדשות מ-Jotform API.
3. עבור כל הגשה - הסקריפט משווה את הערכים מול Powerlink ורבגונית.
4. אם יש פער, הסקריפט מציג את ההפרשים בטרמינל ומבקש אישור (`y/n/s`).
5. באישור - מעדכן את שתי המערכות:
   - **Powerlink** - דרך REST API
   - **רבגונית** - דרך אוטומציית GUI (`pywinauto`)

## דרישות

- Windows (לאוטומציית רבגונית)
- Python 3.10+
- API key ל-Jotform
- Token ל-Powerlink
- רבגונית מותקנת מקומית

## התקנה

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# ב-Windows נדרש גם tzdata - הוא כלול ב-requirements.txt

copy config.example.yaml config.yaml
# ערוך את config.yaml והכנס את הפרטים שלך
```

## שימוש

```bash
python -m src.main
```

הסקריפט יציג כל הגשה חדשה ויבקש אישור לפני עדכון.

## מצב הפרויקט - מה מוכן ומה חסר

| רכיב | סטטוס |
|------|--------|
| מבנה פרויקט + CLI | מוכן |
| Jotform client | מוכן (דורש API key) |
| Matcher לפי שם+טלפון/ת.ז. | מוכן |
| הצגת diff וקבלת אישור | מוכן |
| State store (הגשות שכבר טופלו) | מוכן |
| Powerlink client | **סטאב** - יש להשלים לפי תיעוד ה-API |
| רבגונית GUI automation | **סטאב** - דורש בדיקה מקומית להתאמת selectors |
| סוכן ווטסאפ - זיהוי "טרם הגבתי" | מוכן (נבדק מול שרת מדומה) |
| סוכן ווטסאפ - הצעת 2 אפשרויות + זיהוי תשובה | מוכן (נבדק מול שרת מדומה) |
| סוכן ווטסאפ - חיבור ל-Google Calendar | מוכן, דורש `credentials.json` והרצת `calendar` |
| סוכן ווטסאפ - התאמת נתיבי הבריג' | דורש הרצת `probe` מול `http://eyal:3980/` |

---

# סוכן ווטסאפ - למי טרם הגבתי + תיאום פגישות למחר

## מה זה עושה

1. סורק את השיחות האחרונות בווטסאפ דרך הבריג' המקומי (`http://eyal:3980/`).
2. מסמן כל שיחה שההודעה האחרונה בה היא **שלהם** ולא ענית אחריה - כלומר ממתינה לתשובה.
3. מציע לכל אחד מהם **שתי אפשרויות** לפגישה מחר, ושולח הודעה אחת בווטסאפ.
4. הלקוח עונה "1" או "2", והסוכן מזהה מה נבחר ושולח אישור.

הסוכן לא קובע כלום לבד - הוא מציע שתי אפשרויות, ואתה מאשר כל הודעה לפני שליחה
(אלא אם הרצת עם `--yes`).

## שימוש

```bash
python -m src.whatsapp_agent probe                 # בדיקה איזה נתיבים הבריג' חושף
python -m src.whatsapp_agent pending               # דוח: למי טרם הגבת
python -m src.whatsapp_agent schedule --dry-run    # להציג את ההודעות בלי לשלוח
python -m src.whatsapp_agent schedule              # שליחה, עם אישור y/n לכל לקוח
python -m src.whatsapp_agent replies --confirm     # מי ענה, מה בחר, ושליחת אישור
python -m src.whatsapp_agent agenda                # מה נקבע דרך הסוכן למחר
python -m src.whatsapp_agent calendar              # מה תפוס ביומן ומה יוצע
```

דגלים שימושיים:

- `--only "דנה"` - לעבוד מול לקוח אחד (שם, טלפון או chat id).
- `--limit 5` - להגביל את מספר הפניות בהרצה אחת.
- `--json` (ב-`pending`) - פלט לעיבוד אוטומטי.
- `--dry-run` - להציג בדיוק מה היה נשלח, בלי לשלוח.

## מה הסוכן לא יעשה

- לא ישלח בלי אישור שלך, אלא אם הרצת `--yes`.
- לא ישלח הצעה שנייה למי שכבר קיבל הצעה ב-`resend_after_hours` האחרונות.
- לא יציע שעות חדשות למי שכבר קבע פגישה, גם אם ימשיך לכתוב.
- לא יענה לבד כשהתשובה לא חד-משמעית - הוא יסמן "טפל ידנית".
- לא ישלח רצף הודעות מהיר: יש השהיה של `send_delay_seconds` (עם ג'יטר) בין
  הודעות, כדי להקטין סיכון לחסימה של המספר.

כל הודעה שנשלחת נרשמת ב-`state/whatsapp_sent.log` (שורת JSON להודעה),
וכל ההצעות והתשובות נשמרות ב-`state/whatsapp_proposals.json`.

## איך נקראת התשובה של הלקוח

`replies` מזהה `1`/`2`, `א`/`ב`, "אפשרות 2", וגם שעה או חלק מהיום בתשובה קצרה
("בעשר", "ב-15:00", "בבוקר"). תשובה שלילית ("שתיהן לא מתאימות") מקבלת שאלה חוזרת
מתי כן נוח. כל השאר מסומן לטיפול ידני - עדיף שהסוכן ישתוק מלנחש.

## הגדרה ראשונה

הנתיבים ושמות השדות משתנים בין בריג'ים (WPPConnect / whatsapp-web.js / Green API),
ולכן הכל יושב ב-`config.yaml`. סדר הפעולות:

1. ודא שהבריג' רץ ומחובר (סריקת QR).
2. הרץ `python -m src.whatsapp_agent probe` - הוא ינסה את הנתיבים הנפוצים ויציג
   מי החזיר תשובה ואילו שדות יש בה.
3. העתק את הנתיב ושמות השדות שעבדו אל `whatsapp.endpoints` ב-`config.yaml`.
4. הרץ `pending` כדי לוודא שהרשימה נראית נכון, ורק אז `schedule`.

אם כל הנתיבים חוזרים 404, `probe` יראה גם מה השרת עונה על `/`, `/health`,
`/sessions` וכדומה - משם בדרך כלל מזהים איזה בריג' זה. הרבה בריג'ים (WPPConnect,
WAHA, Evolution) דורשים שם session בתוך הנתיב; הגדר אותו ב-`whatsapp.session`
והשתמש ב-`{session}` בתוך `endpoints`, למשל `/api/{session}/all-chats`.

הקליינט מזהה לבד את שמות השדות הנפוצים (`fromMe`/`key.fromMe`, `body`/`message.conversation`,
`timestamp` בשניות או במילישניות), כך שברוב המקרים מספיק לכוון את הנתיבים.

## חיבור ליומן

`scheduling.calendar.provider` קובע מאיפה הסוכן יודע מה תפוס:

| provider | מה זה עושה | מה צריך |
|----------|-------------|---------|
| `none` | כל השעות ב-`option_times` נחשבות פנויות | כלום |
| `file` | קובץ JSON מקומי של שעות תפוסות | קובץ `busy_file` |
| `outlook` | האאוטלוק שמותקן במחשב הזה, דרך COM | Outlook מותקן ומחובר |
| `graph` | Microsoft 365 דרך הרשת | רישום אפליקציה ב-Azure |
| `google` | free/busy מ-Google Calendar | הרשאה חד-פעמית |

### הפעלת Outlook (הדרך הקצרה)

אם Outlook מותקן ומחובר במחשב שמריץ את הסוכן, זה כל מה שצריך:

```yaml
scheduling:
  calendar:
    provider: "outlook"
    include_tentative: true
```

```bash
python -m src.whatsapp_agent calendar
```

בלי רישום, בלי Azure, בלי הרשאות מנהל. הסוכן קורא את היומן הראשי של הפרופיל,
מדלג על אירועים שמסומנים "פנוי" (למשל "X לא במשרד"), ומתייחס ל"אולי" כתפוס
(`include_tentative: false` כדי לשנות).

### הפעלת Microsoft Graph (להרצה מרחוק או מתוזמנת)

עובד גם כשאאוטלוק סגור ומכל מחשב, אבל דורש רישום חד-פעמי:

```bash
pip install -r requirements-outlook.txt
```

ב-Azure Portal → App registrations → New registration → Public client, הוסף
הרשאת **Calendars.Read** (או `Calendars.ReadWrite` אם רוצים יצירת אירועים), והעתק
את ה-Application ID:

```yaml
scheduling:
  calendar:
    provider: "graph"
    client_id: "APP_ID_FROM_AZURE"
    tenant_id: "cpateam.co.il"
    calendar_id: "eyal@cpateam.co.il"
```

בהרצה הראשונה יודפס קוד להזנה ב-microsoft.com/devicelogin, והטוקן נשמר.

### הפעלת Google Calendar

```bash
pip install -r requirements-google.txt
```

ב-Google Cloud Console: צור פרויקט, הפעל את **Google Calendar API**, וצור
**OAuth client ID** מסוג *Desktop app*. הורד את ה-JSON ושמור כ-`credentials.json`.
אז ב-`config.yaml`:

```yaml
scheduling:
  calendar:
    provider: "google"
    calendar_id: "eyal@cpateam.co.il"
    credentials_file: "credentials.json"
    token_file: "state/google_token.json"
    create_events: false
```

אם הפגישות מפוזרות על כמה יומנים (יומן אישי + יומן משרד משותף), `calendar_id`
מקבל גם רשימה - הסוכן ימזג את התפוסים מכולם ויציע רק שעה שפנויה בכל אחד מהם.
`write_calendar_id` קובע לאן ייווצרו אירועים (ברירת מחדל: הראשון ברשימה).

בהרצה הראשונה ייפתח דפדפן לאישור, והטוקן יישמר ב-`token_file` - אחריה זה עובד
בלי התערבות. להרצה מתוזמנת בשרת אפשר במקום זה `service_account_file` של service
account עם domain-wide delegation (הוא יתחזה ל-`calendar_id`).

לבדיקה, כמו `probe` לבריג':

```bash
python -m src.whatsapp_agent calendar        # מה תפוס ומה יוצע ללקוחות
```

`create_events: true` יגרום לסוכן ליצור אירוע ביומן ברגע שלקוח מאשר שעה
(דורש הרשאת כתיבה). ברירת המחדל כבויה - הסוכן רק קורא.

## שעות הפגישות

נקבעות ב-`config.yaml` תחת `scheduling`:

- `option_times` - רשימת שעות מועדפות. שתי הראשונות שפנויות הן מה שיוצע.
- `skip_weekdays` - ברירת מחדל שישי ושבת, ולכן "מחר" של יום חמישי מתגלגל ליום ראשון.
- `lookahead_days` - אם אין שתי אפשרויות פנויות מחר, ההצעות מתגלגלות ליום שאחריו
  (ההודעה תמיד מציינת את התאריך המדויק).
- `resend_after_hours` - לא נשלחת הצעה חוזרת לאותו לקוח בתוך X שעות.
- `apology_after_hours` - מעל כמה שעות המתנה ההודעה נפתחת בהתנצלות על העיכוב.
- טקסטים: `opening_line`, `opening_line_late`, `closing_line`, `no_fit_line`,
  `location_line`, `signature`.

## מבנה הקוד

```
src/
  main.py            - CLI של סנכרון הלקוחות
  jotform_client.py  - מושך הגשות מ-Jotform
  powerlink_client.py- קורא/מעדכן לקוח ב-Powerlink (stub)
  ravgonit_gui.py    - מעדכן לקוח ברבגונית דרך pywinauto (stub)
  matcher.py         - זיהוי לקוח בין מערכות
  diff_display.py    - הצגת השוואה ובקשת אישור
  state_store.py     - שמירת היסטוריית הגשות שכבר טופלו

  whatsapp_agent.py  - CLI של הסוכן (pending / schedule / replies / agenda / calendar / probe)
  whatsapp_client.py - קליינט HTTP לבריג' הווטסאפ (retry + קצב שליחה + probe)
  unanswered.py      - הלוגיקה של "למי טרם הגבתי"
  slots.py           - בניית שתי אפשרויות הפגישה למחר
  templates.py       - נוסח ההודעה בעברית וזיהוי התשובה
  proposal_store.py  - אילו הצעות כבר נשלחו, מי ענה ומה נקבע
  calendar_source.py - מה תפוס: none / קובץ מקומי / Google Calendar
  audit_log.py       - לוג של כל הודעה שנשלחה
```

## טסטים

```bash
pip install -r requirements-dev.txt
pytest -q
```

הטסטים כוללים שרת HTTP שמדמה את הבריג', כך שכל המסלול -
`pending` → `schedule` → `replies` → `agenda` - נבדק מקצה לקצה בלי ווטסאפ אמיתי.
אותם טסטים רצים ב-GitHub Actions על כל דחיפה (`.github/workflows/ci.yml`).
