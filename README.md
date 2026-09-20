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

## Deploy (Neon + Render + awspro.uk)
1. **Neon** — create a project (London), copy the connection string.
2. **GitHub** — push this folder to a private repo.
3. **Render** — New → Blueprint from the repo. Set `DATABASE_URL` to the Neon string;
   `SECRET_KEY` generates automatically; set `SEED_DEMO=1` for the first deploy only.
4. **Domain** — add e.g. `audit.awspro.uk` in Render, then a **CNAME** (not AAAA) at
   Names.co.uk pointing to the Render URL. SSL issues automatically.

## If you are ever locked out
Visit `/healthz` — it reports, without logging in, whether the database is reachable and how
many user accounts exist. If it shows `users: 0`, redeploy: the accounts are created on every
boot for any that are missing. To force a known admin account, set `ADMIN_EMAIL` and
`ADMIN_PASSWORD` in Render's environment and redeploy — that account is created (or its
password reset and reactivated) on startup. Clear both variables afterwards.

## Default logins (change immediately)
| Role | Email | Password |
|---|---|---|
| Administrator | admin@verity.local | Verity2026 |
| Forensic Lead | lead@verity.local | Verity2026 |
| Finance Reviewer | finance@verity.local | Verity2026 |
| Assistant | support1@verity.local / support2@verity.local | Verity2026 |

A missing document is a gap to be explained, not proof of wrongdoing on its own. Put each
material item to the individual concerned for a response before drawing conclusions.
