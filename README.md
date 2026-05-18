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
