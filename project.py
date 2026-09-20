"""
project.py — the work programme keyed to the project window, plus progress and
team activity reporting.
"""
from datetime import date, timedelta, datetime
from models import db, Task, TaskUpdate, User, AuditLog, DocRequest, Exception_, Period
from core import task_ref

# Work programme template. (offset_start, offset_end) are working-day offsets from
# project start; role is who it is intended for.
PLAN = [
    ("Mobilise",   "Freeze former manager's system access; secure originals", "lead", 0, 1),
    ("Mobilise",   "Issue bank confirmation letters to CIB and NBE", "lead", 0, 2),
    ("Mobilise",   "Collect Vodafone Cash and InstaPay statement logs", "assistant", 0, 6),
    ("Mobilise",   "Export Al Amin ledger, quarter by quarter", "finance_reviewer", 1, 5),
    ("Mobilise",   "Set up accounts and column mappings in Verity", "lead", 1, 3),
    ("Data",       "Upload and verify statements — 2023 quarters", "assistant", 3, 7),
    ("Data",       "Upload and verify statements — 2024 quarters", "assistant", 5, 10),
    ("Data",       "Upload and verify statements — 2025-26 quarters", "assistant", 8, 13),
    ("Data",       "Enter opening/closing balances; clear continuity anomalies", "finance_reviewer", 4, 12),
    ("Reconcile",  "Reconcile 2023 quarters month by month", "lead", 6, 11),
    ("Reconcile",  "Reconcile 2024 quarters month by month", "lead", 9, 14),
    ("Reconcile",  "Reconcile 2025-26 quarters month by month", "lead", 12, 17),
    ("Clear",      "Raise document requests for open exceptions", "finance_reviewer", 8, 18),
    ("Clear",      "Chase outstanding requests; log responses", "assistant", 10, 21),
    ("Clear",      "Assess documents received; accept or reject", "finance_reviewer", 11, 22),
    ("Analyse",    "Write quarterly rationale — 2023 and 2024", "lead", 14, 19),
    ("Analyse",    "Write quarterly rationale — 2025 and 2026", "lead", 17, 22),
    ("Analyse",    "Recurrence and pattern analysis across all quarters", "lead", 19, 23),
    ("Report",     "Quantify exposure; compile exception pack", "lead", 21, 24),
    ("Report",     "Draft findings report with evidence index", "lead", 22, 25),
    ("Report",     "QA every figure to source; legal review", "finance_reviewer", 24, 26),
]


def _workday(start: date, n: int) -> date:
    d, added = start, 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def seed_plan(engagement, user_by_role=None):
    """Create the task list across the project window. Assigns by role where a
    user is available; otherwise leaves unassigned for the admin to allocate."""
    if Task.query.filter_by(engagement_id=engagement.id).count():
        return 0
    start = engagement.project_start or date.today()
    user_by_role = user_by_role or {}
    made = 0
    for phase, title, role, s, e in PLAN:
        db.session.add(Task(engagement_id=engagement.id, ref=task_ref(engagement),
            title=title, phase=phase, owner_id=user_by_role.get(role),
            start_date=_workday(start, s), due_date=_workday(start, e)))
        db.session.flush()
        made += 1
    db.session.commit()
    return made


def project_progress(engagement):
    tasks = Task.query.filter_by(engagement_id=engagement.id).all()
    total = len(tasks) or 1
    done = sum(1 for t in tasks if t.status == "Done")
    avg = round(sum(t.progress or 0 for t in tasks) / total)
    today = date.today()
    ps, pe = engagement.project_start, engagement.project_end
    elapsed = 0
    if ps and pe and pe > ps:
        elapsed = max(0, min(100, round((today - ps).days / (pe - ps).days * 100)))
    periods = Period.query.filter_by(engagement_id=engagement.id).all()
    return {
        "tasks": total, "done": done, "avg_progress": avg,
        "overdue": sum(1 for t in tasks if t.overdue),
        "elapsed_pct": elapsed,
        "days_left": (pe - today).days if pe else None,
        "months_done": sum(1 for p in periods if p.status in ("Reconciled", "Signed off")),
        "months_total": len(periods),
        "open_exceptions": Exception_.query.filter_by(engagement_id=engagement.id, status="Open").count(),
        "open_requests": DocRequest.query.filter_by(engagement_id=engagement.id)
                          .filter(DocRequest.status.in_(["Requested", "Chased"])).count(),
    }


def activity_report(engagement):
    """Per-person summary: workload, progress, overdue items, recent activity."""
    users = User.query.filter_by(active=True).order_by(User.name).all()
    rows = []
    for u in users:
        tasks = Task.query.filter_by(engagement_id=engagement.id).filter(
            (Task.owner_id == u.id) | (Task.joint_owner_id == u.id)).all()
        reqs = DocRequest.query.filter_by(engagement_id=engagement.id, assigned_to_id=u.id).all()
        acts = AuditLog.query.filter_by(user_id=u.id).order_by(AuditLog.ts.desc()).limit(1).all()
        upd = (TaskUpdate.query.filter_by(by=u.name).order_by(TaskUpdate.ts.desc()).first())
        rows.append({
            "user": u, "tasks": len(tasks),
            "done": sum(1 for t in tasks if t.status == "Done"),
            "in_progress": sum(1 for t in tasks if t.status == "In progress"),
            "blocked": sum(1 for t in tasks if t.status == "Blocked"),
            "overdue": sum(1 for t in tasks if t.overdue),
            "avg": round(sum(t.progress or 0 for t in tasks) / len(tasks)) if tasks else 0,
            "requests": len(reqs),
            "requests_overdue": sum(1 for r in reqs if r.overdue),
            "last_active": acts[0].ts if acts else None,
            "last_update": upd.ts if upd else None,
        })
    return rows
