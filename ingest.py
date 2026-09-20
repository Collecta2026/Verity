"""
ingest.py — parse an uploaded file into Txn rows against a chosen Account.
"""
import hashlib, re
import pandas as pd
from models import db, Txn, SourceFile, FxRate
from core import quarter_of, month_of


def fx_lookup(engagement_id, currency, month):
    """Rate for a currency in a month: the month's own rate, else the most recent
    earlier one, else None (left blank rather than guessed)."""
    r = FxRate.query.filter_by(engagement_id=engagement_id, currency=currency,
                               month=month).first()
    if r:
        return r.rate
    prev = (FxRate.query.filter_by(engagement_id=engagement_id, currency=currency)
            .filter(FxRate.month < month).order_by(FxRate.month.desc()).first())
    return prev.rate if prev else None


def preview_headers(path, limit=5):
    """Read just the header row and a few sample rows, for the mapping screen."""
    df = read_any(path)
    headers = [str(c) for c in df.columns]
    sample = df.head(limit).fillna("").astype(str).values.tolist()
    return headers, sample, len(df)


def guess_mapping(headers, kind):
    """Best-guess mapping from column names, which the user then confirms."""
    # Ordered most-specific first: an account column must be claimed before the
    # looser name match takes it.
    hints = [
     ("date", ["value date","posting date","transaction date","trans date","txn date",
               "txn dt","value dt","post dt","date","dt","تاريخ"]),
     ("counterparty_id", ["beneficiary account","recipient account","vendor account",
               "bene acct","bene account","account no","account number","iban",
               "mobile number","mobile","msisdn","acct","a/c","حساب"]),
     ("gl_ref", ["voucher no","voucher","journal no","journal","jv no","jv","gl ref",
                 "gl reference","سند"]),
     ("reference", ["reference no","transaction id","transaction ref","transfer ref",
                    "cheque no","cheque","our ref","their ref","ref no","reference",
                    "ref","مرجع"]),
     ("description", ["narrative details","description","narrative","details",
                      "particulars","memo","remarks","بيان"]),
     ("txn_type", ["transaction type","txn type","type","service","نوع"]),
     ("counterparty", ["beneficiary name","bene name","counterparty","beneficiary",
                       "payee","vendor","supplier","party","recipient","name","اسم"]),
     ("amount_in", ["credit amount","money in","amount in","received","credit","deposit",
                    "in","دائن"]),
     ("amount_out", ["debit amount","money out","amount out","withdrawal","payment",
                     "sent","debit","out","مدين"]),
     ("amount_signed", ["movement","net amount","amount","value","transaction amount",
                        "مبلغ"]),
     ("currency", ["currency code","currency","ccy","curr","cur","عملة"]),
     ("fx_rate", ["exchange rate","fx rate","conversion rate","rate","سعر الصرف"]),
    ]
    low = {h: str(h).strip().lower() for h in headers}
    out = {}
    used = set()
    for field, words in hints:
        best = None
        for h, lh in low.items():
            if h in used:
                continue
            for i, w in enumerate(words):
                if lh == w:
                    score = (0, i)            # exact header match wins
                elif lh.startswith(w) or lh.endswith(w):
                    score = (1, i)
                elif w in lh:
                    score = (2, i)
                else:
                    continue
                if best is None or score < best[0]:
                    best = (score, h)
                break
        if best:
            out[field] = best[1]
            used.add(best[1])
    # a single signed amount column is only used when in/out were not found
    if out.get("amount_in") or out.get("amount_out"):
        out.pop("amount_signed", None)
    return out

# Fields a statement column can be mapped to.
STD = ["date","txn_type","description","counterparty","counterparty_id",
       "amount_in","amount_out","amount_signed","currency","fx_rate",
       "reference","gl_ref"]

FIELD_LABELS = {
 "date":            ("Date", "Transaction or value date — required"),
 "txn_type":        ("Type", "Transaction type as the source labels it"),
 "description":     ("Description", "Narrative text; used for description matching"),
 "counterparty":    ("Counterparty", "Payee or payer name"),
 "counterparty_id": ("Counterparty account", "IBAN, account number or mobile number"),
 "amount_in":       ("Money in", "Credits / receipts (positive)"),
 "amount_out":      ("Money out", "Debits / payments (positive)"),
 "amount_signed":   ("Single amount column", "Use instead of in/out: negative = money out"),
 "currency":        ("Currency", "Leave unmapped if the file is all one currency"),
 "fx_rate":         ("FX rate", "Rate to base currency, if the file carries one"),
 "reference":       ("Reference", "Bank reference, cheque or transfer number"),
 "gl_ref":          ("Voucher / GL reference", "Ledger voucher number"),
}

