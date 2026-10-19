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
    """footer: the x config (dict) or a plain footer string."""
    if item["type"] == "poll":
        return {"text": with_footer(no_links(item["question"]), footer, item.get("id", "")),
                "poll": {"options": [o[:25] for o in item["options"]], "duration_minutes": 1440}}
    return {"text": with_footer(no_links(item["text"]), footer, item.get("id", ""))}


def weight(text):
    """X counts most emoji and CJK as 2 characters."""
    return sum(2 if ord(c) > 0x10FF else 1 for c in text)


def footer_parts(cfg, key):
    """Ordered by priority: cashtag, 'Telegram in bio', brand hashtag, then rotating viral hashtags."""
    if isinstance(cfg, str):
        return [("bio" if "in bio" in w.lower() else "tag", w) for w in [cfg] if w]
    viral = cfg.get("viral_hashtags", [])
    start = sum(map(ord, key)) % len(viral) if viral else 0
    picks = [viral[(start + i) % len(viral)] for i in range(min(cfg.get("viral_per_post", 3), len(viral)))]
    parts = [("tag", cfg["cashtag"])] if cfg.get("cashtag") else []
    if cfg.get("footer"):
        parts.append(("bio", cfg["footer"]))
    return parts + [("tag", h) for h in cfg.get("hashtags", []) + picks]


def with_footer(text, cfg, key=""):
    """Adds footer parts by priority while the post stays within 280; the post text itself is never cut."""
    bio, tags = "", []
    for kind, part in footer_parts(cfg, key):
        if kind == "bio" and "in bio" in text.lower():
            part = " ".join(w for w in part.split() if w.startswith(("#", "$")))
            kind = "tag"
            if not part:
                continue
        new_bio, new_tags = (part, tags) if kind == "bio" else (bio, tags + part.split())
        tail = "\n".join(x for x in (new_bio, " ".join(new_tags)) if x)
        if weight(f"{text}\n\n{tail}") <= 280:
            bio, tags = new_bio, new_tags
    tail = "\n".join(x for x in (bio, " ".join(tags)) if x)
    return f"{text}\n\n{tail}" if tail else text[:280]


def post(item, footer=""):
    req = urllib.request.Request(URL, json.dumps(body_for(item, footer)).encode(),
                                 {"Authorization": auth_header("POST", URL), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["data"]["id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"X {e.code}: {e.read().decode()[:300]}")
