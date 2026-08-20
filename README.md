# Sync Customer Updates

סקריפט חצי-אוטומטי לסנכרון עדכוני פרטי לקוח בין **Jotform** (טופס הגשה אונליין),
**Powerlink** (CRM בענן) ו**רבגונית** (תוכנת דסקטופ Windows).

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

## מבנה הקוד

```
src/
  main.py            - CLI entry point
  jotform_client.py  - מושך הגשות מ-Jotform
  powerlink_client.py- קורא/מעדכן לקוח ב-Powerlink (stub)
  ravgonit_gui.py    - מעדכן לקוח ברבגונית דרך pywinauto (stub)
  matcher.py         - זיהוי לקוח בין מערכות
  diff_display.py    - הצגת השוואה ובקשת אישור
  state_store.py     - שמירת היסטוריית הגשות שכבר טופלו
```

---

# ניתוב חשבוניות להוצאות (Invoice Router)

רכיב נוסף שמטרתו להפוך את העברת החשבוניות למודולי ההוצאות לאוטומטית.
חשבונית שמתקבלת צריכה להגיע ל"ספר" הנכון:

- העסק שלך (חברה) → `…@expense.co.il` (סאמיט)
- העצמאי שלך → `…@mail.paperless.tax` (Paperless)
- לקוח → `…@expense.co.il` / `…@invoice-maven.com` / `…@biziboxcpa.com`

## שלב 1 — לומד הניתוב (מוכן)

במקום לבנות טבלת ניתוב ביד, הסקריפט לומד אותה מההיסטוריה שלך: הוא סורק את
תיקיית **Sent Items**, ולכל העברה לכתובת קליטה (`@expense.co.il` וכו') מצליב
את שם הלקוח שמופיע בגוף (`לכבוד: <לקוח>` או פתיח ריווחית), ובונה מפה
`{לקוח → כתובת יעד}`. לקוח שנשלח ליותר מכתובת אחת מסומן כ"סתירה" להכרעה.

```bash
copy config.example.yaml config.yaml   # מלא graph.access_token
python -m src.invoice_learn --config config.yaml --since 2025-01-01T00:00:00Z
```

נוצרים `state/routing_map.yaml` (המפה לאישור) ו-`state/routing_report.md`
(סתירות + העברות שלא זוהה בהן לקוח). **בשלב זה כלום לא נשלח** — רק נלמדת המפה.

## מצב הרכיב

| שלב | סטטוס |
|------|--------|
| לומד ניתוב (Sent Items → מפה) | **מוכן** |
| מסווג חשבונית נכנסת (חילוץ לכבוד/ח.פ. → יעד) | **מוכן** (`invoice_classifier`) |
| חילוץ טקסט מ-PDF מצורף (לכבוד בקובץ) | **מוכן** (`invoice_attachments`, pdfminer) |
| ניתוב + שליחה בפועל (forward) | **מוכן** — הרצה יבשה; `--apply` דורש Mail.Send |
| סימון "✓ נשלח לסאמיט" בעת שליחה | **מוכן** — דורש Mail.ReadWrite ל-`--apply` |
| אימות חזרה של "קיבלנו"/"אישור קבלת" | **מוכן** (`invoice_verify`, קריאה בלבד) |
| זיהוי "התקבל אך לא נשלח" (מניעת פספוסים) | **מוכן** (`invoice_audit`, קריאה בלבד) |

## מבנה הקוד — Invoice Router

```
src/
  invoice_routing.py    - לוגיקה טהורה: חילוץ לקוח/ח.פ., בניית מפת ניתוב
  invoice_classifier.py - מחליט לאן חשבונית נכנסת הולכת (חברה/לקוח/לבדיקה)
  invoice_attachments.py- חילוץ טקסט מ-PDF/קבצים מצורפים (pdfminer, נופל רך)
  invoice_processor.py  - מעביר ליעד + מסמן "✓ נשלח לסאמיט" (פעולות מוזרקות)
  invoice_verifier.py   - מתאים העברות מול אישורי "קיבלנו"/"אישור קבלת"
  invoice_missing.py    - זיהוי חשבוניות שהתקבלו אך לא הועברו לאף ספר
  invoice_graph.py      - Microsoft Graph: קריאת Sent/Inbox + forward + סימון
  invoice_learn.py      - CLI: מושך Sent → לומד → כותב מפה+דוח לאישור
  invoice_process.py    - CLI: מושך Inbox → מנתב+שולח (יבש כברירת מחדל, --apply)
  invoice_verify.py     - CLI: מצליב הועבר↔אושר, מדווח על פערים (קריאה בלבד)
  invoice_audit.py      - CLI: מדווח "התקבל אך לא נשלח" (מניעת פספוסים, קריאה בלבד)
tests/
  test_invoice_routing.py    - בדיקות יחידה על מפת הניתוב
  test_invoice_classifier.py - בדיקות יחידה על הסיווג
  test_invoice_processor.py  - בדיקות יחידה על השליחה+הסימון
  test_invoice_verifier.py   - בדיקות יחידה על אימות הקליטה
  test_invoice_attachments.py- בדיקות יחידה על חילוץ הקבצים
  test_invoice_missing.py    - בדיקות יחידה על זיהוי הפספוסים
```

בדיקות רצות אוטומטית ב-GitHub Actions (`.github/workflows/ci.yml`).

מסמך הקמת ההרשאות מול Microsoft 365: ראה [`docs/microsoft365_setup.md`](docs/microsoft365_setup.md).
