import http.client, urllib.parse, re, os

PORT = int(os.environ.get("VERITY_PORT", "9100"))
CK = None
fails = []


def req(m, p, b=None, follow=True):
    global CK
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=25)
    h = {}
    if CK:
        h["Cookie"] = CK
    if b is not None:
        h["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(m, p, urllib.parse.urlencode(b), h)
    else:
        c.request(m, p, headers=h)
    r = c.getresponse()
    d = r.read()
    sc = r.getheader("Set-Cookie")
    loc = r.getheader("Location")
    st = r.status
    c.close()
    if sc:
        CK = sc.split(";")[0]
    if follow and st in (301, 302, 303) and loc:
        return req("GET", loc if loc.startswith("/") else "/")
    return st, d


def check(label, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{(' — ' + extra) if extra and not cond else ''}")
    if not cond:
        fails.append(label)


req("POST", "/login", {"email": "admin", "password": "Admin1234"})
st, d = req("GET", "/engagement/1/accounts")
check("currency is a dropdown", b"<select name=\"currency\"" in d)
check("Egyptian pound listed", "Egyptian pound".encode() in d)
check("US dollar listed", b"US dollar" in d)
check("Other option offered", b"Other" in d)

st, d = req("POST", "/engagement/1/accounts",
            {"code": "QNBUSD", "name": "QNB USD account", "kind": "bank",
             "identifier": "QA55", "currency": "USD"})
check("USD account created from dropdown", b"QNBUSD" in d and b"USD" in d)

st, d = req("POST", "/engagement/1/accounts",
            {"code": "JPYACC", "name": "Tokyo account", "kind": "bank",
             "identifier": "JP1", "currency": "", "currency_other": "jpy"})
check("custom currency accepted and upper-cased", b"JPYACC" in d and b"JPY" in d)

ids = re.findall(rb'action="/engagement/1/accounts/(\d+)/edit"', d)
check("edit form rendered per account", bool(ids))
if ids:
    aid = ids[0].decode()
    st, d = req("POST", f"/engagement/1/accounts/{aid}/edit",
                {"name": "Commercial International Bank", "identifier": "EG10",
                 "currency": "USD"})
    check("existing account currency changed", b"updated" in d or b"restated" in d)
    st, d = req("POST", f"/engagement/1/accounts/{aid}/edit",
                {"name": "Commercial International Bank", "identifier": "EG10",
                 "currency": "EGP"})
    check("changed back to EGP", b"updated" in d or b"restated" in d)

st, d = req("GET", "/engagement/1/fx?currency=USD")
check("FX page loads for USD", st == 200)
st, d = req("GET", "/")
check("dashboard base-currency dropdown", b"<select name=\"currency\"" in d)

for lg in ("en", "ar"):
    req("GET", f"/lang/{lg}")
    st, d = req("GET", "/engagement/1/accounts")
    check(f"accounts page loads ({lg})", st == 200)
req("GET", "/lang/en")

print("\nRESULT:", "ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
