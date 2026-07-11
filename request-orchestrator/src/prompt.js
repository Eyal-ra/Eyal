// Turn an approved request into a Claude session prompt.
export function buildPrompt(req) {
  const lines = [];
  lines.push(`בקשה שאושרה על ידי אייל במערכת הבקשות. בצע אותה מקצה לקצה.`);
  lines.push("");
  lines.push(`# ${req.title || "(ללא כותרת)"}`);
  if (req.system) lines.push(`מערכת: ${req.system}`);
  if (req.requester) lines.push(`מבקש: ${req.requester}`);
  lines.push("");
  lines.push("## מה לבצע");
  lines.push(req.body || "(לא צורף פירוט — פנה לאייל אם לא ברור)");
  if (req.acceptance) {
    lines.push("");
    lines.push("## קריטריון סיום (בוצע כאשר)");
    lines.push(req.acceptance);
  }
  lines.push("");
  lines.push("---");
  lines.push(
    "כללי-חובה: לפני עריכת קובץ/מערכת חיה ודא שאין סשן אחר על אותו קובץ; גבה לפני שינוי; " +
      "אל תעלה נתוני לקוחות לשירות חיצוני; בסיום דווח מה בוצע. אם הבקשה לא ברורה — עצור ושאל, אל תנחש."
  );
  return lines.join("\n");
}
