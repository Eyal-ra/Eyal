# חיבור Microsoft 365 לסקריפט ניתוב החשבוניות

הסקריפט צריך גישה לתיבת המייל שלך כדי (א) **לקרוא** את הדואר היוצא וללמוד את
מפת הניתוב, ובהמשך (ב) **לשלוח/להעביר** חשבוניות ו**לסמן** מיילים כ"נשלח
לסאמיט". כאן מוסבר איך מקימים את ההרשאות.

יש שתי דרכים: **מהירה** (לבדיקת הלומד בלבד) ו**יציבה** (לאוטומציה שרצה לבד).

---

## דרך א' — מהירה, לבדיקת הלומד בלבד (קריאה)

מתאימה רק כדי להריץ `invoice_learn` פעם אחת ולראות את המפה. לא לפרודקשן
(הטוקן פג אחרי כ-שעה).

1. היכנס ל-**Graph Explorer**: https://developer.microsoft.com/graph/graph-explorer
2. התחבר עם המשתמש `eyal@cpateam.co.il`.
3. הרץ שאילתה כלשהי (למשל `GET /me/messages`) ואשר את ההרשאה `Mail.Read`.
4. ב-**Access token** העתק את הטוקן.
5. ב-`config.yaml`:
   ```yaml
   invoice_router:
     graph:
       access_token: "<הדבק כאן את הטוקן>"
   ```
6. הרץ: `python -m src.invoice_learn --config config.yaml --since 2025-01-01T00:00:00Z`

---

## דרך ב' — יציבה, לאוטומציה (App Registration)

זו הדרך הנכונה לסקריפט שרץ לבד על המחשב במשרד. דורש **הרשאת מנהל** ב-Microsoft 365.

### שלב 1 — יצירת רישום אפליקציה
1. היכנס ל-**Microsoft Entra admin center**: https://entra.microsoft.com
   (כמנהל — דרוש Global Admin / Application Admin).
2. תפריט: **Identity → Applications → App registrations → New registration**.
3. שם: למשל `Invoice Router`. Supported account types: **Single tenant**.
4. **Register**.
5. במסך האפליקציה העתק ושמור:
   - **Application (client) ID** → ל-`client_id`
   - **Directory (tenant) ID** → ל-`tenant_id`

### שלב 2 — יצירת סוד (Client secret)
1. בתוך האפליקציה: **Certificates & secrets → Client secrets → New client secret**.
2. תיאור + תוקף (מומלץ 12–24 חודשים).
3. **Add**, ומיד העתק את ה-**Value** (מוצג פעם אחת בלבד!) → ל-`client_secret`.

### שלב 3 — הוספת הרשאות Graph
1. **API permissions → Add a permission → Microsoft Graph**.
2. בחר **Application permissions** (לא Delegated — כי הסקריפט רץ ללא משתמש מחובר).
3. הוסף:
   - `Mail.Read` — קריאה (ללומד)
   - `Mail.Send` — שליחה/העברה
   - `Mail.ReadWrite` — סימון/תיוג ("✓ נשלח לסאמיט"), הזזה לתיקייה
4. לחץ **Grant admin consent for <הארגון>** ואשר. (חייב מנהל.)

### שלב 4 — ⚠️ הגבלת הגישה לתיבה שלך בלבד (חשוב מאוד)
כברירת מחדל, `Mail.Send`/`Mail.ReadWrite` כהרשאת אפליקציה נותנות גישה ל**כל**
התיבות בארגון. חובה לצמצם זאת לתיבה שלך בלבד, דרך **Application Access Policy**
ב-Exchange Online (PowerShell):

```powershell
# התקנה חד-פעמית
Install-Module ExchangeOnlineManagement -Scope CurrentUser
Connect-ExchangeOnline -UserPrincipalName eyal@cpateam.co.il

# מגביל את האפליקציה לתיבה של eyal בלבד
New-ApplicationAccessPolicy `
  -AppId "<APPLICATION_CLIENT_ID>" `
  -PolicyScopeGroupId eyal@cpateam.co.il `
  -AccessRight RestrictAccess `
  -Description "Invoice Router - eyal mailbox only"

# בדיקה שהמדיניות חלה
Test-ApplicationAccessPolicy -Identity eyal@cpateam.co.il -AppId "<APPLICATION_CLIENT_ID>"
```

> אם תרצה שהסקריפט יטפל גם בתיבות לקוחות בעתיד — מוסיפים אותן לקבוצה ומרחיבים
> את ה-policy. כרגע: תיבה אחת בלבד.

### שלב 5 — חיבור ל-config.yaml
```yaml
invoice_router:
  graph:
    tenant_id: "<Directory (tenant) ID>"
    client_id: "<Application (client) ID>"
    client_secret: "<Secret Value>"
    mailbox: "eyal@cpateam.co.il"
```
(`config.yaml` כבר ב-`.gitignore` — הסוד לא נכנס ל-git.)

### שלב 6 — תחזוקה
- ה-**Client secret פג** בתאריך שבחרת. שים תזכורת ביומן לחדש אותו לפני כן
  (אחרת הסקריפט יפסיק לעבוד).
- לביטול גישה מיידי: מוחקים את הסוד או את רישום האפליקציה.

---

## סיכום הרשאות

| הרשאה | למה משמשת | שלב באוטומציה |
|---|---|---|
| `Mail.Read` | לקרוא Sent Items, ללמוד ניתוב | לומד הניתוב (קיים) |
| `Mail.Send` | להעביר חשבונית ליעד | ניתוב+שליחה (הבא) |
| `Mail.ReadWrite` | לסמן "✓ נשלח לסאמיט" | אימות+סימון (הבא) |
