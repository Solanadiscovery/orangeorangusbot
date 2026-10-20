"""Peel Points: community points for missions (Telegram DM commands). Points have no monetary value.

Verification: Telegram membership and invites are checked with the Bot API; X posts are checked with the public
oEmbed endpoint (author, text, post date from the post id). When X cannot be reached the post waits for an admin.
A random sample of auto-approved posts is also sent to the admin, who can revoke them.
All data lives in points.json (committed by the bot like state.json)."""
import datetime, hashlib, html, json, re, urllib.error, urllib.parse, urllib.request

import tg

TWEET = re.compile(r"^https://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d{5,25})/?(?:\?.*)?$")
HANDLE = re.compile(r"^@?([A-Za-z0-9_]{1,15})$")
X_EPOCH = 1288834974657  # ms: X post ids embed their creation time
OPEN_STATES = ("member", "administrator", "creator")


def tweet_time(tid):
    return datetime.datetime.fromtimestamp(((int(tid) >> 22) + X_EPOCH) / 1000, datetime.timezone.utc)


def oembed(url):
    """Public X endpoint, no key needed. Returns {author, text}; raises LookupError if the post does not exist."""
    q = urllib.parse.urlencode({"url": url, "omit_script": "1", "dnt": "true"})
    try:
        with urllib.request.urlopen(f"https://publish.twitter.com/oembed?{q}", timeout=15) as r:
            j = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            raise LookupError("post not found or not public")
        raise
    author = urllib.parse.urlparse(j.get("author_url", "")).path.strip("/").lower()
    text = html.unescape(re.sub(r"<[^>]+>", " ", j.get("html", "")))
    return {"author": author, "text": text}


# Badges are earned from what the member did (status only, no monetary value). id: (icon, name, how, test(user, posts))
BADGES = {
    "first": ("🥇", "First Peel", "Earn your first points", lambda u, n: u["pts"] > 0),
    "streak3": ("🔥", "On Fire", "3-day check-in streak", lambda u, n: u.get("best_streak", 0) >= 3),
    "streak7": ("⚡", "Unstoppable", "7-day check-in streak", lambda u, n: u.get("best_streak", 0) >= 7),
    "voice": ("✍️", "X Voice", "1 verified post on X", lambda u, n: n >= 1),
    "megaphone": ("📣", "Megaphone", "5 verified posts on X", lambda u, n: n >= 5),
    "recruiter": ("🤝", "Recruiter", "Bring 3 friends", lambda u, n: u["invites"] >= 3),
    "pack": ("🦍", "Pack Leader", "Bring 10 friends", lambda u, n: u["invites"] >= 10),
}


