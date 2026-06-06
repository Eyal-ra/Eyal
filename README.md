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

## דשבורד פנימי (web)

בנוסף ל-CLI יש דשבורד web פנימי לצוות, עם מסך כניסה, הצגת שם המשתמש המחובר בכל עמוד, וכפתור יציאה.

### הפעלה

```bash
python -m src.dashboard
```

ההגדרות נקראות מתוך `config.yaml` (סעיף `dashboard`).

### הגדרת משתמשים

כל משתמש מוגדר ב-`config.yaml` עם `username`, `display_name` ו-`password_hash`.
ליצירת hash לסיסמה:

```bash
python -m src.dashboard.hash_password
```

הדביקו את הפלט לשדה `password_hash`. (לנוחות אפשר גם `password` בטקסט גלוי, אך פחות מומלץ.)

כשעובד נכנס - שמו המלא מוצג בראש כל עמוד ("מחובר/ת כ: ...") כך שברור לכל אחד באיזה
משתמש הוא מחובר, ולצדו כפתור **יציאה** שמנתק ומחזיר למסך הכניסה.

### כתובת ידידותית (במקום מספר/IP ארוך)

כדי שעובד יוכל לרשום בדפדפן כתובת פשוטה כמו `http://cpateam-dash` במקום מספר IP ופורט,
הריצו פעם אחת על מחשב השרת (בהרשאת מנהל):

```bash
# Windows (PowerShell כ-Administrator) או Linux/Mac (sudo)
python scripts/setup_hostname.py
```

הסקריפט מוסיף לקובץ ה-hosts מיפוי של השם `cpateam-dash` לכתובת המחשב.

- **גישה מקומית בלבד:** ברירת המחדל ממפה ל-`127.0.0.1`.
- **גישה לעובדים אחרים ברשת:** הריצו עם כתובת ה-IP של מחשב השרת ברשת המקומית, והריצו
  את אותו הסקריפט על כל מחשב עובד (או הגדירו זאת בשרת ה-DNS הפנימי):

  ```bash
  python scripts/setup_hostname.py --name cpateam-dash --ip 192.168.1.50
  ```

הפעלה על פורט 80 (ברירת המחדל ב-`config.yaml`) מאפשרת כתובת ללא מספר פורט כלל:
פשוט `http://cpateam-dash`.

## מצב הפרויקט - מה מוכן ומה חסר

| רכיב | סטטוס |
|------|--------|
| מבנה פרויקט + CLI | מוכן |
| Jotform client | מוכן (דורש API key) |
| Matcher לפי שם+טלפון/ת.ז. | מוכן |
| הצגת diff וקבלת אישור | מוכן |
| State store (הגשות שכבר טופלו) | מוכן |
| דשבורד web (כניסה / יציאה / משתמש מחובר) | מוכן |
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
  dashboard/         - דשבורד web פנימי (Flask): כניסה, יציאה, הצגת המשתמש המחובר
scripts/
  setup_hostname.py  - הגדרת כתובת ידידותית (cpateam-dash) בקובץ ה-hosts
```
