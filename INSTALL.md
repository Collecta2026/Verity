# Verity — Installation (local)

1. Install Python 3.11+ and clone/unzip this folder.
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env`. Leave `DATABASE_URL` blank to use local SQLite;
   set `SEED_DEMO=1` to load a demo engagement with planted fraud.
4. `python app.py` and open http://localhost:5000
5. Sign in as `lead@verity.local` / `Verity2026`.

Run order once signed in: create an engagement → upload sources → Reconcile →
Red flags → Build register → upload documents → Auto-link → Recompute → Export pack.

For production (Neon + Render + awspro.uk), see README.md.
