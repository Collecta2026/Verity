"""
core.py — reference generation, period scaffolding, balance continuity.
"""
from datetime import date, timedelta
from calendar import monthrange
from models import (db, Period, Exception_, DocRequest, DocumentFile, Task,
                    Balance, Txn, Account, FxRate)


# ---------------------------------------------------------------- references
# Every artefact gets a structured, human-readable reference so it can be found
# later:  SGE-Q2-23-EXC-0007  /  SGE-Q2-23-DR-0003  /  SGE-DOC-000124  /  SGE-T-0042
def _next(model, engagement_id, prefix, width=4):
    n = model.query.filter_by(engagement_id=engagement_id).filter(
        model.ref.like(prefix + "%")).count() + 1
    ref = f"{prefix}{n:0{width}d}"
    while model.query.filter_by(ref=ref).first():
        n += 1
        ref = f"{prefix}{n:0{width}d}"
    return ref


def q_short(quarter):          # "2023-Q2" -> "Q2-23"
    y, q = quarter.split("-")
    return f"{q}-{y[2:]}"


def exception_ref(e, quarter):
    return _next(Exception_, e.id, f"{e.code}-{q_short(quarter)}-EXC-")


def request_ref(e, quarter):
    return _next(DocRequest, e.id, f"{e.code}-{q_short(quarter)}-DR-")


def document_ref(e):
    return _next(DocumentFile, e.id, f"{e.code}-DOC-", width=6)


def task_ref(e):
    return _next(Task, e.id, f"{e.code}-T-")


# ---------------------------------------------------------------- periods
def quarter_of(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1)//3 + 1}"


def month_of(d: date) -> str:
    return d.strftime("%Y-%m")


def build_periods(engagement):
    """Create one Period row per calendar month across the engagement span."""
    if not (engagement.period_start and engagement.period_end):
        return 0
    Period.query.filter_by(engagement_id=engagement.id).delete()
    d = date(engagement.period_start.year, engagement.period_start.month, 1)
    end = engagement.period_end
    made = 0
    while d <= end:
        last = date(d.year, d.month, monthrange(d.year, d.month)[1])
        db.session.add(Period(engagement_id=engagement.id, quarter=quarter_of(d),
                              month=month_of(d), start=d,
                              end=min(last, end) if last > end else last))
        made += 1
        d = (last + timedelta(days=1))
    db.session.commit()
    return made


def quarters(engagement_id):
    rows = (Period.query.filter_by(engagement_id=engagement_id)
            .order_by(Period.month).all())
    out = []
    for p in rows:
        if p.quarter not in [q["quarter"] for q in out]:
            out.append({"quarter": p.quarter, "months": [], "statuses": []})
        q = next(x for x in out if x["quarter"] == p.quarter)
        q["months"].append(p.month)
        q["statuses"].append(p.status)
    for q in out:
        s = q["statuses"]
        q["status"] = ("Signed off" if all(x == "Signed off" for x in s)
                       else "Reconciled" if all(x in ("Reconciled", "Signed off") for x in s)
                       else "In progress" if any(x != "Not started" for x in s)
                       else "Not started")
        q["done"] = sum(1 for x in s if x in ("Reconciled", "Signed off"))
    return out


