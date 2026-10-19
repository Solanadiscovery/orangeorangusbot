"""OrangeOrangus bot: processo sempre attivo su GitHub Actions.

Ogni minuto: comandi admin, countdown fissato (modificato sul posto), traguardi membri,
pubblicazioni programmate su Telegram e X con controllo anti-ripetizione.
Stato e storico sono salvati nel repository (state.json, history.json), quindi sopravvivono ai riavvii.

Variabili: BOT_TOKEN, CHAT_ID, ADMIN_USER_ID (facoltativo), X_* (facoltative), GITHUB_TOKEN (riavvio).
Uso: python bot.py            -> processo continuo
     python bot.py --preview  -> mostra i prossimi contenuti senza pubblicare
"""
import datetime, json, os, subprocess, sys, time, urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import content, countdown, tg, xapi

ROOT = Path(__file__).parent
RUN_SECONDS = 5 * 3600 + 40 * 60
SLOT_WINDOW = datetime.timedelta(minutes=30)
PIN_CHECK_EVERY = 1800
HELP = """🦧 Comandi admin OrangeOrangus

/status → stato del bot: pausa, anteprima, countdown, contenuti nuovi rimasti, ultimi post
/pause → ferma i post su Telegram e X (il countdown continua ad aggiornarsi)
/resume → riattiva i post
/preview_on → modalità prova: i post arrivano solo a te in privato, non sul canale né su X
/preview_off → torna a pubblicare sul canale e su X
/next → mostra i prossimi contenuti che verranno pubblicati
/help → questo elenco

Solo tu puoi usare questi comandi: gli altri utenti vengono ignorati."""


