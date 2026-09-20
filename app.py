"""
app.py — Verity v2: quarterly forensic reconciliation platform.
Flask + SQLAlchemy on Neon Postgres, GitHub -> Render.
"""
import os, json, io
from datetime import datetime, date, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for, flash,
                   send_file, abort, Response, session)
from flask_login import (LoginManager, login_user, logout_user, login_required, current_user)
from werkzeug.utils import secure_filename

from config import Config, DEFAULT_SETTINGS, STARTER_ACCOUNTS
from models import (db, User, AuditLog, Engagement, Account, Period, QuarterFile,
                    SourceFile, Txn, Match, Split, Balance, Exception_, DocRequest,
                    DocumentFile, Task, TaskUpdate, ROLES, ROLE_LABELS, TASK_STATUS,
                    REQ_STATUS, DOC_TYPES)
import core, ingest, recon, forensics, project, reporting, requests_memo, i18n

app = Flask(__name__)
app.config.from_object(Config)
app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))


def log(action, entity=None, entity_id=None, before=None, after=None, detail=""):
    db.session.add(AuditLog(user_id=getattr(current_user, "id", None),
        user_email=getattr(current_user, "email", "system"), action=action,
        entity=entity, entity_id=str(entity_id) if entity_id else None,
        before=before, after=after, detail=detail))
    db.session.commit()