# ---------------------------------------------------------------- balances
def recompute_balances(engagement):
    """Recompute movement, in-month variance and cross-period continuity gaps.

    variance       = closing - opening - movement   (statement doesn't foot)
    continuity_gap = this opening - prior closing   (a period is missing or altered)
    """
    accounts = Account.query.filter_by(engagement_id=engagement.id).all()
    flagged = 0
    for acc in accounts:
        rows = (Balance.query.filter_by(engagement_id=engagement.id, account_id=acc.id)
                .order_by(Balance.month).all())
        prev = None
        for b in rows:
            txns = Txn.query.filter_by(engagement_id=engagement.id,
                                       account_id=acc.id, month=b.month).all()
            movement = sum(t.amount_in for t in txns) - sum(t.amount_out for t in txns)
            b.computed_movement = round(movement, 2)
            b.variance = round((b.closing or 0) - (b.opening or 0) - movement, 2)
            b.continuity_gap = round((b.opening or 0) - (prev.closing or 0), 2) if prev else 0.0
            notes = []
            if abs(b.variance) > 0.01:
                notes.append(f"statement does not foot by {b.variance:,.2f}")
            if prev and abs(b.continuity_gap) > 0.01:
                notes.append(f"opening differs from prior closing by {b.continuity_gap:,.2f}")
            if prev and _month_gap(prev.month, b.month) > 1:
                notes.append(f"missing period between {prev.month} and {b.month}")
            if not txns:
                notes.append("no transactions loaded for this month")
            b.anomaly = "; ".join(notes) if notes else None
            if notes:
                flagged += 1
            prev = b
    db.session.commit()
    return flagged


def _month_gap(a, b):
    ay, am = map(int, a.split("-")); by, bm = map(int, b.split("-"))
    return (by - ay) * 12 + (bm - am)


def balance_anomalies(engagement_id):
    return (Balance.query.filter_by(engagement_id=engagement_id)
            .filter(Balance.anomaly.isnot(None)).order_by(Balance.month).all())


# ---------------------------------------------------------------- currency
def reprice(engagement):
    """Restate every foreign-currency transaction in the base currency using the
    month's rate. Reporting only — matching is always done in the original currency."""
    base = engagement.currency or "EGP"
    rates = {(r.currency, r.month): r.rate for r in
             FxRate.query.filter_by(engagement_id=engagement.id).all()}

    def rate_for(ccy, month):
        if ccy == base:
            return 1.0
        if (ccy, month) in rates:
            return rates[(ccy, month)]
        earlier = sorted([m for (c, m) in rates if c == ccy and m < month])
        return rates[(ccy, earlier[-1])] if earlier else None

    n = 0
    for t in Txn.query.filter_by(engagement_id=engagement.id).all():
        ccy = (t.currency or base).upper()
        r = rate_for(ccy, t.month)
        if r is None:
            t.fx_rate = t.base_in = t.base_out = None
            continue
        t.fx_rate = r
        t.base_in = round((t.amount_in or 0) * r, 2)
        t.base_out = round((t.amount_out or 0) * r, 2)
        n += 1
    for x in Exception_.query.filter_by(engagement_id=engagement.id).all():
        tx = db.session.get(Txn, x.txn_id) if x.txn_id else None
        if tx:
            x.currency = tx.currency
            x.base_amount = tx.base_out or tx.base_in
    db.session.commit()
    return n


def missing_rates(engagement_id):
    """Foreign-currency months with no rate — figures that cannot yet be stated
    in the base currency. The base currency itself never needs a rate."""
    from models import Engagement
    eng = db.session.get(Engagement, engagement_id)
    base = (eng.currency or "EGP").upper() if eng else "EGP"
    rows = (db.session.query(Txn.currency, Txn.month)
            .filter(Txn.engagement_id == engagement_id).distinct().all())
    have = {(r.currency, r.month) for r in
            FxRate.query.filter_by(engagement_id=engagement_id).all()}
    out = []
    for ccy, month in rows:
        if not ccy or not month or ccy.upper() == base:
            continue
        if (ccy, month) in have:
            continue
        out.append((ccy, month))
    return sorted(out)


def currency_totals(engagement_id, quarter=None):
    """Outflow totals per currency, with the base-currency equivalent."""
    q = Txn.query.filter_by(engagement_id=engagement_id, side="bank")
    if quarter:
        q = q.filter_by(quarter=quarter)
    out = {}
    for t in q.all():
        if not t.amount_out:
            continue
        c = t.currency or "?"
        d = out.setdefault(c, {"amount": 0.0, "base": 0.0, "count": 0, "unpriced": 0})
        d["amount"] += t.amount_out
        d["count"] += 1
        if t.base_out is None:
            d["unpriced"] += 1
        else:
            d["base"] += t.base_out
    return out
