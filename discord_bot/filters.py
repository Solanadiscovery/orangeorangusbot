"""Pure moderation rules (no Discord), so they can be tested offline."""
import fnmatch, re, time
from collections import defaultdict, deque

URL = re.compile(r"https?://([^/\s]+)", re.I)


def scam_match(text, patterns):
    low = " ".join(text.lower().split())
    return next((p for p in patterns if fnmatch.fnmatchcase(low, p)), None)


def bad_link(text, allowed_domains):
    for host in URL.findall(text):
        host = host.lower().split(":")[0]
        if not any(host == d or host.endswith("." + d) for d in allowed_domains):
            return host
    return None


def too_many_caps(text, ratio, min_length):
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= min_length and sum(c.isupper() for c in letters) / len(letters) >= ratio


class Tracker:
    """Remembers each user's recent messages for flood and duplicate checks."""

    def __init__(self, spam_messages, spam_seconds, duplicate_limit, clock=time.monotonic):
        self.spam_messages, self.spam_seconds, self.duplicate_limit = spam_messages, spam_seconds, duplicate_limit
        self.clock = clock
        self.times = defaultdict(lambda: deque(maxlen=spam_messages))
        self.texts = defaultdict(lambda: deque(maxlen=duplicate_limit))

    def add(self, user_id, text):
        """Returns 'flooding', 'repeated messages' or None."""
        now = self.clock()
        times, texts = self.times[user_id], self.texts[user_id]
        times.append(now)
        texts.append(" ".join(text.lower().split()))
        if len(times) == self.spam_messages and now - times[0] <= self.spam_seconds:
            times.clear()
            return "flooding"
        if len(texts) == self.duplicate_limit and texts[0] and len(set(texts)) == 1:
            texts.clear()
            return "repeated messages"
        return None


def check(message_text, mentions, in_no_link_area, cfg):
    """Checks a single message. Returns (reason, timeout?) or None."""
    hit = scam_match(message_text, cfg["scam_patterns"])
    if hit:
        return f"possible scam ({hit})", False
    if mentions >= cfg["mention_limit"]:
        return f"mention spam ({mentions})", True
    if in_no_link_area:
        host = bad_link(message_text, cfg["allowed_domains"])
        if host:
            return f"link not allowed ({host})", False
    if too_many_caps(message_text, cfg["caps_ratio"], cfg["caps_min_length"]):
        return "too many capital letters", True
    return None


def og_picks(granted, member_ids, limit):
    """Which members get OG: the earliest joiners, until `limit` slots are used.
    `granted` is every id that ever got OG, so a slot is never given twice."""
    free = limit - len(granted)
    return [m for m in member_ids if m not in granted][:max(free, 0)]
