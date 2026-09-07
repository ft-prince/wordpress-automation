"""Google Search Console + GA4 over plain OAuth 2.0 and urllib. No google-* packages.
Credentials: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN in .env.
One Google login covers every site; each site names its own GSC + GA4 property."""
import json
import secrets as pysecrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from django.utils import timezone

from core import secrets, sites
from core.models import Ga4Row, GscRow, Sync

SCOPES = "https://www.googleapis.com/auth/webmasters.readonly https://www.googleapis.com/auth/analytics.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GSC_URL = "https://www.googleapis.com/webmasters/v3"
GA4_URL = "https://analyticsdata.googleapis.com/v1beta"
REDIRECT_PATH = "/api/google/callback"
DEFAULT_DAYS = 90
GSC_LAG_DAYS = 3        # Search Console data is final ~3 days late
PAGE_ROWS = 25000
_pending_state = {}
_access = {"token": None, "expires": 0}


def _env():
    return secrets._parse()


def configured():
    e = _env()
    return bool(e.get("GOOGLE_CLIENT_ID") and e.get("GOOGLE_CLIENT_SECRET"))


def connected():
    return configured() and bool(_env().get("GOOGLE_REFRESH_TOKEN"))


def auth_url(base_url):
    """Step 1: send the browser here. State is checked on the way back."""
    if not configured():
        raise ValueError("add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Secrets first")
    state = pysecrets.token_urlsafe(16)
    _pending_state[state] = True
    params = {"client_id": _env()["GOOGLE_CLIENT_ID"], "redirect_uri": base_url + REDIRECT_PATH,
              "response_type": "code", "scope": SCOPES, "access_type": "offline", "prompt": "consent",
              "state": state}
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def _token_request(fields):
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Google token error {exc.code}: {exc.read().decode('utf8', 'replace')[:300]}")


def exchange_code(code, state, base_url):
    """Step 2: Google redirected back. Store the refresh token, never show it."""
    if not _pending_state.pop(state, None):
        raise ValueError("OAuth state mismatch - start the connection again from the dashboard")
    e = _env()
    data = _token_request({"code": code, "client_id": e["GOOGLE_CLIENT_ID"], "client_secret": e["GOOGLE_CLIENT_SECRET"],
                           "redirect_uri": base_url + REDIRECT_PATH, "grant_type": "authorization_code"})
    if not data.get("refresh_token"):
        raise RuntimeError("Google returned no refresh token - remove the app at myaccount.google.com/permissions and retry")
    secrets.set_value("GOOGLE_REFRESH_TOKEN", data["refresh_token"])
    _access.update(token=data.get("access_token"), expires=timezone.now().timestamp() + int(data.get("expires_in", 0)) - 60)
    return True


def disconnect():
    secrets.set_value("GOOGLE_REFRESH_TOKEN", "")
    _access.update(token=None, expires=0)


def _access_token():
    if _access["token"] and _access["expires"] > timezone.now().timestamp():
        return _access["token"]
    e = _env()
    if not e.get("GOOGLE_REFRESH_TOKEN"):
        raise ValueError("Google is not connected - open Sites and connect Google")
    data = _token_request({"refresh_token": e["GOOGLE_REFRESH_TOKEN"], "client_id": e["GOOGLE_CLIENT_ID"],
                           "client_secret": e["GOOGLE_CLIENT_SECRET"], "grant_type": "refresh_token"})
    _access.update(token=data["access_token"], expires=timezone.now().timestamp() + int(data.get("expires_in", 3600)) - 60)
    return _access["token"]


