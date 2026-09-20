"""
requests_memo.py — the document request memo, printable or emailable, in English or Arabic.
The memo language follows the ?lang= parameter so you can send an Arabic memo to an
Arabic-speaking recipient regardless of the interface language you are working in.
"""
AR = {
 "title": "طلب مستندات", "to": "إلى", "from": "من", "date": "التاريخ",
 "due": "الاستحقاق", "subject": "الموضوع", "subject_v": "المستندات المؤيدة",
 "intro": ("في إطار مراجعة السجلات المالية للفترة، لم نتمكن من العثور على المستندات "
           "المؤيدة للمعاملة المبينة أدناه. يرجى تقديم المستندات المطلوبة، أو إيضاح "
           "سبب عدم وجودها."),
 "txn": "المعاملة", "ref": "المرجع", "tdate": "التاريخ", "cp": "الطرف المقابل",
 "amount": "المبلغ", "cat": "التصنيف", "detail": "التفاصيل",
 "docs": "المستندات المطلوبة",
 "close": ("يرجى ذكر رقم مرجع الطلب أعلاه في ردكم ليتسنى ربط المستندات بالبند الصحيح. "
           "وفي حال تعذر تقديم المستندات، يُقبل إيضاح خطي للمعاملة وسند اعتمادها بدلاً منها."),
 "print": "طباعة أو حفظ كـ PDF",
}
EN = {
 "title": "Document request", "to": "To", "from": "From", "date": "Date",
 "due": "Due by", "subject": "Subject", "subject_v": "Supporting documents",
 "intro": ("As part of the review of financial records for the period, we are unable to "
           "locate supporting documentation for the transaction below. Please provide the "
           "documents listed, or an explanation if none exist."),
 "txn": "Transaction", "ref": "Reference", "tdate": "Date", "cp": "Counterparty",
 "amount": "Amount", "cat": "Category", "detail": "Detail",
 "docs": "Documents requested",
 "close": ("Please quote the request reference above in your response so the documents can "
           "be matched to the correct item. If the documents cannot be provided, a written "
           "explanation of the transaction and its authorisation will be accepted in their place."),
 "print": "Print / save as PDF",
}


CATS = {
 "Ghost entry": "قيد وهمي (بالدفاتر دون حركة نقدية)",
 "Unrecorded outflow": "مدفوعات غير مقيدة",
 "Unrecorded receipt": "متحصلات غير مقيدة",
 "Unsupported credit": "إيراد غير مؤيد",
 "Watchlist hit": "مطابقة مع قائمة المراقبة",
 "Structuring": "تجزئة لتفادي حد الاعتماد",
 "Duplicate payment": "دفعة مكررة",
}


def _L(lang):
    return AR if lang == "ar" else EN


def _cat(value, lang):
    return CATS.get(value, value) if lang == "ar" else value

from datetime import date


def memo_text(engagement, req, lang='en'):
    """Plain-text version, suitable for pasting into an email."""
    L = _L(lang)
    e = req.exception
    lines = [f"{L['title'].upper()} — {req.ref}", "",
             f"{L['to']}: {req.addressee or '—'}",
             f"{L['from']}: {req.raised_by} ({engagement.client or engagement.name})",
             f"{L['date']}: {req.raised_at.strftime('%d/%m/%Y')}",
             f"{L['due']}: {req.due_date.strftime('%d/%m/%Y') if req.due_date else '—'}",
             f"{L['subject']}: {L['subject_v']} — {req.quarter}", "",
             L["intro"], "", L["txn"].upper()]
    if e:
        lines += [f"  {L['ref']}: {e.ref}",
                  f"  {L['tdate']}: {e.date.strftime('%d/%m/%Y') if e.date else '—'}",
                  f"  {L['cp']}: {e.counterparty or '—'}",
                  f"  {L['amount']}: {engagement.currency} {(e.amount or 0):,.2f}",
                  f"  {L['cat']}: {_cat(e.category, lang)}"]
        if e.detail:
            lines.append(f"  {L['detail']}: {e.detail}")
    lines += ["", L["docs"].upper()]
    for d in (req.documents_needed or "").splitlines():
        if d.strip():
            lines.append(f"  - {d.strip()}")
    lines += ["", L["close"], "", req.raised_by, engagement.client or engagement.name]
    return "\n".join(lines)


