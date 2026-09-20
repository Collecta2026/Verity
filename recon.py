"""
recon.py — cascade reconciliation, run per quarter, month by month.

Match tiers, strongest first. Each match records HOW it matched, so a
reference-exact hit is never given the same evidential weight as a
description-similarity hit.

  1  Reference exact          confidence 100
  2  Reference fuzzy          confidence 85
  3  Value + date + party     confidence 80
  4  Value + date             confidence 65
  5  Description similarity   confidence 55
  6  Split / aggregation      confidence 50
"""
from collections import defaultdict
from itertools import combinations
import pandas as pd
from rapidfuzz import fuzz
from models import db, Txn, Match, Split, Exception_
from ingest import norm_ref, norm_desc
from core import exception_ref

TIERS = {1: "Reference exact", 2: "Reference fuzzy", 3: "Value + date + party",
         4: "Value + date", 5: "Description similarity", 6: "Split / aggregation"}
CONF = {1: 100, 2: 85, 3: 80, 4: 65, 5: 55, 6: 50}


def _frame(engagement_id, side, month):
    q = Txn.query.filter_by(engagement_id=engagement_id, side=side, month=month).all()
    return [{"id": t.id, "date": pd.Timestamp(t.date), "cp": (t.counterparty or "").upper(),
             "cid": t.counterparty_id or "", "amount_in": t.amount_in, "amount_out": t.amount_out,
             "mag": round(t.amount_out if t.amount_out > 0 else t.amount_in, 2),
             "dir": "OUT" if t.amount_out > 0 else "IN",
             "refn": norm_ref(t.reference), "desc": norm_desc(t.description or t.txn_type),
             "used": False, "o": t} for t in q]


