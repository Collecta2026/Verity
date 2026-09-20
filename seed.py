"""
seed.py — default users and (optionally) a demo engagement.
"""
import json, random
from datetime import date, timedelta, datetime
from config import DEFAULT_SETTINGS, STARTER_ACCOUNTS
from models import (User, Engagement, Account, Txn, Balance, DocumentFile, ROLES)
import core, project

DEFAULTS = [
    ("admin@verity.local", "Administrator", "admin", "System administrator", "Verity2026"),
    ("lead@verity.local", "Zak Saleh", "lead", "CFO / Forensic Lead", "Verity2026"),
    ("finance@verity.local", "Finance Manager", "finance_reviewer", "Finance Manager", "Verity2026"),
    ("support1@verity.local", "Support One", "assistant", "Data & Records Coordinator", "Verity2026"),
    ("support2@verity.local", "Support Two", "assistant", "Tracing & Vouching Assistant", "Verity2026"),
]


def run(app, db):
    if not User.query.first():
        for email, name, role, title, pw in DEFAULTS:
            u = User(email=email, name=name, role=role, title=title)
            u.set_password(pw)
            db.session.add(u)
        db.session.commit()
    if app.config.get("SEED_DEMO") and not Engagement.query.first():
        _demo(db)


def _demo(db):
    lead = User.query.filter_by(role="lead").first()
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    s["watchlist_ids"] = ["01012345678"]
    e = Engagement(name="Scientific Gate — records review 2023-26", client="Scientific Gate",
                   code="SGE", currency="EGP",
                   period_start=date(2023, 5, 1), period_end=date(2026, 6, 30),
                   project_start=date(2026, 9, 21), project_end=date(2026, 10, 23),
                   created_by=lead.id if lead else None)
    e.set_settings(s)
    db.session.add(e)
    db.session.commit()

    accs = {}
    for code, name, kind, ident in STARTER_ACCOUNTS:
        a = Account(engagement_id=e.id, code=code, name=name, kind=kind,
                    identifier=ident, currency="EGP")
        db.session.add(a)
        db.session.commit()
        accs[code] = a

    core.build_periods(e)
    by_role = {r: u.id for r in ROLES for u in [User.query.filter_by(role=r).first()] if u}
    project.seed_plan(e, by_role)

    # ---- demo transactions with planted fraud, spread across quarters -------
    random.seed(7)
    start = date(2023, 5, 1)
    def d(n): return start + timedelta(days=n)

    def add(acc, dt, cp, cid, ai, ao, ref, gl="", desc=""):
        db.session.add(Txn(engagement_id=e.id, account_id=acc.id, side=acc.side,
            channel=acc.code, month=core.month_of(dt), quarter=core.quarter_of(dt), date=dt,
            counterparty=cp, counterparty_id=cid or "", amount_in=ai, amount_out=ao,
            reference=ref, gl_ref=gl, description=desc, txn_type=desc))

    ref = 1000
    for k in range(60):
        ref += 1
        amt = random.choice([2500, 7800, 15400, 33200, 48000, 61000])
        day = (k * 17) % 1100
        r = f"TRX{ref}"
        add(accs["CIB"], d(day), f"Supplier {k%8}", f"EG38..{k:02d}", 0, amt, r, "", "Supplier payment")
        add(accs["GL"], d(day + (k % 3)), f"Supplier {k%8}", f"EG38..{k:02d}", 0, amt, r,
            f"V{ref}", "Supplier payment")
        db.session.add(DocumentFile(engagement_id=e.id, ref=f"SGE-DOC-{k+1:06d}",
            filename=f"INV_{r}.pdf", doc_type="Invoice", txn_reference=r, sha256="demo",
            uploaded_by="seed"))
    # ghosts
    for k in range(4):
        ref += 1
        add(accs["GL"], d(200 + k * 120), "Bright Future Consulting", "EG999", 0,
            44000 + k * 1000, f"TRX{ref}", f"V{ref}", "Consulting fee")
    # unrecorded, one watchlisted
    add(accs["CIB"], d(150), "A. Personal", "EG380003000199999999", 0, 95000, "TRX9001", "", "Transfer")
    add(accs["VODA"], d(151), "Ahmed Personal", "01012345678", 0, 9800, "VF77001", "", "Send money")
    add(accs["INSTA"], d(520), "Unknown beneficiary", "01055500011", 0, 47500, "IP88001", "", "Transfer out")
    # split
    ref += 1
    add(accs["GL"], d(300), "TechCo", "EG38..99", 0, 30000, "TRX9100", f"V{ref}", "Equipment")
    add(accs["CIB"], d(300), "TechCo", "EG38..99", 0, 12000, "TRX9101", "", "Equipment part")
    add(accs["CIB"], d(301), "TechCo", "EG38..99", 0, 18000, "TRX9102", "", "Equipment part")
    # description-only match (different refs, same description and amount)
    add(accs["CIB"], d(400), "Nile Freight", "EG777", 0, 22350, "BNK55501", "", "Customs clearance charge")
    add(accs["GL"], d(402), "Nile Freight Co", "EG777", 0, 22350, "JV-9912", "V9912", "Customs clearance charges")
    # recurring unsupported
    for k in range(14):
        ref += 1
        r = f"TRX{ref}"
        add(accs["CIB"], d(30 * k + 5), "Falcon Services", "EG555", 0, 25000, r, "", "Service fee")
        add(accs["GL"], d(30 * k + 6), "Falcon Services", "EG555", 0, 25000, r, f"V{ref}", "Service fee")
    db.session.commit()

    # ---- balances, with one deliberate continuity break -------------------
    for code in ("CIB", "VODA"):
        acc = accs[code]
        months = sorted({t.month for t in Txn.query.filter_by(engagement_id=e.id,
                                                              account_id=acc.id).all()})
        running = 500000.0 if code == "CIB" else 20000.0
        for i, m in enumerate(months):
            txns = Txn.query.filter_by(engagement_id=e.id, account_id=acc.id, month=m).all()
            mv = sum(t.amount_in for t in txns) - sum(t.amount_out for t in txns)
            opening = running
            if code == "CIB" and i == 6:
                opening = running - 18500      # planted continuity break
            closing = opening + mv
            db.session.add(Balance(engagement_id=e.id, account_id=acc.id, month=m,
                quarter=f"{m[:4]}-Q{(int(m[5:7])-1)//3+1}", opening=round(opening, 2),
                closing=round(closing, 2), entered_by="seed"))
            running = closing
    db.session.commit()
    core.recompute_balances(e)
