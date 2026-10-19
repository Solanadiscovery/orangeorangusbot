"""X API v2 (OAuth 1.0a utente): pubblicazione di post e sondaggi."""
import base64, hashlib, hmac, json, os, re, time, urllib.error, urllib.parse, urllib.request, uuid

KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")
URL = "https://api.x.com/2/tweets"


def enabled():
    return all(os.environ.get(k, "").strip() for k in KEYS)


def auth_header(method, url):
    key, secret, token, token_secret = (os.environ[k].strip() for k in KEYS)
    oauth = {"oauth_consumer_key": key, "oauth_nonce": uuid.uuid4().hex, "oauth_signature_method": "HMAC-SHA1",
             "oauth_timestamp": str(int(time.time())), "oauth_token": token, "oauth_version": "1.0"}
    q = lambda v: urllib.parse.quote(v, safe="")
    base = f"{method}&{q(url)}&{q('&'.join(f'{q(k)}={q(v)}' for k, v in sorted(oauth.items())))}"
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(f"{q(secret)}&{q(token_secret)}".encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in oauth.items())


LINK = re.compile(r"\s*(https?://\S+|\bt\.me/\S+)")


def no_links(text):
    """Telegram link is in the X bio: posts never carry URLs."""
    return LINK.sub("", text).strip()


def body_for(item, footer):
    if item["type"] == "poll":
        return {"text": no_links(item["question"]), "poll": {"options": [o[:25] for o in item["options"]], "duration_minutes": 1440}}
    item = {**item, "text": no_links(item["text"])}
    text = item["text"] if not footer or len(item["text"]) + len(footer) + 2 > 280 else f"{item['text']}\n\n{footer}"
    return {"text": text[:280]}


def post(item, footer=""):
    req = urllib.request.Request(URL, json.dumps(body_for(item, footer)).encode(),
                                 {"Authorization": auth_header("POST", URL), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["data"]["id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"X {e.code}: {e.read().decode()[:300]}")