def run_month(engagement, month, settings):
    """Reconcile one month. Returns a summary dict."""
    eid = engagement.id
    win = settings.get("date_window_days", 5)
    fz = settings.get("fuzzy_ref_min", 88)
    dz = settings.get("desc_sim_min", 80)
    tol = settings.get("amount_tolerance", 0.01)
    maxg = settings.get("max_split_group", 4)

    Match.query.filter_by(engagement_id=eid, month=month).delete()
    db.session.commit()
    bank, ledger = _frame(eid, "bank", month), _frame(eid, "ledger", month)
    for t in bank + ledger:
        t["o"].matched = False
        t["o"].match_tier = None

    idx = defaultdict(list)
    for j, l in enumerate(ledger):
        idx[(l["dir"], int(round(l["mag"] * 100)))].append(j)

    quarter = None
    matches = []
    for b in bank:
        if b["used"]:
            continue
        quarter = quarter or b["o"].quarter
        best = None
        # tiers 1-4: same direction and amount
        for j in idx.get((b["dir"], int(round(b["mag"] * 100))), []):
            l = ledger[j]
            if l["used"]:
                continue
            gap = abs((b["date"] - l["date"]).days)
            tier = None
            if b["refn"] and l["refn"] and b["refn"] == l["refn"] and gap <= win * 3:
                tier = 1
            elif b["refn"] and l["refn"] and gap <= win and fuzz.ratio(b["refn"], l["refn"]) >= fz:
                tier = 2
            elif gap <= win and b["cp"] and l["cp"] and fuzz.token_set_ratio(b["cp"], l["cp"]) >= 85:
                tier = 3
            elif gap <= win:
                tier = 4
            if tier and (best is None or (tier, gap) < (best[0], best[1])):
                best = (tier, gap, j)
        # tier 5: description similarity, amount within tolerance, wider window
        if best is None and b["desc"]:
            for j, l in enumerate(ledger):
                if l["used"] or l["dir"] != b["dir"]:
                    continue
                if abs(l["mag"] - b["mag"]) > max(tol, b["mag"] * 0.001):
                    continue
                gap = abs((b["date"] - l["date"]).days)
                if gap <= win * 2 and l["desc"] and fuzz.token_set_ratio(b["desc"], l["desc"]) >= dz:
                    best = (5, gap, j)
                    break
        if best:
            tier, gap, j = best
            l = ledger[j]
            l["used"] = b["used"] = True
            b["o"].matched = l["o"].matched = True
            b["o"].match_tier = l["o"].match_tier = TIERS[tier]
            matches.append(Match(engagement_id=eid, quarter=b["o"].quarter, month=month,
                                 tier=tier, tier_label=TIERS[tier], confidence=CONF[tier],
                                 date_gap_days=int(gap), amount=b["mag"], direction=b["dir"],
                                 bank_txn_id=b["id"], ledger_txn_id=l["id"]))

    # tier 6: splits / aggregation, both directions
    splits = []
    def find(one, many, lbl_one, lbl_many):
        for o in one:
            if o["used"]:
                continue
            pool = [k for k, m in enumerate(many)
                    if not m["used"] and m["dir"] == o["dir"]
                    and abs((m["date"] - o["date"]).days) <= win]
            if not (2 <= len(pool) <= 25):
                continue
            found = None
            for n in range(2, maxg + 1):
                for combo in combinations(pool, n):
                    if all(not many[k]["used"] for k in combo) and \
                       abs(sum(many[k]["mag"] for k in combo) - o["mag"]) <= tol:
                        found = combo
                        break
                if found:
                    break
            if found:
                o["used"] = True
                o["o"].matched = True
                o["o"].match_tier = TIERS[6]
                for k in found:
                    many[k]["used"] = True
                    many[k]["o"].matched = True
                    many[k]["o"].match_tier = TIERS[6]
                splits.append(Split(engagement_id=eid, quarter=o["o"].quarter,
                    pattern=f"1 {lbl_one} = {len(found)} {lbl_many}", amount=o["mag"],
                    direction=o["dir"], one_txn_id=o["id"],
                    many_txn_ids=",".join(str(many[k]["id"]) for k in found),
                    counterparty=o["o"].counterparty))
    find(bank, ledger, "bank", "ledger")
    find(ledger, bank, "ledger", "bank")

    db.session.add_all(matches + splits)
    db.session.commit()

    ghost = [l for l in ledger if not l["used"] and l["amount_out"] > 0]
    unrec = [b for b in bank if not b["used"] and b["amount_out"] > 0]
    return {"month": month, "matched": len(matches), "splits": len(splits),
            "ghost": len(ghost), "unrecorded": len(unrec),
            "ghost_value": round(sum(l["amount_out"] for l in ghost), 2),
            "unrecorded_value": round(sum(b["amount_out"] for b in unrec), 2)}


def run_quarter(engagement, quarter, months, settings):
    out = [run_month(engagement, m, settings) for m in months]
    raise_exceptions(engagement, quarter)
    return out


def raise_exceptions(engagement, quarter):
    """Create an Exception row (with auto reference) for every unresolved item
    in the quarter that doesn't already have one."""
    eid = engagement.id
    existing = {(e.category, e.txn_id) for e in
                Exception_.query.filter_by(engagement_id=eid, quarter=quarter).all()}
    made = 0
    unmatched = Txn.query.filter_by(engagement_id=eid, quarter=quarter, matched=False).all()
    for t in unmatched:
        if t.amount_out <= 0 and t.amount_in <= 0:
            continue
        cat = "Ghost entry" if t.side == "ledger" else "Unrecorded outflow"
        if t.amount_in > 0:
            cat = "Unrecorded receipt" if t.side == "bank" else "Unsupported credit"
        if (cat, t.id) in existing:
            continue
        db.session.add(Exception_(engagement_id=eid, ref=exception_ref(engagement, quarter),
            quarter=quarter, month=t.month, category=cat, txn_id=t.id, date=t.date,
            counterparty=t.counterparty, amount=t.amount_out or t.amount_in,
            detail=f"{t.channel} {t.reference or ''} — {t.description or t.txn_type or ''}".strip()))
        made += 1
        db.session.flush()
    db.session.commit()
    return made