def memo_html(engagement, req, lang="en"):
    """Printable version — opens in a browser tab, Ctrl+P to PDF."""
    L = _L(lang)
    rtl = lang == "ar"
    e = req.exception
    docs = "".join(f"<li>{d.strip()}</li>" for d in (req.documents_needed or "").splitlines() if d.strip())
    row = lambda k, v: f"<tr><th>{k}</th><td>{v}</td></tr>"
    tx = ""
    if e:
        tx = (row(L["ref"], e.ref) +
              row(L["tdate"], e.date.strftime("%d/%m/%Y") if e.date else "—") +
              row(L["cp"], e.counterparty or "—") +
              row(L["amount"], f"{engagement.currency} {(e.amount or 0):,.2f}") +
              row(L["cat"], _cat(e.category, lang)) +
              (row(L["detail"], e.detail) if e.detail else ""))
    align = "right" if rtl else "left"
    font = ('"Segoe UI","Dubai","Noto Naskh Arabic",Tahoma,Arial,sans-serif' if rtl
            else "Calibri,Arial,sans-serif")
    return f"""<!doctype html><html lang="{lang}" dir="{'rtl' if rtl else 'ltr'}"><head><meta charset="utf-8">
<title>{req.ref}</title>
<style>
body{{font-family:{font};color:#1b2733;max-width:760px;margin:40px auto;padding:0 24px;line-height:1.6;text-align:{align}}}
h1{{font-size:19px;color:#1F3864;margin:0 0 2px}} .ref{{color:#6b7a8d;font-size:13px;margin-bottom:22px;direction:ltr;text-align:{align}}}
table{{border-collapse:collapse;width:100%;margin:10px 0 18px}}
th{{text-align:{align};background:#f1f5fa;width:160px;padding:6px 10px;font-weight:600;font-size:13px;border:1px solid #e3e9f0}}
td{{padding:6px 10px;border:1px solid #e3e9f0;font-size:13px;text-align:{align}}}
h2{{font-size:13px;letter-spacing:.04em;color:#1F3864;margin:20px 0 6px}}
ul{{margin:6px 0 18px;padding-{'right' if rtl else 'left'}:22px;padding-{'left' if rtl else 'right'}:0}}
li{{margin:3px 0}}
.meta td,.meta th{{border:none;padding:2px 10px 2px 0;background:none}}
.foot{{margin-top:30px;border-top:1px solid #e3e9f0;padding-top:12px;font-size:12px;color:#6b7a8d}}
@media print{{body{{margin:0}} .noprint{{display:none}}}}
</style></head><body>
<h1>{L['title']}</h1><div class="ref">{req.ref} &middot; {engagement.client or engagement.name}</div>
<table class="meta">
<tr><th>{L['to']}</th><td>{req.addressee or '—'}</td></tr>
<tr><th>{L['from']}</th><td>{req.raised_by}</td></tr>
<tr><th>{L['date']}</th><td>{req.raised_at.strftime('%d/%m/%Y')}</td></tr>
<tr><th>{L['due']}</th><td>{req.due_date.strftime('%d/%m/%Y') if req.due_date else '—'}</td></tr>
<tr><th>{L['subject']}</th><td>{L['subject_v']} — {req.quarter}</td></tr>
</table>
<p>{L['intro']}</p>
<h2>{L['txn']}</h2><table>{tx}</table>
<h2>{L['docs']}</h2><ul>{docs}</ul>
<p>{L['close']}</p>
<div class="foot">{req.raised_by} &middot; {engagement.client or engagement.name}</div>
<p class="noprint"><button onclick="window.print()">{L['print']}</button></p>
</body></html>"""
