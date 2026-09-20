"""
forensics.py — red-flag analytics, scoped to a quarter or the whole engagement.
Findings are raised as Exception rows so they enter the same clearance workflow.
"""
import math
from collections import Counter
from rapidfuzz import fuzz
from models import db, Txn, Exception_
from ingest import clean_id
from core import exception_ref


def benford(engagement_id, quarter=None):
    q = Txn.query.filter_by(engagement_id=engagement_id, side="bank")
    if quarter:
        q = q.filter_by(quarter=quarter)
    vals = [t.amount_out for t in q.all() if t.amount_out > 0]
    obs = Counter()
    for v in vals:
        x = abs(v)
        while x >= 10:
            x /= 10
        if x >= 1:
            obs[int(x)] += 1
    n = sum(obs.values()) or 1
    rows = []
    for d in range(1, 10):
        exp = math.log10(1 + 1 / d) * 100
        o = obs[d] / n * 100
        rows.append({"digit": d, "observed": obs[d], "observed_pct": round(o, 1),
                     "benford_pct": round(exp, 1), "excess": round(o - exp, 1)})
    return rows


def run(engagement, quarter=None):
    """Raise red-flag exceptions. Idempotent — won't duplicate existing ones."""
    s = engagement.settings()
    eid = engagement.id
    q = Txn.query.filter_by(engagement_id=eid, side="bank")
    if quarter:
        q = q.filter_by(quarter=quarter)
    outs = [t for t in q.all() if t.amount_out > 0]
    existing = {(e.category, e.txn_id) for e in Exception_.query.filter_by(engagement_id=eid).all()}
    made = Counter()

    def raise_(cat, t, detail):
        if (cat, t.id) in existing:
            return
        db.session.add(Exception_(engagement_id=eid, ref=exception_ref(engagement, t.quarter),
            quarter=t.quarter, month=t.month, category=cat, txn_id=t.id, date=t.date,
            counterparty=t.counterparty, amount=t.amount_out, detail=detail))
        db.session.flush()
        existing.add((cat, t.id))
        made[cat] += 1

    # watchlist
    wl_ids = {clean_id(x) for x in s.get("watchlist_ids", [])}
    wl_names = s.get("watchlist_names", [])
    for t in outs:
        hits = []
        if t.counterparty_id and t.counterparty_id in wl_ids:
            hits.append(f"ID {t.counterparty_id}")
        for nm in wl_names:
            if t.counterparty and fuzz.partial_ratio(nm.upper(), t.counterparty.upper()) >= 90:
                hits.append(f"name~{nm}")
        if hits:
            raise_("Watchlist hit", t, "; ".join(hits))

    # structuring
    band = s.get("threshold_band", 0.05)
    for th in s.get("approval_thresholds", []):
        for t in outs:
            if th * (1 - band) <= t.amount_out < th:
                raise_("Structuring", t, f"{t.amount_out/th*100:.1f}% of {th:,} authorisation limit")

    # duplicates
    dwin = s.get("duplicate_window", 7)
    by = {}
    for t in outs:
        by.setdefault((round(t.amount_out, 2), (t.counterparty or "").upper()), []).append(t)
    for g in by.values():
        g.sort(key=lambda x: x.date)
        for i in range(1, len(g)):
            if (g[i].date - g[i-1].date).days <= dwin:
                raise_("Duplicate payment", g[i],
                       f"same amount to same payee on {g[i-1].date} and {g[i].date}")

    db.session.commit()
    return dict(made)
