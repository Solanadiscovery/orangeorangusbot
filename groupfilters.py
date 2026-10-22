"""Rose-style group tools: keyword filters and group rules, handled by the bot itself.

Admins (the bot owner or any group admin) manage them from the group:
/filter word text · /filters · /stop word · /setrules text · /rules (everyone).
Filters live in state.json, so they survive restarts. Needs the bot to see group messages
(make it a group admin or turn off Privacy mode in BotFather).
"""
import re

import tg

MAX_FILTERS = 100
MAX_TEXT = 3500
COOLDOWN = 600       # seconds before the same word is answered again
RULES_COOLDOWN = 60
ADMIN_CACHE = 300


class GroupFilters:
    def __init__(self, bot):
        self.bot = bot

    @property
    def filters(self):
        return self.bot.state.setdefault("filters", {})

    def is_main(self, chat):
        main = self.bot.chat.lower()
        return bool(main) and main in (str(chat.get("id", "")).lower(), "@" + (chat.get("username") or "").lower())

    def is_admin(self, user_id):
        if self.bot.admin and str(user_id) == self.bot.admin:
            return True
        cache = self.bot.mem.setdefault("group_admins", {})
        ts = self.bot.clock().timestamp()
        if user_id in cache and ts - cache[user_id][1] < ADMIN_CACHE:
            return cache[user_id][0]
        try:
            ok = tg.call("getChatMember", {"chat_id": self.bot.chat, "user_id": user_id})["status"] in ("creator", "administrator")
        except tg.TelegramError:
            ok = False
        cache[user_id] = (ok, ts)
        return ok

    def say(self, msg, text):
        tg.call("sendMessage", {"chat_id": self.bot.chat, "text": text, "reply_to_message_id": msg["message_id"],
                                "allow_sending_without_reply": True, "link_preview_options": {"is_disabled": True}})

    def cooled(self, key, seconds):
        ts, last = self.bot.clock().timestamp(), self.bot.mem.setdefault("group_cooldown", {})
        if ts - last.get(key, 0) < seconds:
            return False
        last[key] = ts
        return True

    def on_message(self, msg):
        text = msg.get("text") or ""
        if not text:
            return
        if not text.startswith("/"):
            return self.match(msg, text)
        head, _, arg = text.partition(" ")
        cmd, arg = head.split("@")[0].lower(), arg.strip()
        if cmd == "/rules":
            rules = self.bot.state.get("group_rules")
            if rules and self.cooled("rules", RULES_COOLDOWN):
                self.say(msg, rules)
            return
        if cmd not in ("/filter", "/filters", "/stop", "/setrules") or not self.is_admin(msg.get("from", {}).get("id")):
            return
        if cmd == "/filters":
            return self.say(msg, "Active filters: " + ", ".join(self.filters) if self.filters else "No filters yet.")
        if cmd == "/stop":
            if self.filters.pop(arg.strip('"').lower(), None) is None:
                return self.say(msg, "Filter not found. See /filters.")
            self.bot.dirty = True
            return self.say(msg, "🗑 Filter removed.")
        if not arg:
            replied = (msg.get("reply_to_message") or {}).get("text")
            if cmd == "/setrules" and replied:
                arg = replied
            else:
                return self.say(msg, "Usage: /filter word text · /filter \"two words\" text · /setrules text · /stop word")
        if cmd == "/setrules":
            self.bot.state["group_rules"], self.bot.dirty = arg[:MAX_TEXT], True
            return self.say(msg, "✅ Rules saved. Members get them with /rules.")
        word, reply = self.split(arg, (msg.get("reply_to_message") or {}).get("text"))
        if not word or not reply:
            return self.say(msg, "Usage: /filter word text (or reply to a message with /filter word)")
        if word not in self.filters and len(self.filters) >= MAX_FILTERS:
            return self.say(msg, f"Limit of {MAX_FILTERS} filters reached.")
        self.filters[word], self.bot.dirty = reply[:MAX_TEXT], True
        self.say(msg, f"✅ Filter saved: {word}")

    @staticmethod
    def split(arg, replied):
        if arg.startswith('"') and '"' in arg[1:]:
            word, _, rest = arg[1:].partition('"')
        else:
            word, _, rest = arg.partition(" ")
        return word.strip().lower(), (rest.strip() or replied or "")

    def match(self, msg, text):
        low = text.lower()
        for word, reply in self.filters.items():
            if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", low) and self.cooled("filter:" + word, COOLDOWN):
                return self.say(msg, reply)
