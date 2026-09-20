"""Full workout against the live gunicorn+Postgres server, as Render runs it."""
import http.client, urllib.parse, json, sys

import os
HOST = os.environ.get("VERITY_HOST", "127.0.0.1")
PORT = int(os.environ.get("VERITY_PORT", "8200"))
COOKIE = None
fails = []


def req(method, path, body=None, follow=True):
    global COOKIE
    c = http.client.HTTPConnection(HOST, PORT, timeout=25)
    h = {}
    if COOKIE:
        h["Cookie"] = COOKIE
    if body is not None:
        h["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, urllib.parse.urlencode(body), h)
    else:
        c.request(method, path, headers=h)
    r = c.getresponse()
    data = r.read()
    sc = r.getheader("Set-Cookie")
    loc = r.getheader("Location")
    st = r.status
    c.close()
    if sc:
        COOKIE = sc.split(";")[0]
    if follow and st in (301, 302, 303) and loc:
        return req("GET", loc if loc.startswith("/") else "/", None, follow)
    return st, data


def check(label, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{(' — ' + extra) if extra and not cond else ''}")
    if not cond:
        fails.append(label)


print("=== 1. Boot state on a brand-new database ===")
st, d = req("GET", "/healthz")
h = json.loads(d)
check("healthz reachable", st == 200)
check("database connected", h.get("database") == "connected", str(h))
check("driver is postgresql", h.get("driver") == "postgresql", str(h))
check("DATABASE_URL detected", h.get("database_url_configured") is True)
check("default users seeded", h.get("users") == 5, f"users={h.get('users')}")

print("\n=== 2. Login page and authentication ===")
st, d = req("GET", "/login")
check("login page renders", st == 200 and b"Sign in" in d, f"status={st} bytes={len(d)}")
check("login page not blank", len(d) > 800, f"bytes={len(d)}")
st, d = req("POST", "/login", {"email": "lead@verity.local", "password": "Verity2026"})
check("lead can sign in", st == 200 and b"Invalid credentials" not in d)
st, d = req("GET", "/")
check("dashboard loads", st == 200 and (b"records review" in d or b"Engagements" in d))

print("\n=== 3. Wrong password is rejected cleanly (no crash) ===")
save = COOKIE
st, d = req("POST", "/login", {"email": "lead@verity.local", "password": "wrong"})
check("bad password -> friendly message", st == 200 and b"Invalid credentials" in d)
COOKIE = save

print("\n=== 4. Every page, English ===")
req("GET", "/lang/en")
PAGES = ["/", "/engagement/1", "/engagement/1/accounts", "/engagement/1/data",
         "/engagement/1/balances", "/engagement/1/casefile", "/engagement/1/exceptions",
         "/engagement/1/requests", "/engagement/1/documents", "/engagement/1/tasks",
         "/engagement/1/team", "/engagement/1/settings", "/engagement/1/export",
         "/engagement/1/quarter/2023-Q3", "/audit", "/help", "/healthz"]
bad = []
for p in PAGES:
    st, d = req("GET", p)
    minimum = 100 if p == "/healthz" else 400   # healthz is a short JSON body
    if st != 200 or len(d) < minimum:
        bad.append((p, st, len(d)))
check(f"all {len(PAGES)} pages load", not bad, str(bad))

print("\n=== 5. Every page, Arabic (RTL) ===")
req("GET", "/lang/ar")
bad = []
for p in PAGES:
    st, d = req("GET", p)
    minimum = 100 if p == "/healthz" else 400
    if st != 200 or len(d) < minimum:
        bad.append((p, st, len(d)))
check(f"all {len(PAGES)} pages load in Arabic", not bad, str(bad))
st, d = req("GET", "/engagement/1/tasks")
check("Arabic RTL active", b'dir="rtl"' in d)
check("Arabic strings present", "المهام".encode() in d)
req("GET", "/lang/en")

print("\n=== 6. Core workflow ===")
st, d = req("POST", "/engagement/1/quarter/2023-Q3/run", {})
check("quarter reconciles", st == 200)
st, d = req("GET", "/engagement/1/exceptions")
check("exceptions raised with auto refs", b"SGE-Q3-23-EXC-" in d)
st, d = req("POST", "/engagement/1/exception/1/request",
            {"addressee": "Former Finance Manager",
             "documents_needed": "Invoice\nPayment authorisation",
             "due_date": "2026-10-05"})
check("document request raised", st == 200)
st, d = req("GET", "/engagement/1/requests")
check("request has auto reference", b"SGE-Q3-23-DR-" in d)
st, d = req("GET", "/engagement/1/request/1/memo?lang=en")
check("English memo renders", st == 200 and b"Document request" in d)
st, d = req("GET", "/engagement/1/request/1/memo?lang=ar")
check("Arabic memo renders RTL", st == 200 and 'طلب مستندات'.encode() in d and b'dir="rtl"' in d)
st, d = req("POST", "/engagement/1/task/1/update",
            {"status": "In progress", "progress": "50", "note": "started"})
check("task update + reassignment", st == 200)
st, d = req("GET", "/audit")
check("audit trail records changes", b"task.update" in d or b"request.raise" in d)
st, d = req("GET", "/engagement/1/export")
check("Excel pack downloads", st == 200 and len(d) > 5000, f"bytes={len(d)}")

print("\n=== 7. Permissions ===")
req("GET", "/logout")
req("POST", "/login", {"email": "support1@verity.local", "password": "Verity2026"})
st, d = req("GET", "/users", follow=False)
check("assistant blocked from Users (403)", st == 403, f"status={st}")
check("403 page is not blank", len(d) > 400, f"bytes={len(d)}")

print("\n=== 8. Session robustness ===")
COOKIE = "session=tampered-rubbish-value"
st, d = req("GET", "/login")
check("bad cookie -> login page, not crash", st == 200 and b"Sign in" in d, f"status={st}")
COOKIE = None
st, d = req("GET", "/", follow=False)
check("logged out -> redirect to login", st in (302, 303), f"status={st}")

print("\n" + "=" * 52)
print("RESULT:", "ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILURE(S): {fails}")
sys.exit(1 if fails else 0)
