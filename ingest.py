"""
ingest.py — parse an uploaded file into Txn rows against a chosen Account.
"""
import hashlib, re
import pandas as pd
from models import db, Txn, SourceFile
from core import quarter_of, month_of

STD = ["date","txn_type","description","counterparty","counterparty_id",
       "amount_in","amount_out","reference","gl_ref"]

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
    ai, ao = clean_amount(col("amount_in")), clean_amount(col("amount_out"))
    tt   = col("txn_type").fillna("").astype(str)
    desc = col("description").fillna("").astype(str)
    cp   = col("counterparty").fillna("").astype(str)
    cid  = col("counterparty_id"); ref = col("reference").fillna("").astype(str)
    gl   = col("gl_ref").fillna("").astype(str)

    rows = 0; qs = set()
    for i in range(len(raw)):
        if pd.isna(dates.iloc[i]): continue
        d = dates.iloc[i].date()
        q = quarter_of(d); qs.add(q)
        db.session.add(Txn(engagement_id=engagement.id, account_id=account.id,
            source_file_id=sf.id, side=account.side, channel=account.code,
            month=month_of(d), quarter=q, date=d,
            txn_type=tt.iloc[i][:300], description=desc.iloc[i][:400],
            counterparty=cp.iloc[i][:300], counterparty_id=clean_id(cid.iloc[i])[:120],
            amount_in=float(ai.iloc[i]), amount_out=float(ao.iloc[i]),
            reference=ref.iloc[i][:200], gl_ref=gl.iloc[i][:120]))
        rows += 1
    sf.rows_loaded = rows
    sf.quarter = ", ".join(sorted(qs))[:12] if len(qs) == 1 else "multiple"
    db.session.commit()
    return sf, rows
