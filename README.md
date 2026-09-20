# Verity — Forensic Reconciliation Platform

Quarter-by-quarter reconciliation of a general ledger against bank and mobile-wallet
statements, with document chasing, team task management and full traceability.

Stack: **Flask + SQLAlchemy on Neon Postgres, GitHub → Render**, served on a subdomain
of **awspro.uk**. Same architecture as Collecta and Time.

## Languages
Full English and Arabic interface with a toggle in the top bar (and on the sign-in page).
Arabic switches the whole application to right-to-left. Document request memos can be
produced in either language independently of the interface language, so an Arabic memo can
be sent to an Arabic-speaking recipient while you work in English.

## What it does
- **Any accounts** — CIB, NBE, Vodafone Cash, InstaPay and the ledger are set up by default;
  add any number of further banks, wallets or ledgers at any time, each with its own column mapping.
- **Period engine** — splits the records period into quarters and months; you work one quarter
  at a time, month by month, and sign each one off.
- **Cascade matching** — reference exact → reference fuzzy → value + date + party → value + date
  → description similarity → split/aggregation. Every match records *how* it matched and a
  confidence score, so evidential weight is never lost.
- **Month-end reconciliation & balance continuity** — opening/closing per account per month,
  checking the statement foots, each opening agrees to the prior closing, and no period is missing.
- **Exceptions & document requests** — every unresolved item gets an automatic reference and
  enters a clearance queue; requests generate a printable/emailable memo, are assigned, chased
  and closed, and accepting the documents clears the exception.
- **Auto references everywhere** — `SGE-Q2-23-EXC-0001`, `-DR-0001`, `SGE-DOC-000001`, `SGE-T-0001`.
- **Quarterly rationale** — written analysis locked on sign-off, rolling into a cumulative case file.
- **Project & team** — work programme across the project window, assignment, joint ownership,
  reassignment, periodic progress updates, per-person activity report, and a user matrix.
- **Audit trail** — append-only, recording the before and after value of every change.
- **Bilingual** — English/Arabic toggle, RTL layout, bilingual request memos.

## Local run
```
pip install -r requirements.txt
cp .env.example .env     # SEED_DEMO=1 loads a demo investigation
python app.py            # http://localhost:5000
```

## Render start command
Either `gunicorn wsgi:app` or `gunicorn app:app` works — the app initialises its database on
first request if the WSGI entry point didn't do it. Python is pinned to 3.12 by
`.python-version` and `runtime.txt`, because newer versions have no PostgreSQL driver wheels yet.

## Deploy (Neon + Render + awspro.uk)
1. **Neon** — create a project (London), copy the connection string.
2. **GitHub** — push this folder to a private repo.
3. **Render** — New → Blueprint from the repo. Set `DATABASE_URL` to the Neon string;
   `SECRET_KEY` generates automatically; set `SEED_DEMO=1` for the first deploy only.
4. **Domain** — add e.g. `audit.awspro.uk` in Render, then a **CNAME** (not AAAA) at
   Names.co.uk pointing to the Render URL. SSL issues automatically.

## Verified
Tested end to end against PostgreSQL under gunicorn (the exact Render stack) on a cold-start
empty database: 28 checks covering boot, seeding, login, every page in both languages, the
full reconcile → exception → request → memo → export workflow, permissions and session
handling. Re-run it yourself against a running instance with `python test_e2e.py`
(edit HOST/PORT at the top).

## If DATABASE_URL is missing
The app will **not** silently fall back to local file storage when hosted — that storage is
erased on every deploy, which makes accounts and data vanish without warning. Instead every
page shows a setup notice telling you to set `DATABASE_URL`. Locally (on your own machine)
it still uses SQLite automatically, so `run.bat` needs no setup.

## Troubleshooting a deploy
- **Blank page or an error** — open `/healthz` first. It needs no login and reports whether the
  database is reachable, which driver is in use, and how many accounts exist.
- **Full traceback on screen** — set `SHOW_ERRORS=1` in Render's environment and redeploy, then
  reproduce. Set it back to `0` afterwards; it is off by default so details are never shown to users.
- **Server logs** — Render's Logs tab carries the full stack trace for every error.

## If you are ever locked out
Visit `/healthz` — it reports, without logging in, whether the database is reachable and how
many user accounts exist. If it shows `users: 0`, redeploy: the accounts are created on every
boot for any that are missing. To force a known admin account, set `ADMIN_EMAIL` and
`ADMIN_PASSWORD` in Render's environment and redeploy — that account is created (or its
password reset and reactivated) on startup. Clear both variables afterwards.

## Signing in
One account is created on a live deployment:

| Username | Password |
|---|---|
| `admin` | `Admin1234` |

Sign in with that, then add your team from **Users** — each person can have a short username
(`khaled`) or an email address, whichever you prefer. Change the admin password once you're in.

Running locally with `SEED_DEMO=1` also creates a demo team (`lead@verity.local` and others,
password `Verity2026`) so the demo engagement has people to assign tasks to.

A missing document is a gap to be explained, not proof of wrongdoing on its own. Put each
material item to the individual concerned for a response before drawing conclusions.
