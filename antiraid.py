"""Rose-style raid defence for the group, run by the bot itself.

Admins (the bot owner or any group admin), in the group:
/antiraid [time|off]   ban every new member for a while (no argument toggles it)
/raidtime time         default length of /antiraid (e.g. 6h)
/raidactiontime time   how long each joiner stays banned (e.g. 1h; a temporary ban, they can come back later)
/autoantiraid n|off    switch /antiraid on by itself when n or more people join within a minute
/lock all|links, /unlock all|links, /locks   block the whole chat, or links from non-admins
The bot must be a group admin with "Ban users" and "Delete messages" (and "Change group info" for /lock all).
"""
import re
import time

import tg

DEFAULTS = {"time": 6 * 3600, "action": 3600, "auto": 0}
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
LINK = re.compile(r"(https?://|www\.|t\.me/|\b[\w-]+\.(com|io|app|me|xyz|org|net|gg|ly)\b)", re.I)
COMMANDS = ("/antiraid", "/raidtime", "/raidactiontime", "/autoantiraid", "/lock", "/unlock", "/locks")


def parse_time(text):
    m = re.fullmatch(r"(\d+)([smhd])", text.strip().lower())
    return int(m.group(1)) * UNITS[m.group(2)] if m else None


def show(seconds):
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size and seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


class AntiRaid:
    def __init__(self, bot):
        self.bot = bot

    @property
    def raid(self):
        return self.bot.state.setdefault("raid", dict(DEFAULTS))

    def now(self):
        return self.bot.clock().timestamp()

    def active(self):
        return self.raid.get("until", 0) > self.now()

    def say(self, chat_id, text, reply_to=None):
        fields = {"chat_id": chat_id, "text": text}
        if reply_to:
            fields.update(reply_to_message_id=reply_to, allow_sending_without_reply=True)
        tg.call("sendMessage", fields)

    # --- new members ----------------------------------------------------------
    def on_join(self, user):
        """Called for every new member. Returns True when the person was banned (no welcome for them)."""
        uid = user.get("id")
        if not uid or user.get("is_bot"):
            return False
        recent = self.bot.mem.setdefault("joins", {})
        ts = self.now()
        recent[uid] = ts  # a join reported twice (member update + service message) counts once
        for k in [k for k, v in recent.items() if ts - v > 60]:
            del recent[k]
        auto = self.raid.get("auto", 0)
        if auto and not self.active() and len(recent) >= auto:
            self.start(self.raid.get("time", DEFAULTS["time"]), "Automatic anti-raid: too many people joined within a minute.")
        if not self.active():
            return False
        try:
            tg.call("banChatMember", {"chat_id": self.bot.chat, "user_id": uid,
                                      "until_date": int(ts) + self.raid.get("action", DEFAULTS["action"])})
        except tg.TelegramError as e:
            self.bot.alert("raid_ban", f"Anti-raid could not ban a new member (is the bot an admin that can ban?): {e}")
            return False
        return True

    def start(self, seconds, why=""):
        self.raid["until"], self.bot.dirty = int(self.now()) + seconds, True
        self.bot.alert("raid_on", f"🛡️ Anti-raid ON for {show(seconds)}. {why}".strip(), every=600)
        try:
            self.say(self.bot.chat, f"🛡️ Anti-raid is ON for {show(seconds)}: new members are removed for now. Admins can end it with /antiraid off.")
        except tg.TelegramError:
            pass

    # --- links lock -----------------------------------------------------------
    def check_links(self, msg, is_admin):
        """Delete a link posted by a non-admin while /lock links is on. Returns True when deleted."""
        text = msg.get("text") or msg.get("caption") or ""
        if not self.bot.state.get("lock_links") or not LINK.search(text):
            return False
        if is_admin(msg.get("from", {}).get("id")):
            return False
        try:
            tg.call("deleteMessage", {"chat_id": self.bot.chat, "message_id": msg["message_id"]})
        except tg.TelegramError:
            return False
        return True

    # --- admin commands -------------------------------------------------------
    def command(self, msg, cmd, arg):
        reply = lambda text: self.say(self.bot.chat, text, msg["message_id"])
        raid, state = self.raid, self.bot.state
        if cmd == "/antiraid":
            if arg.lower() in ("off", "no", "stop") or (not arg and self.active()):
                raid["until"], self.bot.dirty = 0, True
                return reply("✅ Anti-raid is OFF.")
            seconds = parse_time(arg) if arg else raid.get("time", DEFAULTS["time"])
            if not seconds:
                return reply("Usage: /antiraid · /antiraid 2h · /antiraid off")
            return self.start(seconds)
        if cmd in ("/raidtime", "/raidactiontime"):
            key = "time" if cmd == "/raidtime" else "action"
            seconds = parse_time(arg) if arg else None
            if not seconds:
                return reply(f"Currently {show(raid.get(key, DEFAULTS[key]))}. Usage: {cmd} 6h")
            raid[key], self.bot.dirty = seconds, True
            return reply(f"✅ Saved: {show(seconds)}.")
        if cmd == "/autoantiraid":
            if arg.lower() in ("off", "no", "0"):
                raid["auto"], self.bot.dirty = 0, True
                return reply("✅ Automatic anti-raid is OFF.")
            if not arg.isdigit() or not 2 <= int(arg) <= 500:
                return reply(f"Currently {raid.get('auto') or 'off'}. Usage: /autoantiraid 10 (joins within a minute) · /autoantiraid off")
            raid["auto"], self.bot.dirty = int(arg), True
            return reply(f"✅ Anti-raid will switch on by itself when {arg} people join within a minute.")
        if cmd == "/locks":
            return reply(f"🛡️ Anti-raid: {'ON, ends in ' + show(int(raid['until'] - self.now())) if self.active() else 'OFF'}"
                         f" · auto: {raid.get('auto') or 'off'} · raid time {show(raid.get('time', DEFAULTS['time']))}"
                         f" · ban {show(raid.get('action', DEFAULTS['action']))}\n"
                         f"🔒 Chat locked: {'yes' if state.get('locked_permissions') else 'no'} · links locked: {'yes' if state.get('lock_links') else 'no'}")
        what = arg.lower()
        lock = cmd == "/lock"
        if what == "links":
            state["lock_links"], self.bot.dirty = lock, True
            return reply("🔒 Links from non-admins will be deleted." if lock else "🔓 Links are allowed again.")
        if what != "all":
            return reply(f"Usage: {cmd} all · {cmd} links")
        try:
            if lock:
                if not state.get("locked_permissions"):
                    state["locked_permissions"] = tg.call("getChat", {"chat_id": self.bot.chat}).get("permissions") or {"can_send_messages": True}
                tg.call("setChatPermissions", {"chat_id": self.bot.chat, "permissions": {"can_send_messages": False}})
                reply("🔒 Chat locked: only admins can write. /unlock all to reopen.")
            else:
                saved = state.pop("locked_permissions", None) or {"can_send_messages": True}
                tg.call("setChatPermissions", {"chat_id": self.bot.chat, "permissions": saved})
                reply("🔓 Chat reopened.")
            self.bot.dirty = True
        except tg.TelegramError as e:
            reply(f"I could not change the chat permissions: {e.description}. Is the bot an admin that can change group info?")
