# Try Verity on your own computer first

This runs the **real, full application** on your machine — nothing goes online, and all data
stays in a local file. When you're happy with it, follow README.md to put it on Render.

## Start it
- **Windows:** double-click **run.bat**
- **Mac:** open Terminal in this folder and run **./run.sh** (or right-click run.sh → Open)

The first run takes a minute or two to set itself up; after that it starts in seconds.
It opens your browser at **http://localhost:5000**.

## Sign in
| Role | Email | Password |
|---|---|---|
| Forensic Lead | lead@verity.local | Verity2026 |
| Finance Reviewer | finance@verity.local | Verity2026 |
| Administrator | admin@verity.local | Verity2026 |

## What you'll see
A demo engagement ("Scientific Gate FY23-26") is pre-loaded with sample data that contains
planted fraud, so you can immediately click around:
1. **Overview** → press **1 Reconcile**, then **2 Red flags**, **3 Build register**, **4 Auto-link docs**, **5 Recompute**.
2. **Exceptions** → see the ghost entries, unrecorded outflows and the split payment it caught.
3. **Red flags** → Benford's Law plus the watchlist hit.
4. **Documents & vouching** → the two systematic-recurrence patterns (Falcon Services, Bright Future).
5. **Export pack** → downloads the Excel findings workbook.

## Test with your own data
Create a new engagement from the Dashboard, then upload your real statements and ledger under
**Data sources**. If a file won't parse, adjust the column mapping in **Settings**.

## Stop / reset
- Stop: close the launcher window (or Ctrl+C).
- Start completely fresh: delete the file **verity.db** in this folder, then launch again.
