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


def body_for(item, cfg):
    """cfg: the "x" section of config.json (or a plain footer string)."""
    if item["type"] == "poll":
        return {"text": with_footer(no_links(item["question"]), cfg, item),
                "poll": {"options": [o[:25] for o in item["options"]], "duration_minutes": 1440}}
    return {"text": with_footer(no_links(item["text"]), cfg, item)}


def weight(text):
    """X counts most emoji and CJK as 2 characters."""
    return sum(2 if ord(c) > 0x10FF else 1 for c in text)


def topic_tags(item, cfg):
    """Only hashtags chosen for this post AND on the allowed list. No tag is ever added without a reason."""
    allowed = {h.lower() for h in cfg.get("allowed_hashtags", [])}
    picked = [h for h in item.get("tags", []) if h.lower() in allowed]
    return picked[:cfg.get("max_topic_hashtags", 2)]


def footer_parts(cfg, item):
    """By priority: Telegram in bio, brand ($ cashtag + hashtag), then topical hashtags of this post."""
    if isinstance(cfg, str):
        return [("bio" if "in bio" in cfg.lower() else "tag", cfg)] if cfg else []
    parts = []
    if cfg.get("footer"):
        parts.append(("bio", cfg["footer"]))
    brand = " ".join(h for h in (cfg.get("cashtag"), *cfg.get("hashtags", [])) if h)
    if brand:
        parts.append(("tag", brand))
    return parts + [("tag", h) for h in topic_tags(item, cfg)]


def with_footer(text, cfg, item=None):
    """Adds footer parts by priority while the post stays within 280; the post text itself is never cut."""
    bio, tags = "", []
    for kind, part in footer_parts(cfg, item or {}):
        if kind == "bio" and "in bio" in text.lower():
            part = " ".join(w for w in part.split() if w.startswith(("#", "$")))
            kind = "tag"
            if not part:
                continue
        if kind == "tag":  # never repeat a tag the post text already contains
            part = " ".join(w for w in part.split() if w.lower() not in text.lower())
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