def load(name, default=None):
    p = ROOT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(name, data):
    (ROOT / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


class Bot:
    def __init__(self, now=None):
        self.cfg = load("config.json")
        self.state = load("state.json", {})
        self.history = load("history.json", [])
        self.pools = {p: load(f"content/{p}.json") for p in ("telegram", "x")}
        self.chat = os.environ.get("CHAT_ID", "").strip()
        self.admin = os.environ.get("ADMIN_USER_ID", "").strip()
        self.dirty = False
        self.now = now
        self.mem = {}  # dati solo in memoria (testo countdown, ultimo controllo pin): niente commit ogni minuto

    # --- utilità -------------------------------------------------------------
    def clock(self):
        return self.now or datetime.datetime.now(datetime.timezone.utc)

    def persist(self, msg="Bot state"):
        save("state.json", self.state)
        save("history.json", self.history)
        if os.environ.get("GITHUB_ACTIONS"):
            for cmd in (["config", "user.name", "orangeorangus-bot"], ["config", "user.email", "bot@users.noreply.github.com"],
                        ["add", "state.json", "history.json"], ["commit", "-qm", msg],
                        ["pull", "-q", "--rebase", "origin", "main"], ["push", "-q", "origin", "HEAD:main"]):
                subprocess.run(["git", *cmd], check=False)
        self.dirty = False

    def alert(self, key, text, every=3600):
        """Avviso all'admin (al massimo una volta ogni `every` secondi per tipo)."""
        alerts = self.state.setdefault("alerts", {})
        ts = self.clock().timestamp()
        if ts - alerts.get(key, 0) < every:
            return
        alerts[key], self.dirty = ts, True
        print(f"ALERT {key}: {text}", flush=True)
        if self.admin:
            try:
                tg.call("sendMessage", {"chat_id": self.admin, "text": f"⚠️ OrangeOrangus bot\n{text}"})
            except Exception as e:
                print(f"Avviso admin non inviato: {e}", flush=True)

    def flag(self, name):  # i comandi admin hanno la precedenza sul file di configurazione
        return self.state.get(name, self.cfg.get(name, False))

    # --- comandi admin (chat privata con il bot) ------------------------------
    def commands(self):
        updates = tg.call("getUpdates", {"offset": self.state.get("update_offset", 0), "timeout": 0,
                                         "allowed_updates": ["message", "chat_member"]})
        joined = []
        for u in updates:
            self.state["update_offset"], self.dirty = u["update_id"] + 1, True
            cm = u.get("chat_member")
            if cm and cm["new_chat_member"]["status"] == "member" and cm["old_chat_member"]["status"] in ("left", "kicked"):
                joined.append(cm["new_chat_member"]["user"].get("first_name") or "Peeler")
                continue
            msg = u.get("message") or {}
            if msg.get("new_chat_members"):  # gruppi: ingresso segnalato anche come messaggio di servizio
                joined += [m.get("first_name") or "Peeler" for m in msg["new_chat_members"] if not m.get("is_bot")]
                continue
            if not self.admin:
                continue
            if msg.get("chat", {}).get("type") != "private":
                continue
            sender = str(msg.get("from", {}).get("id"))
            if sender != self.admin:  # gli altri utenti vengono ignorati in silenzio
                continue
            cmd = (msg.get("text") or "").split()[0].lower() if msg.get("text") else ""
            reply = self.handle(cmd)
            if reply:
                tg.call("sendMessage", {"chat_id": self.admin, "text": reply})
        if joined:
            self.welcome(list(dict.fromkeys(joined)))

    def welcome(self, names):
        """Un solo messaggio di benvenuto per gli ingressi del minuto; il precedente viene cancellato (niente spam)."""
        c = self.cfg["welcome"]
        if not c.get("enabled"):
            return
        count = self.member_count()
        goal = self.cfg["countdown"]["goal"]
        who = ", ".join(names[:5]) + (f" +{len(names) - 5}" if len(names) > 5 else "")
        text = (c["text"] if count < goal else c["text_after_goal"]).format(names=who, count=count, left=max(goal - count, 0), goal=goal)
        old = self.state.get("welcome_id")
        msg = tg.call("sendMessage", {"chat_id": self.chat, "text": text, "link_preview_options": {"is_disabled": True}})
        self.state["welcome_id"], self.dirty = msg["message_id"], True
        if old:
            try:
                tg.call("deleteMessage", {"chat_id": self.chat, "message_id": old})
            except tg.TelegramError:
                pass

    def handle(self, cmd):
        if cmd in ("/pause", "/resume"):
            self.state["paused"] = cmd == "/pause"
            return "⏸ Pubblicazioni in pausa (il countdown continua)." if self.state["paused"] else "▶️ Pubblicazioni riattivate."
        if cmd in ("/preview_on", "/preview_off"):
            self.state["preview"] = cmd == "/preview_on"
            return "👀 Anteprima ON: i post arrivano solo a te." if self.state["preview"] else "✅ Anteprima OFF: si pubblica sul canale e su X."
        if cmd == "/next":
            return self.preview_text()
        if cmd == "/status":
            left = {p: content.remaining(self.pools[p], self.history, self.cfg["similarity_threshold"]) for p in self.pools}
            return (f"Pausa: {self.flag('paused')} | Anteprima: {self.flag('preview')}\n"
                    f"Countdown: modalità {self.cfg['countdown']['mode']}, messaggio {self.state.get('counter_id')}\n"
                    f"Contenuti nuovi rimasti: Telegram {left['telegram']}, X {left['x']}\n"
                    f"Ultimi slot: {self.state.get('slots', {})}")
        return HELP

    def preview_text(self):
        out = []
        for p in ("telegram", "x"):
            item = content.pick(self.pools[p], self.history, self.cfg[p]["rotation"],
                                self.state.get("last_type", {}).get(p), self.cfg["similarity_threshold"])
            out.append(f"[{p.upper()}] " + (f"{item['type']}: {content.text_of(item)}" if item else "nessun contenuto nuovo"))
        return "\n\n".join(out)

    # --- countdown -------------------------------------------------------------
    def member_count(self):
        return tg.call("getChatMemberCount", {"chat_id": self.chat})

    def update_countdown(self, count):
        text, _done = countdown.render(self.cfg, self.clock(), count)
        cid = self.state.get("counter_id")
        if not cid:
            if self.state.get("counter_created"):  # già creato in passato: mai un secondo messaggio
                return self.alert("countdown_missing", "Il messaggio del countdown non è più registrato. Non ne creo un altro: controlla.")
            msg = tg.call("sendMessage", {"chat_id": self.chat, "text": text, "link_preview_options": {"is_disabled": True}})
            self.state.update(counter_id=msg["message_id"], counter_created=True)
            self.mem["counter_text"] = text
            tg.call("pinChatMessage", {"chat_id": self.chat, "message_id": msg["message_id"], "disable_notification": True})
            self.dirty = True
            return
        if text == self.mem.get("counter_text"):
            return
        try:
            tg.call("editMessageText", {"chat_id": self.chat, "message_id": cid, "text": text,
                                         "link_preview_options": {"is_disabled": True}})
        except tg.TelegramError as e:
            if "not modified" in e.description:
                pass
            elif "not found" in e.description or "MESSAGE_ID_INVALID" in e.description or "can't be edited" in e.description:
                return self.alert("countdown_missing", f"Non trovo il messaggio del countdown ({cid}): {e.description}. "
                                  "Non ne creo uno nuovo per evitare duplicati.")
            else:
                raise
        self.mem["counter_text"] = text

    def ensure_pinned(self):
        ts = self.clock().timestamp()
        if ts - self.mem.get("pin_checked", 0) < PIN_CHECK_EVERY or not self.state.get("counter_id"):
            return
        self.mem["pin_checked"] = ts
        pinned = tg.call("getChat", {"chat_id": self.chat}).get("pinned_message", {}).get("message_id")
        if pinned != self.state["counter_id"]:
            try:
                tg.call("pinChatMessage", {"chat_id": self.chat, "message_id": self.state["counter_id"],
                                           "disable_notification": True})
            except tg.TelegramError as e:
                self.alert("pin_failed", f"Non riesco a fissare il countdown: {e.description}")

    def og_existing(self, count):
        """Una sola volta: nomina OG Peeler chi era già nel canale (la Bot API non elenca i membri, quindi un annuncio)."""
        og, goal = self.cfg.get("og", {}), self.cfg["countdown"]["goal"]
        if not og.get("enabled") or self.state.get("og_existing_done") or count >= goal:
            return
        self.state["og_existing_done"] = True
        self.persist("OG Peelers announced")  # salvato prima: mai due annunci
        tg.call("sendMessage", {"chat_id": self.chat, "text": og["text_existing"].format(count=count, goal=goal, left=goal - count),
                                "link_preview_options": {"is_disabled": True}})

    def milestones(self, count):
        c = self.cfg["countdown"]
        if c["mode"] != "members":
            return
        new = [m for m in c["milestones"] if count >= m and m not in self.state.setdefault("announced", [])]
        if not new:
            return
        m = max(new)
        text = c["text_goal_post"].format(goal=c["goal"]) if m == c["goal"] else c["text_milestone_post"].format(m=m, goal=c["goal"])
        self.state["announced"] += new
        self.persist(f"Milestone {m}")  # salvato prima di pubblicare: mai due annunci uguali
        self.send_telegram({"type": "text", "text": text})

    # --- pubblicazioni ---------------------------------------------------------
    def send_telegram(self, item, target=None):
        chat = target or self.chat
        if item["type"] in ("quiz", "poll"):
            fields = {"chat_id": chat, "question": item["question"], "options": item["options"]}
            if item["type"] == "quiz":
                fields.update(type="quiz", correct_option_id=item["correct"])
                if item.get("explanation"):
                    fields["explanation"] = item["explanation"][:200]
            return tg.call("sendPoll", fields)
        return tg.call("sendMessage", {"chat_id": chat, "text": f"{item['text']}\n\n{self.cfg['telegram']['footer']}",
                                       "disable_web_page_preview": True})

    def due_slot(self, platform):
        tz = ZoneInfo(self.cfg["timezone"])
        local = self.clock().astimezone(tz)
        for hhmm in self.cfg[platform]["times"]:
            h, m = map(int, hhmm.split(":"))
            slot = local.replace(hour=h, minute=m, second=0, microsecond=0)
            if slot <= local < slot + SLOT_WINDOW:
                return slot.strftime("%Y-%m-%d %H:%M")
        return None

    def publish(self, platform):
        key = self.due_slot(platform)
        slots = self.state.setdefault("slots", {})
        if not key or slots.get(platform) == key or self.flag("paused"):
            return
        if platform == "x" and not xapi.enabled():
            return
        threshold = self.cfg["similarity_threshold"]
        item = content.pick(self.pools[platform], self.history, self.cfg[platform]["rotation"],
                            self.state.get("last_type", {}).get(platform), threshold)
        slots[platform] = key
        if item is None:
            self.persist(f"{platform} {key}: nessun contenuto")
            return self.alert(f"empty_{platform}", f"Contenuti {platform} finiti: aggiungine di nuovi.", every=21600)
        self.state.setdefault("last_type", {})[platform] = item["type"]
        content.record(self.history, item, platform, self.clock().isoformat())
        self.persist(f"{platform} {key}: {item['id']}")  # registrato PRIMA dell'invio: mai doppioni dopo un riavvio
        try:
            if self.flag("preview"):
                if self.admin:
                    tg.call("sendMessage", {"chat_id": self.admin,
                                            "text": f"[ANTEPRIMA {platform.upper()}] {item['type']}\n{content.text_of(item)}"})
            elif platform == "telegram":
                self.send_telegram(item)
            else:
                xapi.post(item, self.cfg["x"])
            print(f"Pubblicato {platform} {item['id']}", flush=True)
        except Exception as e:
            self.alert(f"publish_{platform}", f"Pubblicazione {platform} fallita ({item['id']}): {e}")
        left = content.remaining(self.pools[platform], self.history, threshold)
        if left <= 8:
            self.alert(f"low_{platform}", f"Restano solo {left} contenuti nuovi per {platform}.", every=86400)

    # --- ciclo -------------------------------------------------------------------
    def tick(self):
        for step in (self.commands, lambda: self.publish("telegram"), lambda: self.publish("x")):
            try:
                step()
            except Exception as e:
                print(f"Errore: {e}", flush=True)
        try:
            count = self.member_count()
            self.update_countdown(count)
            self.og_existing(count)
            self.ensure_pinned()
            self.milestones(count)
        except Exception as e:
            print(f"Errore countdown: {e}", flush=True)
        if self.dirty:
            self.persist()


def restart_self():
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if repo and token:
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/workflows/live-counter.yml/dispatches",
            json.dumps({"ref": "main"}).encode(),
            {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})).close()


def main():
    if "--preview" in sys.argv:
        print(Bot().preview_text())
        return
    end, bot = time.time() + RUN_SECONDS, Bot()  # config e contenuti nuovi valgono dal riavvio successivo
    while time.time() < end:
        bot.tick()
        time.sleep(60)
    restart_self()


if __name__ == "__main__":
    main()