DEFAULT_MAPS = {
 "bank":   {"date":"Value Date","txn_type":"Description","description":"Description",
            "counterparty":"Beneficiary","counterparty_id":"Beneficiary Account",
            "amount_in":"Credit","amount_out":"Debit","reference":"Reference"},
 "wallet": {"date":"Date","txn_type":"Type","description":"Type","counterparty":"Name",
            "counterparty_id":"Mobile Number","amount_in":"Received","amount_out":"Sent",
            "reference":"Transaction ID"},
 "ledger": {"date":"Posting Date","txn_type":"Description","description":"Description",
            "counterparty":"Vendor/Payee","counterparty_id":"Vendor Account",
            "amount_in":"Debit","amount_out":"Credit",
            "reference":"Cheque/Transfer Ref","gl_ref":"Voucher No"},
}

def sha256_bytes(d): return hashlib.sha256(d).hexdigest()

def read_any(path):
    p = str(path)
    if p.lower().endswith((".xlsx",".xls",".xlsm")):
        return pd.read_excel(p, dtype=str)
    return pd.read_csv(p, dtype=str, keep_default_na=False)

def clean_amount(s):
    s = s.fillna("").astype(str)
    s = s.str.replace(r"[^\d.\-]", "", regex=True)
    return pd.to_numeric(s, errors="coerce").fillna(0.0).abs()

def clean_signed(s):
    """A single amount column where negatives are payments out."""
    s = s.fillna("").astype(str)
    neg = s.str.contains(r"\(") | s.str.strip().str.startswith("-")
    v = pd.to_numeric(s.str.replace(r"[^\d.]", "", regex=True), errors="coerce").fillna(0.0)
    return v, neg


def clean_currency(v, default):
    c = str(v or "").strip().upper()
    c = {"LE": "EGP", "L.E": "EGP", "L.E.": "EGP", "EGP.": "EGP",
         "US$": "USD", "$": "USD", "USD.": "USD"}.get(c, c)
    return c[:10] if c else default


def clean_id(v):
    s = str(v or "").upper()
    s = re.sub(r"[\s\-]", "", s)
    return re.sub(r"^(\+20|0020|20)(?=1[0-9]{9}$)", "0", s).strip()

def norm_ref(x): return re.sub(r"[^A-Z0-9]", "", str(x).upper())

def norm_desc(x):
    s = re.sub(r"[^a-z0-9 ]", " ", str(x or "").lower())
    return " ".join(s.split())

def ingest_file(engagement, account, path, filename, raw_bytes, user_email):
    raw = read_any(path)
    mapping = account.column_map() or DEFAULT_MAPS.get(account.kind, DEFAULT_MAPS["bank"])
    sf = SourceFile(engagement_id=engagement.id, account_id=account.id, filename=filename,
                    sha256=sha256_bytes(raw_bytes), uploaded_by=user_email)
    db.session.add(sf); db.session.flush()

    def col(n):
        src = mapping.get(n)
        return raw[src] if src and src in raw.columns else pd.Series([""]*len(raw))

    dates = pd.to_datetime(col("date"), errors="coerce", dayfirst=True)
    if mapping.get("amount_signed"):
        vals, neg = clean_signed(col("amount_signed"))
        ai = vals.where(~neg, 0.0)
        ao = vals.where(neg, 0.0)
    else:
        ai, ao = clean_amount(col("amount_in")), clean_amount(col("amount_out"))
    ccy_col = col("currency")
    rate_col = pd.to_numeric(col("fx_rate").replace("", None), errors="coerce")
    tt   = col("txn_type").fillna("").astype(str)
    desc = col("description").fillna("").astype(str)
    cp   = col("counterparty").fillna("").astype(str)
    cid  = col("counterparty_id"); ref = col("reference").fillna("").astype(str)
    gl   = col("gl_ref").fillna("").astype(str)

    base = engagement.currency or "EGP"
    acct_ccy = account.currency or base
    rows = 0; qs = set()
    for i in range(len(raw)):
        if pd.isna(dates.iloc[i]): continue
        d = dates.iloc[i].date()
        q = quarter_of(d); qs.add(q)
        m = month_of(d)
        ccy = clean_currency(ccy_col.iloc[i], acct_ccy)
        r = rate_col.iloc[i] if not pd.isna(rate_col.iloc[i]) else None
        if ccy == base:
            r = 1.0
        elif r is None:
            r = fx_lookup(engagement.id, ccy, m)      # from the rate table, may be None
        in_, out_ = float(ai.iloc[i]), float(ao.iloc[i])
        db.session.add(Txn(engagement_id=engagement.id, account_id=account.id,
            source_file_id=sf.id, side=account.side, channel=account.code,
            month=m, quarter=q, date=d,
            txn_type=tt.iloc[i][:300], description=desc.iloc[i][:400],
            counterparty=cp.iloc[i][:300], counterparty_id=clean_id(cid.iloc[i])[:120],
            currency=ccy, amount_in=in_, amount_out=out_, fx_rate=r,
            base_in=round(in_ * r, 2) if r else None,
            base_out=round(out_ * r, 2) if r else None,
            reference=ref.iloc[i][:200], gl_ref=gl.iloc[i][:120]))
        rows += 1
    sf.rows_loaded = rows
    sf.quarter = ", ".join(sorted(qs))[:12] if len(qs) == 1 else "multiple"
    db.session.commit()
    return sf, rows
