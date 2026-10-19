"""Contenuti: storico persistente e controllo anti-ripetizione (testo identico, testo simile, stesso concetto)."""
import difflib, re, unicodedata


def text_of(item):
    return item.get("text") or item.get("question", "")


def normalize(text):
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if c.isascii())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def similarity(a, b):
    a, b = normalize(a), normalize(b)
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 1.0
    return max(ratio, jaccard)


def is_duplicate(item, history, threshold):
    """history: elementi già pubblicati su QUALSIASI piattaforma. Rifiuta id, concetto o testo già usati/simili."""
    text = text_of(item)
    for old in history:
        if old["id"] == item["id"] or old.get("concept") == item.get("concept"):
            return f"già usato ({old['id']})"
        if normalize(old["text"]) == normalize(text):
            return f"testo identico a {old['id']}"
        if similarity(old["text"], text) >= threshold:
            return f"troppo simile a {old['id']}"
    return None


def pick(pool, history, rotation, last_type, threshold):
    """Prossimo contenuto: segue la rotazione dei tipi dopo l'ultimo pubblicato, salta quelli già usati o simili."""
    start = (rotation.index(last_type) + 1) % len(rotation) if last_type in rotation else 0
    for t in rotation[start:] + rotation[:start]:
        for item in pool:
            if item["type"] == t and not is_duplicate(item, history, threshold):
                return item
    return None


def remaining(pool, history, threshold):
    return sum(1 for item in pool if not is_duplicate(item, history, threshold))


def record(history, item, platform, ts):
    history.append({"id": item["id"], "concept": item.get("concept"), "type": item["type"],
                    "platform": platform, "text": text_of(item), "ts": ts})