class Points:
    def __init__(self, bot, data, fetch=oembed):
        self.b, self.d, self.fetch = bot, data, fetch
        for k, v in (("users", {}), ("tweets", {}), ("links", {}), ("refs", []), ("referred", {}), ("open", False), ("announced", False)):
            self.d.setdefault(k, v)

    # --- helpers -------------------------------------------------------------
    @property
    def cfg(self):
        return self.b.cfg["points"]

    def now(self):
        return self.b.clock()

    def say(self, uid, text, markup=None):
        f = {"chat_id": uid, "text": text, "link_preview_options": {"is_disabled": True}}
        if markup:
            f["reply_markup"] = markup
        try:
            return tg.call("sendMessage", f)
        except tg.TelegramError as e:
            print(f"Points: message to {uid} not sent: {e}", flush=True)

    def user(self, uid, name=""):
        u = self.d["users"].setdefault(str(uid), {"name": "", "pts": 0, "x": "", "checkin": "", "day": {"d": "", "p": 0},
                                                  "joined": False, "strikes": 0, "invites": 0, "first": self.now().isoformat()})
        if name:
            u["name"] = name[:20]
        return u

    def award(self, uid, n, why, capped=True):
        """Adds points up to the daily cap (invites are limited by max_invites instead). Returns the points given."""
        u, today = self.user(uid), self.now().strftime("%Y-%m-%d")
        if u["strikes"] >= 2:
            return 0
        if u["day"]["d"] != today:
            u["day"] = {"d": today, "p": 0}
        n = max(0, min(n, self.cfg["daily_cap"] - u["day"]["p"])) if capped else n
        u["pts"] += n
        u["day"]["p"] += n
        self.b.dirty = True
        return n

    def level(self, pts):
        """(index, icon, name) of the highest level reached."""
        i = max(k for k, lv in enumerate(self.cfg["levels"]) if pts >= lv[0])
        return (i, *self.cfg["levels"][i][1:])

    def posts_ok(self, uid):
        return sum(1 for t in self.d["tweets"].values() if t["uid"] == str(uid) and t["status"] == "approved")

    def check_badges(self, uid):
        """Announces new badges and level-ups (badges stay earned even if points are later revoked)."""
        u = self.user(uid)
        n = self.posts_ok(uid)
        new = [k for k, (_, _, _, ok) in BADGES.items() if k not in u.setdefault("badges", []) and ok(u, n)]
        lvl = self.level(u["pts"])[0]
        if new:
            u["badges"] += new
            self.say(uid, "🏅 New badge" + ("s" if len(new) > 1 else "") + "!\n" + "\n".join(f"{BADGES[k][0]} {BADGES[k][1]}: {BADGES[k][2]}" for k in new))
        if lvl > u.get("level", 0):
            u["level"] = lvl
            _, icon, name = self.level(u["pts"])
            self.say(uid, f"🎉 LEVEL UP! You are now {icon} {name}!")
        if new or lvl != u.get("level", 0):
            self.b.dirty = True

    def is_member(self, uid):
        try:
            return tg.call("getChatMember", {"chat_id": self.b.chat, "user_id": int(uid)}).get("status") in OPEN_STATES
        except tg.TelegramError:
            return False

    # --- user commands ---------------------------------------------------------
    def on_message(self, msg, is_admin=False):
        """Handles a private message. Returns True when it was a Points command."""
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return False
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.split("@")[0].lower(), arg.strip()
        uid, name = msg["from"]["id"], msg["from"].get("first_name", "")
        if is_admin and cmd in ("/points_on", "/points_off", "/points_stats"):
            return self.admin(cmd, uid)
        table = {"/start": self.start, "/missions": self.missions, "/points": self.points, "/rank": self.rank, "/checkin": self.checkin,
                 "/x": self.link_x, "/badges": self.badges, "/post": self.post, "/invite": self.invite, "/rules": self.rules}
        if cmd not in table:
            return False
        if not (self.d["open"] or is_admin):  # until the admin opens Peel Points, regular users get no reply
            return True
        u = self.user(uid, name)
        if u["strikes"] >= 2 and cmd != "/rules":
            self.say(uid, "Your account is excluded from Peel Points.")
            return True
        table[cmd](uid, u, arg)
        self.check_badges(uid)
        return True

    def rules(self, uid, u, arg=""):
        c = self.cfg
        self.say(uid, f"🍊 Peel Points rules\n\n• Points have no monetary value and nothing is promised in exchange for them. Any future use will be announced by the admins only, in the pinned messages.\n"
                      f"• Maximum {c['daily_cap']} points per day.\n• One account per person. Fake, copied or duplicated submissions are revoked and repeated cases are excluded.\n"
                      f"• Admins never DM first and never ask for seed phrases or wallets.")

    def start(self, uid, u, arg=""):
        if not u["joined"] and self.is_member(uid):
            u["joined"] = True
            got = self.award(uid, self.cfg["points_join"], "join")
            self.say(uid, f"✅ You are in the Troop: +{got} Peel Points.")
        elif not u["joined"]:
            self.say(uid, f"Join the Troop first: {self.cfg['group_link']} then send /start again.")
        self.say(uid, "🍊 Welcome to Peel Points! Commands:\n/missions · /points · /badges · /rank · /checkin · /x @handle · /post <link> · /invite · /rules")

    def missions(self, uid, u, arg=""):
        c = self.cfg
        need = " or ".join(c["required_any"])
        self.say(uid, f"🎯 Missions\n\n💬 Join the Troop: +{c['points_join']} (once, send /start)\n📅 Daily check-in: +{c['points_checkin']} (/checkin)\n"
                      f"✍️ Post on X mentioning {need}: +{c['points_post']} (once a day). First link your account with /x @yourhandle, then send /post <link of your post>\n"
                      f"🤝 Invite a friend with your own link (/invite): +{c['points_invite']} each, after they stay {c['hold_hours']}h (max {c['max_invites']})\n\n"
                      f"Daily cap: {c['daily_cap']}.")

    def badges(self, uid, u, arg=""):
        n, lv = self.posts_ok(uid), self.cfg["levels"]
        i, icon, name = self.level(u["pts"])
        nxt = f"Next level: {lv[i + 1][1]} {lv[i + 1][2]} at {lv[i + 1][0]} points ({lv[i + 1][0] - u['pts']} to go)" if i + 1 < len(lv) else "Top level reached! 👑"
        got = u.get("badges", [])
        lines = [f"{b[0] if k in got else '🔒'} {b[1]}: {b[2]}" for k, b in BADGES.items()]
        self.say(uid, f"{icon} Level: {name}\n{nxt}\n\n🏅 Badges ({len(got)}/{len(BADGES)})\n" + "\n".join(lines))

    def points(self, uid, u, arg=""):
        self.say(uid, f"{self.level(u['pts'])[1]} {self.level(u['pts'])[2]} · 🍊 {u['pts']} Peel Points · today {u['day']['p'] if u['day']['d'] == self.now().strftime('%Y-%m-%d') else 0}/{self.cfg['daily_cap']}"
                      f"\nX account: {('@' + u['x']) if u['x'] else 'not linked (/x @handle)'}")

    def rank(self, uid, u, arg=""):
        top = sorted(((v["pts"], v["name"] or "Peeler") for v in self.d["users"].values() if v["strikes"] < 2 and v["pts"] > 0), reverse=True)[:10]
        rows = "\n".join(f"{i + 1}. {self.level(p)[1]} {n} · {p}" for i, (p, n) in enumerate(top)) or "Nobody yet. Be the first!"
        self.say(uid, f"🏆 Peel Points top 10\n\n{rows}\n\nYou: {u['pts']}")

    def checkin(self, uid, u, arg=""):
        today = self.now().strftime("%Y-%m-%d")
        if u["checkin"] == today:
            return self.say(uid, "Already done today. Come back tomorrow! 📅")
        yesterday = (self.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        u["streak"] = u.get("streak", 0) + 1 if u["checkin"] == yesterday else 1
        u["best_streak"] = max(u.get("best_streak", 0), u["streak"])
        u["checkin"] = today
        got = self.award(uid, self.cfg["points_checkin"], "checkin")
        self.say(uid, f"📅 Check-in done: +{got}. Streak: {u['streak']} 🔥 Total {u['pts']}." if got else "Daily cap reached. Come back tomorrow!")

    def link_x(self, uid, u, arg=""):
        m = HANDLE.match(arg)
        if not m:
            return self.say(uid, "Send your X handle like this: /x @yourhandle")
        h = m.group(1).lower()
        if any(v["x"] == h for k, v in self.d["users"].items() if k != str(uid)):
            return self.say(uid, "This X account is already linked to another member.")
        if u["x"] and u["x"] != h and u.get("x_changed"):
            return self.say(uid, "You can change your linked account only once. Ask an admin.")
        u["x_changed"] = bool(u["x"] and u["x"] != h) or u.get("x_changed", False)
        u["x"] = h
        self.b.dirty = True
        self.say(uid, f"Linked @{h}. Now post on X and send /post <link>.")

    def invite(self, uid, u, arg=""):
        if not u.get("link"):
            try:
                link = tg.call("createChatInviteLink", {"chat_id": self.b.chat, "name": f"pp{uid}"[:32]})["invite_link"]
            except tg.TelegramError as e:
                return self.say(uid, "Invite links are not available right now. Try again later.") or print(f"Points invite: {e}", flush=True)
            u["link"], self.d["links"][link] = link, str(uid)
            self.b.dirty = True
        self.say(uid, f"🤝 Your personal invite link:\n{u['link']}\n\n+{self.cfg['points_invite']} for each friend who joins with it and stays {self.cfg['hold_hours']}h. Invited so far: {u['invites']}/{self.cfg['max_invites']}.")

    def post(self, uid, u, arg=""):
        c, m = self.cfg, TWEET.match(arg)
        if not u["x"]:
            return self.say(uid, "Link your X account first: /x @yourhandle")
        if not m:
            return self.say(uid, "Send the link of your post: /post https://x.com/yourhandle/status/123…")
        handle, tid = m.group(1).lower(), m.group(2)
        if handle != u["x"]:
            return self.say(uid, f"This post is from @{handle}, not from your linked account @{u['x']}.")
        if tid in self.d["tweets"]:
            return self.say(uid, "This post was already submitted.")
        age = self.now() - tweet_time(tid)
        if age < datetime.timedelta(minutes=-5) or age > datetime.timedelta(hours=c["max_post_age_hours"]):
            return self.say(uid, f"Only posts from the last {c['max_post_age_hours']} hours count.")
        today = self.now().strftime("%Y-%m-%d")
        if any(t["uid"] == str(uid) and t["day"] == today and t["status"] in ("approved", "pending") for t in self.d["tweets"].values()):
            return self.say(uid, "One X post per day. Come back tomorrow!")
        rec = {"uid": str(uid), "day": today, "status": "pending", "pts": 0, "url": f"https://x.com/{handle}/status/{tid}"}
        try:
            info = self.fetch(rec["url"])
        except LookupError as e:
            return self.say(uid, f"I could not verify it: {e}.")
        except Exception as e:  # X unreachable: an admin decides
            print(f"Points: X check failed: {e}", flush=True)
            self.d["tweets"][tid] = rec
            self.b.dirty = True
            self.say(uid, "I could not check X right now: your post is waiting for an admin.")
            return self.review(tid, rec, "X check unavailable")
        if info["author"] != handle:
            return self.say(uid, "The post author does not match your linked account.")
        low = info["text"].lower()
        if not any(r.lower() in low for r in c["required_any"]):
            return self.say(uid, f"The post must mention {' or '.join(c['required_any'])}.")
        got = self.award(uid, c["points_post"], "post")
        rec.update(status="approved", pts=got)
        self.d["tweets"][tid] = rec
        self.say(uid, f"✅ Post verified: +{got}. Total {u['pts']}.")
        if int(hashlib.sha256(tid.encode()).hexdigest(), 16) % c["review_every"] == 0:  # random sample for the admin
            self.review(tid, rec, "random check")

    def review(self, tid, rec, why):
        if not self.b.admin:
            return
        ok = rec["status"] == "pending"
        btns = [[{"text": "✅ Approve", "callback_data": f"ok:{tid}"}, {"text": "❌ Reject", "callback_data": f"no:{tid}"}]] if ok \
            else [[{"text": "↩️ Revoke points", "callback_data": f"no:{tid}"}]]
        self.say(self.b.admin, f"🔎 Peel Points review ({why})\n{rec['url']}\nUser: {self.d['users'][rec['uid']]['name']} · {rec['pts']} pts", {"inline_keyboard": btns})

    # --- admin ---------------------------------------------------------------
    def admin(self, cmd, uid):
        if cmd == "/points_stats":
            us = self.d["users"].values()
            self.say(uid, f"Peel Points: {'OPEN' if self.d['open'] else 'closed'} | users {len(self.d['users'])} | points {sum(u['pts'] for u in us)} | "
                          f"waiting posts {sum(t['status'] == 'pending' for t in self.d['tweets'].values())}")
        elif cmd == "/points_off":
            self.d["open"] = False
            self.say(uid, "Peel Points closed: regular users get no replies.")
        else:
            self.d["open"] = True
            self.d["promo_slot"], self.d["promo_at"] = self.hour_key(), self.now().isoformat()  # first reminder after the interval
            if self.d["announced"]:
                self.say(uid, "Peel Points open (announcement already sent before).")
            else:
                self.d["announced"] = True
                self.b.persist("Peel Points opened")  # saved first: never two announcements
                user = tg.call("getMe", {}).get("username", "")
                tg.call("sendMessage", {"chat_id": self.b.chat, "text": self.cfg["announce"].format(bot=user),
                                        "link_preview_options": {"is_disabled": True}})
                self.say(uid, "Peel Points open and announced in the group.")
        self.b.dirty = True
        return True

    def on_callback(self, cb):
        """Admin buttons: ok:<id> approve, no:<id> reject or revoke."""
        if str(cb["from"]["id"]) != self.b.admin:
            return
        act, _, tid = (cb.get("data") or "").partition(":")
        rec = self.d["tweets"].get(tid)
        if not rec or act not in ("ok", "no"):
            return
        u = self.user(rec["uid"])
        if act == "ok" and rec["status"] == "pending":
            rec.update(status="approved", pts=self.award(rec["uid"], self.cfg["points_post"], "post"))
            self.say(rec["uid"], f"✅ Your X post was approved: +{rec['pts']}.")
        elif act == "no" and rec["status"] in ("pending", "approved"):
            u["pts"] = max(0, u["pts"] - rec["pts"])
            u["strikes"] += rec["status"] == "approved"
            rec.update(status="revoked" if rec["status"] == "approved" else "rejected", pts=0)
            self.say(rec["uid"], "❌ Your X post was not accepted" + (" and its points were revoked." if rec["status"] == "revoked" else "."))
        self.b.dirty = True
        self.check_badges(rec["uid"])
        try:
            tg.call("answerCallbackQuery", {"callback_query_id": cb["id"], "text": f"Done: {rec['status']}"})
        except tg.TelegramError:
            pass

    # --- referrals -----------------------------------------------------------
    def on_join(self, cm):
        """chat_member update: remembers who joined with a personal link."""
        link = (cm.get("invite_link") or {}).get("invite_link")
        inviter = self.d["links"].get(link)
        user = cm["new_chat_member"]["user"]
        invitee = str(user.get("id", ""))
        if not inviter or not invitee or inviter == invitee or invitee in self.d["referred"] or user.get("is_bot"):
            return
        self.d["referred"][invitee] = inviter
        self.d["refs"].append({"inviter": inviter, "invitee": invitee, "ts": self.now().isoformat()})
        self.b.dirty = True

    def process_refs(self):
        """After the hold time, pays the inviter if the friend is still in the group."""
        keep, hold = [], datetime.timedelta(hours=self.cfg["hold_hours"])
        for r in self.d["refs"]:
            if self.now() - datetime.datetime.fromisoformat(r["ts"]) < hold:
                keep.append(r)
                continue
            u = self.user(r["inviter"])
            if self.is_member(r["invitee"]) and u["invites"] < self.cfg["max_invites"]:
                u["invites"] += 1
                got = self.award(r["inviter"], self.cfg["points_invite"], "invite", capped=False)
                self.say(r["inviter"], f"🤝 A friend you invited stayed in the Troop: +{got}. Total {u['pts']}.")
                self.check_badges(r["inviter"])
            self.b.dirty = True
        self.d["refs"] = keep

    # --- hourly reminder -----------------------------------------------------
    def hour_key(self):
        import zoneinfo
        return self.now().astimezone(zoneinfo.ZoneInfo(self.b.cfg["timezone"])).strftime("%Y-%m-%d %H")

    def promo(self):
        """One hype message every `every_hours` hours in the group (the previous one is deleted, so there is never a pile of them)."""
        c = self.cfg.get("promo", {})
        key = self.hour_key()
        if not (self.d["open"] and c.get("enabled") and c.get("texts")) or self.d.get("promo_slot") == key:
            return
        last = self.d.get("promo_at")
        if last and (self.now() - datetime.datetime.fromisoformat(last)).total_seconds() < c.get("every_hours", 1) * 3600 - 300:
            return
        self.d["promo_slot"], self.d["promo_at"] = key, self.now().isoformat()
        n = self.d["promo_n"] = self.d.get("promo_n", -1) + 1  # rotates the variants
        self.b.persist("Peel Points reminder")  # saved first: never two reminders in the same hour
        bot_name = tg.call("getMe", {}).get("username", "")
        text = c["texts"][n % len(c["texts"])].format(bot=bot_name, **{k: v for k, v in self.cfg.items() if k.startswith("points_")})
        old = self.d.get("promo_id")
        msg = tg.call("sendMessage", {"chat_id": self.b.chat, "text": text, "link_preview_options": {"is_disabled": True}})
        self.d["promo_id"] = msg["message_id"]
        if old and c.get("delete_previous", True):
            try:
                tg.call("deleteMessage", {"chat_id": self.b.chat, "message_id": old})
            except tg.TelegramError:
                pass
        self.b.dirty = True

    def tick(self):
        if self.d["open"] and self.d["refs"]:
            self.process_refs()
        self.promo()