def roles_required(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if not current_user.is_authenticated or not current_user.can(*roles):
                abort(403)
            return f(*a, **k)
        return w
    return deco


def get_e(eid):
    e = db.session.get(Engagement, eid)
    if not e:
        abort(404)
    return e


def pdate(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


@app.teardown_request
def _teardown(exc):
    if exc is not None:
        db.session.rollback()
    db.session.remove()


@app.context_processor
def inject():
    return {"ROLE_LABELS": ROLE_LABELS, "ROLES": ROLES, "TASK_STATUS": TASK_STATUS,
            "REQ_STATUS": REQ_STATUS, "DOC_TYPES": DOC_TYPES, "today": date.today(),
            "t": i18n.t, "tv": i18n.tv, "lang": i18n.get_lang(), "rtl": i18n.is_rtl(),
            "LANGS": i18n.LANGS}


@app.route("/lang/<code>")
def set_lang(code):
    if code in i18n.LANGS:
        session["lang"] = code
    return redirect(request.referrer or url_for("dashboard"))


# ----------------------------------------------------------------- auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(email=request.form["email"].lower().strip()).first()
        if u and u.active and u.check_password(request.form["password"]):
            login_user(u)
            log("login")
            return redirect(url_for("dashboard"))
        flash("Invalid credentials or inactive account.", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    log("logout")
    logout_user()
    return redirect(url_for("login"))


# ----------------------------------------------------------------- dashboard
@app.route("/")
@login_required
def dashboard():
    es = Engagement.query.order_by(Engagement.created_at.desc()).all()
    e = es[0] if es else None
    ctx = {"engagements": es, "e": e}
    if e:
        ctx.update(prog=project.project_progress(e), quarters=core.quarters(e.id),
                   mytasks=Task.query.filter_by(engagement_id=e.id).filter(
                       (Task.owner_id == current_user.id) |
                       (Task.joint_owner_id == current_user.id)).order_by(Task.due_date).all())
    return render_template("dashboard.html", **ctx)


@app.route("/engagements", methods=["POST"])
@roles_required("lead", "finance_reviewer")
def create_engagement():
    f = request.form
    e = Engagement(name=f["name"].strip(), client=f.get("client", "").strip(),
                   code=(f.get("code") or "SGE").strip().upper(),
                   currency=f.get("currency", "EGP"),
                   period_start=pdate(f.get("period_start")), period_end=pdate(f.get("period_end")),
                   project_start=pdate(f.get("project_start")), project_end=pdate(f.get("project_end")),
                   created_by=current_user.id)
    e.set_settings(json.loads(json.dumps(DEFAULT_SETTINGS)))
    db.session.add(e)
    db.session.commit()
    for code, name, kind, ident in STARTER_ACCOUNTS:
        db.session.add(Account(engagement_id=e.id, code=code, name=name, kind=kind,
                               identifier=ident, currency=e.currency))
    db.session.commit()
    core.build_periods(e)
    by_role = {r: u.id for r in ROLES for u in [User.query.filter_by(role=r).first()] if u}
    project.seed_plan(e, by_role)
    log("engagement.create", "engagement", e.id, detail=e.name)
    return redirect(url_for("engagement", eid=e.id))


@app.route("/engagement/<int:eid>")
@login_required
def engagement(eid):
    e = get_e(eid)
    return render_template("engagement.html", e=e, prog=project.project_progress(e),
        quarters=core.quarters(eid), accounts=Account.query.filter_by(engagement_id=eid).all(),
        anomalies=core.balance_anomalies(eid)[:8])


# ----------------------------------------------------------------- accounts
@app.route("/engagement/<int:eid>/accounts", methods=["GET", "POST"])
@login_required
def accounts(eid):
    e = get_e(eid)
    if request.method == "POST":
        if not current_user.can("lead", "finance_reviewer"):
            abort(403)
        f = request.form
        a = Account(engagement_id=eid, code=f["code"].strip().upper(), name=f["name"].strip(),
                    kind=f["kind"], identifier=f.get("identifier", "").strip(),
                    currency=f.get("currency") or e.currency)
        if f.get("column_map"):
            try:
                a.set_column_map(json.loads(f["column_map"]))
            except Exception:
                flash("Column map must be valid JSON — saved without it.", "error")
        db.session.add(a)
        db.session.commit()
        log("account.create", "account", a.id, detail=f"{a.code} {a.name}")
        flash(f"Account {a.code} added.", "ok")
        return redirect(url_for("accounts", eid=eid))
    return render_template("accounts.html", e=e,
        accounts=Account.query.filter_by(engagement_id=eid).all(),
        maps=ingest.DEFAULT_MAPS)


@app.route("/engagement/<int:eid>/accounts/<int:aid>/map", methods=["POST"])
@roles_required("lead", "finance_reviewer")
def account_map(eid, aid):
    a = db.session.get(Account, aid)
    before = a.column_map_json
    try:
        a.set_column_map(json.loads(request.form["column_map"]))
        db.session.commit()
        log("account.map", "account", aid, before=before, after=a.column_map_json)
        flash("Column mapping saved.", "ok")
    except Exception:
        flash("Column map must be valid JSON.", "error")
    return redirect(url_for("accounts", eid=eid))


# ----------------------------------------------------------------- data
@app.route("/engagement/<int:eid>/data", methods=["GET", "POST"])
@login_required
def data(eid):
    e = get_e(eid)
    if request.method == "POST":
        if not current_user.can("lead", "finance_reviewer", "assistant"):
            abort(403)
        acc = db.session.get(Account, int(request.form["account_id"]))
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Choose a file.", "error")
            return redirect(url_for("data", eid=eid))
        raw = file.read()
        tmp = app.config["UPLOAD_FOLDER"] / f"{eid}_{secure_filename(file.filename)}"
        tmp.write_bytes(raw)
        try:
            sf, n = ingest.ingest_file(e, acc, tmp, file.filename, raw, current_user.email)
            core.recompute_balances(e)
            log("source.upload", "source", sf.id, detail=f"{acc.code} {file.filename} {n} rows")
            flash(f"Loaded {n} rows into {acc.code}.", "ok")
        except Exception as ex:
            flash(f"Could not parse: {ex}. Check the column mapping for {acc.code}.", "error")
        return redirect(url_for("data", eid=eid))
    return render_template("data.html", e=e,
        accounts=Account.query.filter_by(engagement_id=eid, active=True).all(),
        sources=SourceFile.query.filter_by(engagement_id=eid).order_by(SourceFile.uploaded_at.desc()).all())


# ----------------------------------------------------------------- balances
@app.route("/engagement/<int:eid>/balances", methods=["GET", "POST"])
@login_required
def balances(eid):
    e = get_e(eid)
    if request.method == "POST":
        if not current_user.can("lead", "finance_reviewer", "assistant"):
            abort(403)
        f = request.form
        aid, month = int(f["account_id"]), f["month"]
        b = Balance.query.filter_by(engagement_id=eid, account_id=aid, month=month).first()
        before = f"{b.opening}/{b.closing}" if b else None
        if not b:
            b = Balance(engagement_id=eid, account_id=aid, month=month,
                        quarter=f"{month[:4]}-Q{(int(month[5:7])-1)//3+1}")
            db.session.add(b)
        b.opening = float(f.get("opening") or 0)
        b.closing = float(f.get("closing") or 0)
        b.entered_by = current_user.name
        db.session.commit()
        n = core.recompute_balances(e)
        log("balance.save", "balance", b.id, before=before, after=f"{b.opening}/{b.closing}",
            detail=f"{month}")
        flash(f"Balance saved. {n} anomaly flag(s) across the engagement.", "ok")
        return redirect(url_for("balances", eid=eid, account_id=aid))
    aid = request.args.get("account_id", type=int)
    accs = Account.query.filter_by(engagement_id=eid, active=True).all()
    aid = aid or (accs[0].id if accs else None)
    periods = Period.query.filter_by(engagement_id=eid).order_by(Period.month).all()
    bal = {b.month: b for b in Balance.query.filter_by(engagement_id=eid, account_id=aid).all()}
    return render_template("balances.html", e=e, accounts=accs, aid=aid,
                           periods=periods, bal=bal)


# ----------------------------------------------------------------- quarters
@app.route("/engagement/<int:eid>/quarter/<quarter>")
@login_required
def quarter(eid, quarter):
    e = get_e(eid)
    months = [p for p in Period.query.filter_by(engagement_id=eid, quarter=quarter)
              .order_by(Period.month).all()]
    exc = Exception_.query.filter_by(engagement_id=eid, quarter=quarter).order_by(Exception_.date).all()
    qf = QuarterFile.query.filter_by(engagement_id=eid, quarter=quarter).first()
    stats = {
        "matched": Match.query.filter_by(engagement_id=eid, quarter=quarter).count(),
        "splits": Split.query.filter_by(engagement_id=eid, quarter=quarter).count(),
        "open": sum(1 for x in exc if x.status == "Open"),
        "cleared": sum(1 for x in exc if x.status == "Cleared"),
        "value": sum(x.amount or 0 for x in exc if x.status != "Cleared"),
    }
    return render_template("quarter.html", e=e, quarter=quarter, months=months,
        exceptions=exc, qf=qf, stats=stats, benford=forensics.benford(eid, quarter),
        requests=DocRequest.query.filter_by(engagement_id=eid, quarter=quarter).all())


@app.route("/engagement/<int:eid>/quarter/<quarter>/run", methods=["POST"])
@roles_required("lead", "finance_reviewer")
def run_quarter(eid, quarter):
    e = get_e(eid)
    months = [p.month for p in Period.query.filter_by(engagement_id=eid, quarter=quarter)
              .order_by(Period.month).all()]
    res = recon.run_quarter(e, quarter, months, e.settings())
    forensics.run(e, quarter)
    for p in Period.query.filter_by(engagement_id=eid, quarter=quarter).all():
        if p.status == "Not started":
            p.status = "Reconciled"
    db.session.commit()
    log("quarter.reconcile", "quarter", quarter, detail=json.dumps(res))
    flash(f"{quarter} reconciled across {len(months)} month(s).", "ok")
    return redirect(url_for("quarter", eid=eid, quarter=quarter))


@app.route("/engagement/<int:eid>/quarter/<quarter>/narrative", methods=["POST"])
@roles_required("lead", "finance_reviewer")
def quarter_narrative(eid, quarter):
    e = get_e(eid)
    qf = QuarterFile.query.filter_by(engagement_id=eid, quarter=quarter).first()
    if not qf:
        qf = QuarterFile(engagement_id=eid, quarter=quarter)
        db.session.add(qf)
    if qf.locked:
        flash("This quarter is signed off and locked.", "error")
        return redirect(url_for("quarter", eid=eid, quarter=quarter))
    before = qf.narrative
    qf.narrative = request.form.get("narrative", "")
    qf.value_at_risk = float(request.form.get("value_at_risk") or 0)
    db.session.commit()
    log("quarter.narrative", "quarter", quarter, before=before, after=qf.narrative)
    if request.form.get("signoff"):
        qf.locked = True
        qf.signed_off_by = current_user.name
        qf.signed_off_at = datetime.utcnow()
        for p in Period.query.filter_by(engagement_id=eid, quarter=quarter).all():
            p.status = "Signed off"
            p.signed_off_by = current_user.name
            p.signed_off_at = datetime.utcnow()
        db.session.commit()
        log("quarter.signoff", "quarter", quarter)
        flash(f"{quarter} signed off and locked.", "ok")
    else:
        flash("Rationale saved.", "ok")
    return redirect(url_for("quarter", eid=eid, quarter=quarter))


@app.route("/engagement/<int:eid>/casefile")
@login_required
def casefile(eid):
    e = get_e(eid)
    qfs = {q.quarter: q for q in QuarterFile.query.filter_by(engagement_id=eid).all()}
    qs = core.quarters(eid)
    for q in qs:
        q["file"] = qfs.get(q["quarter"])
        q["exceptions"] = Exception_.query.filter_by(engagement_id=eid, quarter=q["quarter"]).count()
        q["open"] = Exception_.query.filter_by(engagement_id=eid, quarter=q["quarter"], status="Open").count()
    return render_template("casefile.html", e=e, quarters=qs)


# ----------------------------------------------------------------- exceptions & requests
@app.route("/engagement/<int:eid>/exceptions")
@login_required
def exceptions(eid):
    e = get_e(eid)
    q = Exception_.query.filter_by(engagement_id=eid)
    if request.args.get("quarter"):
        q = q.filter_by(quarter=request.args["quarter"])
    if request.args.get("status"):
        q = q.filter_by(status=request.args["status"])
    return render_template("exceptions.html", e=e, quarters=core.quarters(eid),
        items=q.order_by(Exception_.quarter, Exception_.date).all(),
        users=User.query.filter_by(active=True).all())


@app.route("/engagement/<int:eid>/exception/<int:xid>/request", methods=["POST"])
@roles_required("lead", "finance_reviewer", "assistant")
def raise_request(eid, xid):
    e = get_e(eid)
    x = db.session.get(Exception_, xid)
    f = request.form
    due = pdate(f.get("due_date")) or (date.today() + timedelta(days=e.settings().get("request_due_days", 7)))
    r = DocRequest(engagement_id=eid, ref=core.request_ref(e, x.quarter), exception_id=x.id,
        quarter=x.quarter, addressee=f.get("addressee", "").strip(),
        documents_needed=f.get("documents_needed", "").strip(),
        raised_by=current_user.name, due_date=due,
        assigned_to_id=int(f["assigned_to"]) if f.get("assigned_to") else None)
    db.session.add(r)
    db.session.commit()
    log("request.raise", "request", r.ref, detail=f"for {x.ref}")
    flash(f"Document request {r.ref} raised.", "ok")
    return redirect(url_for("requests_list", eid=eid))


@app.route("/engagement/<int:eid>/exception/<int:xid>/clear", methods=["POST"])
@roles_required("lead", "finance_reviewer")
def clear_exception(eid, xid):
    x = db.session.get(Exception_, xid)
    before = x.status
    x.status = request.form.get("status", "Cleared")
    x.resolution = request.form.get("resolution", "")
    x.cleared_by = current_user.name
    x.cleared_at = datetime.utcnow()
    db.session.commit()
    log("exception.update", "exception", x.ref, before=before, after=x.status, detail=x.resolution)
    flash(f"{x.ref} marked {x.status}.", "ok")
    return redirect(request.referrer or url_for("exceptions", eid=eid))


@app.route("/engagement/<int:eid>/requests")
@login_required
def requests_list(eid):
    e = get_e(eid)
    q = DocRequest.query.filter_by(engagement_id=eid)
    if request.args.get("status"):
        q = q.filter_by(status=request.args["status"])
    if request.args.get("mine"):
        q = q.filter_by(assigned_to_id=current_user.id)
    return render_template("requests.html", e=e,
        items=q.order_by(DocRequest.due_date).all(),
        users=User.query.filter_by(active=True).all())


@app.route("/engagement/<int:eid>/request/<int:rid>/memo")
@login_required
def request_memo(eid, rid):
    e = get_e(eid)
    r = db.session.get(DocRequest, rid)
    mlang = request.args.get("lang") or i18n.get_lang()
    if request.args.get("format") == "text":
        return Response(requests_memo.memo_text(e, r, mlang),
                        mimetype="text/plain; charset=utf-8")
    return requests_memo.memo_html(e, r, mlang)


@app.route("/engagement/<int:eid>/request/<int:rid>/update", methods=["POST"])
@roles_required("lead", "finance_reviewer", "assistant")
def update_request(eid, rid):
    r = db.session.get(DocRequest, rid)
    f = request.form
    before = f"{r.status}/{r.assigned_to_id}"
    if f.get("status"):
        r.status = f["status"]
        if r.status == "Chased":
            r.chased_count = (r.chased_count or 0) + 1
            r.last_chased = date.today()
        if r.status in ("Accepted", "Rejected"):
            r.closed_at = datetime.utcnow()
            if r.status == "Accepted" and r.exception:
                r.exception.status = "Cleared"
                r.exception.resolution = f"Cleared by {r.ref}: {f.get('response_note','')}"
                r.exception.cleared_by = current_user.name
                r.exception.cleared_at = datetime.utcnow()
    if f.get("assigned_to"):
        r.assigned_to_id = int(f["assigned_to"])
    if f.get("response_note"):
        r.response_note = f["response_note"]
    if f.get("due_date"):
        r.due_date = pdate(f["due_date"])
    db.session.commit()
    log("request.update", "request", r.ref, before=before, after=f"{r.status}/{r.assigned_to_id}")
    flash(f"{r.ref} updated.", "ok")
    return redirect(request.referrer or url_for("requests_list", eid=eid))


@app.route("/engagement/<int:eid>/documents", methods=["GET", "POST"])
@login_required
def documents(eid):
    e = get_e(eid)
    if request.method == "POST" and request.files.get("file"):
        if not current_user.can("lead", "finance_reviewer", "assistant"):
            abort(403)
        f = request.files["file"]
        raw = f.read()
        d = DocumentFile(engagement_id=eid, ref=core.document_ref(e), filename=f.filename,
            doc_type=request.form.get("doc_type"), quarter=request.form.get("quarter"),
            txn_reference=request.form.get("txn_reference", "").strip(),
            request_id=int(request.form["request_id"]) if request.form.get("request_id") else None,
            sha256=ingest.sha256_bytes(raw), uploaded_by=current_user.email)
        db.session.add(d)
        db.session.commit()
        if d.request_id:
            r = db.session.get(DocRequest, d.request_id)
            if r and r.status in ("Requested", "Chased"):
                r.status = "Received"
                db.session.commit()
        log("document.upload", "document", d.ref, detail=f.filename)
        flash(f"Document filed as {d.ref}.", "ok")
        return redirect(url_for("documents", eid=eid))
    return render_template("documents.html", e=e,
        docs=DocumentFile.query.filter_by(engagement_id=eid).order_by(DocumentFile.uploaded_at.desc()).all(),
        quarters=core.quarters(eid),
        open_requests=DocRequest.query.filter_by(engagement_id=eid).filter(
            DocRequest.status.in_(["Requested", "Chased", "Received"])).all())


# ----------------------------------------------------------------- tasks & team
@app.route("/engagement/<int:eid>/tasks", methods=["GET", "POST"])
@login_required
def tasks(eid):
    e = get_e(eid)
    if request.method == "POST":
        if not current_user.can("lead", "finance_reviewer"):
            abort(403)
        f = request.form
        t = Task(engagement_id=eid, ref=core.task_ref(e), title=f["title"].strip(),
                 detail=f.get("detail", ""), phase=f.get("phase", "Ad hoc"),
                 owner_id=int(f["owner"]) if f.get("owner") else None,
                 joint_owner_id=int(f["joint_owner"]) if f.get("joint_owner") else None,
                 start_date=pdate(f.get("start_date")), due_date=pdate(f.get("due_date")))
        db.session.add(t)
        db.session.commit()
        log("task.create", "task", t.ref, detail=t.title)
        flash(f"Task {t.ref} created.", "ok")
        return redirect(url_for("tasks", eid=eid))
    q = Task.query.filter_by(engagement_id=eid)
    if request.args.get("mine"):
        q = q.filter((Task.owner_id == current_user.id) | (Task.joint_owner_id == current_user.id))
    if request.args.get("status"):
        q = q.filter_by(status=request.args["status"])
    return render_template("tasks.html", e=e, items=q.order_by(Task.due_date).all(),
        users=User.query.filter_by(active=True).order_by(User.name).all(),
        prog=project.project_progress(e))


@app.route("/engagement/<int:eid>/task/<int:tid>/update", methods=["POST"])
@login_required
def update_task(eid, tid):
    t = db.session.get(Task, tid)
    f = request.form
    before = f"{t.status}/{t.progress}/owner={t.owner_id}/joint={t.joint_owner_id}"
    # reassignment / joint ownership — lead & admin only
    if current_user.can("lead", "finance_reviewer"):
        if "owner" in f:
            t.owner_id = int(f["owner"]) if f["owner"] else None
        if "joint_owner" in f:
            t.joint_owner_id = int(f["joint_owner"]) if f["joint_owner"] else None
        if f.get("due_date"):
            t.due_date = pdate(f["due_date"])
    if f.get("status"):
        t.status = f["status"]
    if f.get("progress") is not None and f.get("progress") != "":
        t.progress = max(0, min(100, int(f["progress"])))
    if t.status == "Done":
        t.progress = 100
    t.last_update = datetime.utcnow()
    db.session.add(TaskUpdate(task_id=t.id, by=current_user.name, progress=t.progress,
                              status=t.status, note=f.get("note", "")))
    db.session.commit()
    log("task.update", "task", t.ref,
        before=before, after=f"{t.status}/{t.progress}/owner={t.owner_id}/joint={t.joint_owner_id}",
        detail=f.get("note", ""))
    flash(f"{t.ref} updated.", "ok")
    return redirect(request.referrer or url_for("tasks", eid=eid))


@app.route("/engagement/<int:eid>/team")
@login_required
def team(eid):
    e = get_e(eid)
    return render_template("team.html", e=e, rows=project.activity_report(e),
                           prog=project.project_progress(e))


@app.route("/users", methods=["GET", "POST"])
@roles_required("admin")
def users():
    if request.method == "POST":
        f = request.form
        if User.query.filter_by(email=f["email"].lower().strip()).first():
            flash("Email already exists.", "error")
        else:
            u = User(email=f["email"].lower().strip(), name=f["name"].strip(),
                     role=f["role"], title=f.get("title", "").strip())
            u.set_password(f["password"])
            db.session.add(u)
            db.session.commit()
            log("user.create", "user", u.id, detail=f"{u.email} {u.role}")
            flash("User created.", "ok")
        return redirect(url_for("users"))
    return render_template("users.html", users=User.query.order_by(User.name).all())


@app.route("/users/<int:uid>/edit", methods=["POST"])
@roles_required("admin")
def edit_user(uid):
    u = db.session.get(User, uid)
    before = f"{u.role}/{u.active}"
    if request.form.get("role"):
        u.role = request.form["role"]
    if request.form.get("title") is not None:
        u.title = request.form.get("title")
    if request.form.get("toggle"):
        if u.id != current_user.id:
            u.active = not u.active
    if request.form.get("password"):
        u.set_password(request.form["password"])
    db.session.commit()
    log("user.update", "user", uid, before=before, after=f"{u.role}/{u.active}")
    flash("User updated.", "ok")
    return redirect(url_for("users"))


# ----------------------------------------------------------------- settings, audit, export
@app.route("/engagement/<int:eid>/settings", methods=["GET", "POST"])
@roles_required("lead", "finance_reviewer")
def settings(eid):
    e = get_e(eid)
    s = e.settings()
    if request.method == "POST":
        f = request.form
        before = e.settings_json
        for k in ("date_window_days", "fuzzy_ref_min", "desc_sim_min", "max_split_group",
                  "duplicate_window", "round_modulo", "recurrence_min_months",
                  "recurrence_min_count", "request_due_days"):
            if f.get(k):
                s[k] = int(f[k])
        for k in ("amount_tolerance", "threshold_band"):
            if f.get(k):
                s[k] = float(f[k])
        if f.get("approval_thresholds"):
            s["approval_thresholds"] = [int(x) for x in f["approval_thresholds"].replace(" ", "").split(",") if x]
        s["watchlist_ids"] = [x.strip() for x in f.get("watchlist_ids", "").splitlines() if x.strip()]
        s["watchlist_names"] = [x.strip() for x in f.get("watchlist_names", "").splitlines() if x.strip()]
        e.set_settings(s)
        if f.get("project_start"):
            e.project_start = pdate(f["project_start"])
        if f.get("project_end"):
            e.project_end = pdate(f["project_end"])
        db.session.commit()
        log("settings.update", "engagement", eid, before=before, after=e.settings_json)
        flash("Settings saved.", "ok")
        return redirect(url_for("settings", eid=eid))
    return render_template("settings.html", e=e, s=s)


@app.route("/audit")
@roles_required("lead", "finance_reviewer", "admin")
def audit():
    q = AuditLog.query
    if request.args.get("entity"):
        q = q.filter_by(entity=request.args["entity"])
    if request.args.get("user"):
        q = q.filter(AuditLog.user_email.like(f"%{request.args['user']}%"))
    return render_template("audit.html", logs=q.order_by(AuditLog.ts.desc()).limit(400).all())


@app.route("/engagement/<int:eid>/export")
@login_required
def export(eid):
    e = get_e(eid)
    data = reporting.build_workbook(e)
    log("export.xlsx", "engagement", eid)
    return send_file(io.BytesIO(data), as_attachment=True,
        download_name=f"verity_{secure_filename(e.name)}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/help")
@login_required
def help_page():
    return render_template("help.html")


@app.errorhandler(403)
def forbidden(err):
    return render_template("error.html", code=403,
                           msg="You don't have permission for that action."), 403


@app.errorhandler(404)
def notfound(err):
    return render_template("error.html", code=404, msg="Not found."), 404


def init_db():
    """Create tables and seed defaults. Safe to run concurrently in several
    gunicorn workers — a race just means the other worker got there first."""
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            db.session.rollback()
            app.logger.exception("create_all raced or failed; continuing")
        try:
            import seed
            seed.run(app, db)
        except Exception:
            db.session.rollback()
            app.logger.exception("seed raced or failed; continuing")


@app.route("/healthz")
def healthz():
    """Unauthenticated diagnostics — tells you whether the database is
    reachable and whether the default users exist."""
    from sqlalchemy import text
    info = {"app": "ok"}
    try:
        db.session.execute(text("SELECT 1"))
        info["database"] = "connected"
        info["driver"] = app.config["SQLALCHEMY_DATABASE_URI"].split(":")[0]
        info["users"] = User.query.count()
        info["engagements"] = Engagement.query.count()
    except Exception as ex:
        db.session.rollback()
        info["database"] = "ERROR"
        info["error"] = f"{type(ex).__name__}: {ex}"
    return info


@app.errorhandler(500)
def server_error(err):
    app.logger.exception("Unhandled error")
    return render_template("error.html", code=500,
        msg="Something went wrong. Check /healthz and the server logs."), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
