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
        return {"text": with_footer(no_links(item["question"]), footer),
                "poll": {"options": [o[:25] for o in item["options"]], "duration_minutes": 1440}}
    return {"text": with_footer(no_links(item["text"]), footer)}


def with_footer(text, footer):
    """Adds the footer ("Telegram in bio" + hashtag) when it fits; avoids saying "in bio" twice."""
    if footer and "in bio" in text.lower() and "in bio" in footer.lower():
        footer = " ".join(w for w in footer.split() if w.startswith("#"))
    if not footer or len(text) + len(footer) + 2 > 280:
        return text[:280]
    return f"{text}\n\n{footer}"


def post(item, footer=""):
    req = urllib.request.Request(URL, json.dumps(body_for(item, footer)).encode(),
                                 {"Authorization": auth_header("POST", URL), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["data"]["id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"X {e.code}: {e.read().decode()[:300]}")