def _call(url, payload=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"},
                                 method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Google API {exc.code}: {exc.read().decode('utf8', 'replace')[:300]}")


def list_properties():
    """What the connected Google account can see - helps pick the right ids."""
    gsc = [s["siteUrl"] for s in _call(f"{GSC_URL}/sites").get("siteEntry", [])]
    ga4 = []
    try:
        summaries = _call("https://analyticsadmin.googleapis.com/v1beta/accountSummaries").get("accountSummaries", [])
        for acc in summaries:
            for p in acc.get("propertySummaries", []):
                ga4.append({"id": p["property"].split("/")[-1], "name": p.get("displayName", "")})
    except RuntimeError:
        pass  # admin scope not granted; ids can be typed by hand
    return {"gsc": gsc, "ga4": ga4}


# -- sync --------------------------------------------------------------------------

def _window(days, lag=0):
    end = date.today() - timedelta(days=lag)
    return end - timedelta(days=days), end


def sync_gsc(site=None, days=DEFAULT_DAYS, log=print):
    env = sites.env_for(site)
    prop = env.get("gsc_property")
    if not prop:
        raise ValueError("set the Search Console property for this site first (Sites page)")
    start, end = _window(days, GSC_LAG_DAYS)
    sync = Sync.objects.create(site=env["_site_id"], source="gsc", date_from=start, date_to=end)
    try:
        rows, offset = [], 0
        while True:
            data = _call(f"{GSC_URL}/sites/{urllib.parse.quote(prop, safe='')}/searchAnalytics/query", {
                "startDate": start.isoformat(), "endDate": end.isoformat(),
                "dimensions": ["date", "query", "page"], "rowLimit": PAGE_ROWS, "startRow": offset,
                "dataState": "final"})
            batch = data.get("rows", [])
            rows += batch
            log(f"gsc: {len(rows)} rows")
            if len(batch) < PAGE_ROWS:
                break
            offset += PAGE_ROWS
        GscRow.objects.filter(site=env["_site_id"], date__gte=start, date__lte=end).delete()
        GscRow.objects.bulk_create([
            GscRow(site=env["_site_id"], date=r["keys"][0], query=r["keys"][1][:300], page=r["keys"][2][:1000],
                   clicks=int(r.get("clicks", 0)), impressions=int(r.get("impressions", 0)),
                   ctr=float(r.get("ctr", 0)), position=float(r.get("position", 0)))
            for r in rows], batch_size=1000)
        sync.rows = len(rows)
    except Exception as exc:
        sync.error = str(exc)[:500]
        raise
    finally:
        sync.finished_at = timezone.now()
        sync.save()
    return sync.rows


def sync_ga4(site=None, days=DEFAULT_DAYS, log=print):
    env = sites.env_for(site)
    prop = (env.get("ga4_property") or "").replace("properties/", "")
    if not prop:
        raise ValueError("set the GA4 property id for this site first (Sites page)")
    start, end = _window(days, 1)
    sync = Sync.objects.create(site=env["_site_id"], source="ga4", date_from=start, date_to=end)
    try:
        rows, offset = [], 0
        while True:
            data = _call(f"{GA4_URL}/properties/{prop}:runReport", {
                "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
                "dimensions": [{"name": "date"}, {"name": "landingPagePlusQueryString"}, {"name": "sessionDefaultChannelGroup"}],
                "metrics": [{"name": "sessions"}, {"name": "totalUsers"}, {"name": "keyEvents"}],
                "limit": 100000, "offset": offset})
            batch = data.get("rows", [])
            rows += batch
            log(f"ga4: {len(rows)} rows")
            if len(batch) < 100000:
                break
            offset += 100000
        Ga4Row.objects.filter(site=env["_site_id"], date__gte=start, date__lte=end).delete()
        root = env["WEBSITE_LINK"].rstrip("/")
        Ga4Row.objects.bulk_create([
            Ga4Row(site=env["_site_id"], date=_ga_date(r["dimensionValues"][0]["value"]),
                   landing_page=(root + r["dimensionValues"][1]["value"].split("?")[0])[:1000],
                   channel=r["dimensionValues"][2]["value"][:64],
                   sessions=int(float(r["metricValues"][0]["value"])), users=int(float(r["metricValues"][1]["value"])),
                   conversions=float(r["metricValues"][2]["value"]))
            for r in rows], batch_size=1000)
        sync.rows = len(rows)
    except Exception as exc:
        sync.error = str(exc)[:500]
        raise
    finally:
        sync.finished_at = timezone.now()
        sync.save()
    return sync.rows


def _ga_date(s):
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def status(site=None):
    site_id = sites.env_for(site)["_site_id"]
    last = {src: Sync.objects.filter(site=site_id, source=src).order_by("-id").first() for src in ("gsc", "ga4")}
    return {
        "configured": configured(), "connected": connected(),
        "gsc_property": sites.env_for(site).get("gsc_property", ""), "ga4_property": sites.env_for(site).get("ga4_property", ""),
        "last_sync": {src: ({"at": s.finished_at.isoformat(timespec="seconds") if s.finished_at else None, "rows": s.rows,
                             "from": s.date_from.isoformat() if s.date_from else None, "to": s.date_to.isoformat() if s.date_to else None,
                             "error": s.error} if s else None) for src, s in last.items()},
        "rows": {"gsc": GscRow.objects.filter(site=site_id).count(), "ga4": Ga4Row.objects.filter(site=site_id).count()},
    }
