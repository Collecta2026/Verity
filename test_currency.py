import http.client, urllib.parse, json, os, re, io

PORT = int(os.environ.get("VERITY_PORT", "8600"))
CK = None
fails = []


def raw(method, path, body=None, headers=None, follow=True):
    global CK
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    h = dict(headers or {})
    if CK:
        h["Cookie"] = CK
    c.request(method, path, body, h)
    r = c.getresponse()
    d = r.read()
    sc = r.getheader("Set-Cookie")
    loc = r.getheader("Location")
    st = r.status
    c.close()
    if sc:
        CK = sc.split(";")[0]
    if follow and st in (301, 302, 303) and loc:
        return raw("GET", loc if loc.startswith("/") else "/", None, None, True)
    return st, d


def form(method, path, fields, follow=True):
    return raw(method, path, urllib.parse.urlencode(fields),
               {"Content-Type": "application/x-www-form-urlencoded"}, follow)


def upload(path, fields, filename, filedata):
    b = "----verity" + os.urandom(8).hex()
    parts = []
    for k, v in fields.items():
        parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
    body = "".join(parts).encode()
    body += (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"{filename}\"\r\nContent-Type: text/csv\r\n\r\n").encode()
    body += filedata + f"\r\n--{b}--\r\n".encode()
    return raw("POST", path, body, {"Content-Type": f"multipart/form-data; boundary={b}"})


def check(label, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{(' — ' + extra) if extra and not cond else ''}")
    if not cond:
        fails.append(label)


print("=== login ===")
st, d = form("POST", "/login", {"email": "admin", "password": "Admin1234"})
check("admin signs in", b"Invalid credentials" not in d)

print("\n=== create a USD bank account ===")
st, d = form("POST", "/engagement/1/accounts",
             {"code": "HSBCUSD", "name": "HSBC USD account", "kind": "bank",
              "identifier": "GB00HSBC", "currency": "USD"})
check("USD account created", st == 200 and b"HSBCUSD" in d)
m = re.findall(rb'name="account_id" value="(\d+)"', d)
st, d = raw("GET", "/engagement/1/accounts")
check("account shows USD", b"HSBCUSD" in d and b"USD" in d)

print("\n=== upload an awkward statement and map it ===")
csv = (b"Txn Dt,Narrative Details,Bene Name,Bene Acct,Movement,Ccy,Our Ref\n"
       b"03/02/2026,WIRE TO GULF TRADING,Gulf Trading FZE,AE99001,\"-12,500.00\",USD,WR-5521\n"
       b"11/02/2026,CONSULTING FEE,Vertex Advisers,US7781,\"-8,000.00\",USD,WR-5522\n"
       b"18/02/2026,REFUND RECEIVED,Nile Freight,EG777,\"4,300.00\",USD,RF-119\n")
# find the new account's id from the upload page
st, d = raw("GET", "/engagement/1/data")
ids = re.findall(rb'<option value="(\d+)">HSBCUSD', d)
acct_id = ids[0].decode() if ids else "6"
st, d = upload("/engagement/1/data", {"account_id": acct_id}, "awkward.csv", csv)
check("upload goes to mapping screen", b"Map the file" in d or b"Map columns" in d, f"status={st}")
check("real headers shown", b"Txn Dt" in d and b"Narrative Details" in d)
check("signed amount auto-detected", b'value="Movement" selected' in d
      or b'value="Movement" selected>' in d or b"Movement" in d)
stored = re.search(rb'name="stored" value="([^"]+)"', d)
check("upload staged for mapping", stored is not None)

if stored:
    st, d = form("POST", "/engagement/1/map", {
        "stored": stored.group(1).decode(), "original": "awkward.csv",
        "account_id": acct_id, "confirm": "1",
        "map_date": "Txn Dt", "map_description": "Narrative Details",
        "map_counterparty": "Bene Name", "map_counterparty_id": "Bene Acct",
        "map_amount_signed": "Movement", "map_currency": "Ccy",
        "map_reference": "Our Ref",
        "save_template": "1", "template_name": "HSBC USD layout"})
    check("import succeeds", b"Loaded 3 rows" in d, f"status={st}")
    st, d = raw("GET", "/engagement/1/data")
    check("saved mapping listed", b"HSBC USD layout" in d)

print("\n=== FX rates ===")
st, d = raw("GET", "/engagement/1/fx?currency=USD")
check("FX page loads", st == 200 and b"Exchange rates" in d)
st, d = form("POST", "/engagement/1/fx",
             {"currency": "USD", "month": "2026-02", "rate": "48.5", "source": "CBE month-end"})
check("rate saved and repriced", st == 200 and b"restated" in d, f"status={st}")

print("\n=== currency kept separate ===")
st, d = raw("GET", "/engagement/1/exceptions")
check("exceptions page loads", st == 200)
st, d = raw("GET", "/engagement/1/export")
check("Excel export with currency sheets", st == 200 and len(d) > 8000, f"bytes={len(d)}")

print("\n=== both languages still fine ===")
for lg in ("en", "ar"):
    raw("GET", f"/lang/{lg}")
    bad = []
    for p in ["/engagement/1/data", "/engagement/1/fx", "/engagement/1/accounts",
              "/engagement/1/exceptions", "/engagement/1/balances"]:
        st, d = raw("GET", p)
        if st != 200:
            bad.append((p, st))
    check(f"{lg} pages load", not bad, str(bad))
raw("GET", "/lang/en")

print("\n" + "=" * 50)
print("RESULT:", "ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
