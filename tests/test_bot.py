"""Test offline: le chiamate a Telegram sono simulate. Esegui con: python -m unittest discover tests"""
import datetime, json, os, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import bot, content, countdown, tg

UTC = datetime.timezone.utc


class FakeTelegram:
    def __init__(self, members=7, edit_error=None):
        self.calls, self.members, self.edit_error, self.next_id = [], members, edit_error, 100

    def __call__(self, method, fields, **_):
        self.calls.append((method, fields))
        if method == "getChatMemberCount":
            return self.members
        if method == "getUpdates":
            return self.updates.pop(0) if getattr(self, "updates", None) else []
        if method == "getChatMember":
            return {"status": "member"}
        if method == "getChat":
            return {"pinned_message": {"message_id": 30}}
        if method == "editMessageText" and self.edit_error:
            raise tg.TelegramError(400, self.edit_error)
        if method in ("sendMessage", "sendPoll", "sendPhoto"):
            self.next_id += 1
            return {"message_id": self.next_id, "photo": [{"file_id": "small"}, {"file_id": "PHOTO_ID"}]}
        return True

    def methods(self):
        return [m for m, _ in self.calls]


class BotTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        cfg = json.loads((REPO / "config.json").read_text())
        (self.dir / "config.json").write_text(json.dumps(cfg))
        (self.dir / "history.json").write_text("[]")  # never the live history: its real dates would make tests time-dependent
        shutil.copytree(REPO / "content", self.dir / "content")
        (self.dir / "state.json").write_text(json.dumps({"counter_id": 30, "counter_created": True, "announced": [],
                                                         "og_existing_done": True}))
        self.patches = [mock.patch.object(bot, "ROOT", self.dir),
                        mock.patch.dict(os.environ, {"CHAT_ID": "@test", "BOT_TOKEN": "x", "ADMIN_USER_ID": "1"}, clear=False)]
        for p in self.patches:
            p.start()
        os.environ.pop("GITHUB_ACTIONS", None)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.dir)

    def make(self, when, fake):
        with mock.patch.object(tg, "call", fake):
            b = bot.Bot(now=when)
            b.tick()
        return b

    # --- countdown -----------------------------------------------------------
    def test_countdown_edits_same_message_never_sends_new(self):
        fake = FakeTelegram(members=7)
        b = self.make(datetime.datetime(2026, 10, 19, 6, 0, tzinfo=UTC), fake)
        fake.members = 6  # qualcuno esce: il numero scende
        with mock.patch.object(tg, "call", fake):
            b.tick()
        edits = [f for m, f in fake.calls if m == "editMessageText"]
        self.assertEqual(len(edits), 2)
        self.assertTrue(all(f["message_id"] == 30 for f in edits))
        self.assertIn("494 Peelers left", edits[-1]["text"])
        self.assertNotIn("sendMessage", fake.methods())

    def test_members_json_written_only_when_count_changes(self):
        fake = FakeTelegram(members=7)
        b = self.make(datetime.datetime(2026, 10, 19, 6, 0, tzinfo=UTC), fake)
        self.assertEqual(json.loads((self.dir / "members.json").read_text())["telegram"], 7)
        (self.dir / "members.json").unlink()
        with mock.patch.object(tg, "call", fake):
            b.tick()
        self.assertFalse((self.dir / "members.json").exists())
        fake.members = 8
        with mock.patch.object(tg, "call", fake):
            b.tick()
        self.assertEqual(json.loads((self.dir / "members.json").read_text()), {"telegram": 8, "goal": 500, "updated": "2026-10-19T06:00:00Z"})

    def test_unchanged_count_does_not_edit_again(self):
        fake = FakeTelegram(members=7)
        b = self.make(datetime.datetime(2026, 10, 19, 6, 0, tzinfo=UTC), fake)
        with mock.patch.object(tg, "call", fake):
            b.tick()
        self.assertEqual(fake.methods().count("editMessageText"), 1)

    def test_missing_countdown_alerts_admin_and_does_not_recreate(self):
        fake = FakeTelegram(edit_error="Bad Request: message to edit not found")
        self.make(datetime.datetime(2026, 10, 19, 6, 0, tzinfo=UTC), fake)
        sends = [f for m, f in fake.calls if m == "sendMessage"]
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["chat_id"], "1")  # solo l'avviso all'admin
        self.assertNotIn("pinChatMessage", fake.methods())

    def test_time_mode_uses_absolute_target(self):
        cfg = {"countdown": {"mode": "time", "target": "2026-11-01T20:00:00+01:00",
                             "text_time": "{d}d {h}h {m}m", "text_done_time": "done"}}
        now = datetime.datetime(2026, 10, 19, 16, 30, tzinfo=UTC)
        self.assertEqual(countdown.render(cfg, now, 0), ("13d 02h 30m", False))
        self.assertEqual(countdown.render(cfg, datetime.datetime(2026, 11, 2, tzinfo=UTC), 0), ("done", True))

    # --- anti-ripetizione ----------------------------------------------------
    def test_exact_and_similar_duplicates_rejected(self):
        hist = [{"id": "a", "concept": "c1", "text": "gm to every Peeler waking up somewhere in the world!"}]
        self.assertIn("identico", content.is_duplicate({"id": "b", "concept": "c2", "text": "GM to every peeler waking up somewhere in the world"}, hist, 0.72))
        self.assertIn("simile", content.is_duplicate({"id": "c", "concept": "c3", "text": "gm to every Peeler waking up anywhere in the world 🌍"}, hist, 0.72))
        self.assertIn("già usato", content.is_duplicate({"id": "d", "concept": "c1", "text": "totally different words here"}, hist, 0.72))
        self.assertIsNone(content.is_duplicate({"id": "e", "concept": "c4", "text": "Rug Gorilla opened a banana stand"}, hist, 0.72))

    # --- pubblicazioni ---------------------------------------------------------
    def test_slot_publishes_once_and_survives_restart(self):
        fake = FakeTelegram()
        at = datetime.datetime(2026, 10, 20, 8, 5, tzinfo=UTC)  # 10:05 a Roma
        self.make(at, fake)
        self.make(at + datetime.timedelta(minutes=1), fake)  # "riavvio": nuovo Bot, stato riletto dal disco
        self.assertEqual(fake.methods().count("sendPoll") + fake.methods().count("sendMessage"), 1)
        hist = json.loads((self.dir / "history.json").read_text())
        self.assertEqual(hist[-1]["platform"], "telegram")

    def test_never_repeats_until_pool_exhausted_then_alerts(self):
        fake = FakeTelegram()
        pool = json.loads((self.dir / "content/telegram.json").read_text())
        rome = bot.ZoneInfo("Europe/Rome")
        for i in range(len(pool) // 4 + 3):
            for h in (10, 14, 18, 22):  # orari locali: valgono anche dopo il cambio dell'ora legale
                self.make(datetime.datetime(2026, 10, 20, h, 5, tzinfo=rome) + datetime.timedelta(days=i), fake)
        hist = [h for h in json.loads((self.dir / "history.json").read_text()) if h["platform"] == "telegram"]
        ids = [h["id"] for h in hist]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(any("finiti" in f.get("text", "") for m, f in fake.calls if m == "sendMessage" and f["chat_id"] == "1"))

    def test_preview_mode_sends_only_to_admin(self):
        state = json.loads((self.dir / "state.json").read_text())
        state["preview"] = True
        (self.dir / "state.json").write_text(json.dumps(state))
        fake = FakeTelegram()
        self.make(datetime.datetime(2026, 10, 20, 8, 5, tzinfo=UTC), fake)
        posts = [f for m, f in fake.calls if m in ("sendMessage", "sendPoll")]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["chat_id"], "1")
        self.assertIn("ANTEPRIMA", posts[0]["text"])

    def test_pause_stops_posts_but_not_countdown(self):
        state = json.loads((self.dir / "state.json").read_text())
        state["paused"] = True
        (self.dir / "state.json").write_text(json.dumps(state))
        fake = FakeTelegram()
        self.make(datetime.datetime(2026, 10, 20, 8, 5, tzinfo=UTC), fake)
        self.assertNotIn("sendPoll", fake.methods())
        self.assertIn("editMessageText", fake.methods())

    def test_welcome_one_message_and_previous_deleted(self):
        join = lambda uid, name: {"update_id": uid, "chat_member": {
            "old_chat_member": {"status": "left"}, "new_chat_member": {"status": "member", "user": {"first_name": name}}}}
        fake = FakeTelegram(members=8)
        fake.updates = [[join(1, "Ana"), join(2, "Bo")], [join(3, "Cy")]]
        at = datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
        self.make(at, fake)
        self.make(at + datetime.timedelta(minutes=1), fake)
        welcomes = [f for m, f in fake.calls if m == "sendMessage" and "Welcome" in f.get("text", "")]
        self.assertEqual(len(welcomes), 2)
        self.assertIn("Ana, Bo", welcomes[0]["text"])
        self.assertIn("OG Peeler #8 of 500", welcomes[0]["text"])
        self.assertIn("t.me/OrangeOrangus", welcomes[0]["text"])
        self.assertEqual([f["message_id"] for m, f in fake.calls if m == "deleteMessage"], [welcomes and 101])

    def test_group_filters_like_rose(self):
        def msg(uid, mid, text, **extra):
            return {"update_id": mid, "message": {"message_id": mid, "text": text, "chat": {"id": -5, "type": "supergroup", "username": "test"},
                                                  "from": {"id": uid}, **extra}}
        fake = FakeTelegram()
        fake.updates = [[msg(1, 1, '/filter demo Play: https://example.com/demo'), msg(2, 2, '/filter x y'), msg(3, 3, "any DEMO link?"),
                         msg(3, 4, "demo again"), msg(3, 5, "demos"), msg(1, 6, "/setrules Be kind"), msg(3, 7, "/rules"),
                         msg(1, 8, "/stop demo"), msg(3, 9, "demo"),
                         msg(1, 10, "/filter /ac Contract: 0x1"), msg(3, 11, "/ac@OrangeBot"), msg(1, 12, "/stop /ac")]]
        with mock.patch.object(tg, "call", fake):
            b = bot.Bot(now=datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC))
            b.commands()
        sent = [f["text"] for m, f in fake.calls if m == "sendMessage"]
        self.assertEqual(sent, ["✅ Filter saved: demo", "Play: https://example.com/demo", "✅ Rules saved. Members get them with /rules.",
                                "Be kind", "🗑 Filter removed.", "✅ Filter saved: /ac", "Contract: 0x1",
                                "🗑 Filter removed."])
        self.assertNotIn("demo", b.state["filters"])  # the "demo" filter was removed with /stop
        self.assertIn("/x", b.state["filters"])  # defaults from config.json are there from the start

    def test_antiflood_mutes_spammer_not_admin(self):
        def msg(uid, i, date):
            return {"update_id": i, "message": {"message_id": i, "text": "hi", "date": date, "chat": {"id": -5, "username": "test"},
                                                "from": {"id": uid, "first_name": "Z"}}}
        fake = FakeTelegram()
        fake.updates = [[msg(3, i, 1000 + i // 4) for i in range(1, 9)] + [msg(1, 20 + i, 1000) for i in range(8)]]  # user 3 spams; admin 1 too
        with mock.patch.object(tg, "call", fake):
            bot.Bot(now=datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC)).commands()
        mutes = [f for m, f in fake.calls if m == "restrictChatMember"]
        self.assertEqual([f["user_id"] for f in mutes], [3])
        self.assertFalse(mutes[0]["permissions"]["can_send_messages"])
        self.assertEqual(mutes[0]["until_date"], 1001 + 600)

    def test_new_default_filter_added_to_existing_state_once(self):
        state = json.loads((self.dir / "state.json").read_text())
        state["filters"] = {"/x": "old x"}  # live state from before /tlg existed; /demo was removed by an admin
        state["filters_seeded"] = ["/x", "/demo"]
        (self.dir / "state.json").write_text(json.dumps(state))
        b = bot.Bot(now=datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC))
        f = b.group.filters
        self.assertEqual(f["/x"], "old x")  # an edited default is kept
        self.assertNotIn("/demo", f)  # a default an admin removed does not come back
        self.assertIn("/tlg", f)  # defaults added later reach the live state
        b.group.filters.pop("/tlg")
        self.assertNotIn("/tlg", b.group.filters)

    def test_roadmap_sends_pdf_once_then_reuses_file_id(self):
        def ask(i):
            return {"update_id": i, "message": {"message_id": i, "text": "/roadmap", "chat": {"id": -5, "username": "test"}, "from": {"id": 3}}}
        fake, uploads = FakeTelegram(), []
        fake.updates = [[ask(1)], [ask(2)]]
        def upload(method, fields, field, path, **_):
            uploads.append((method, field, Path(path).name))
            return {"document": {"file_id": "FID"}}
        with mock.patch.object(tg, "call", fake), mock.patch.object(tg, "upload", upload):
            b = bot.Bot(now=datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC))
            b.commands()
            b.group.bot.mem["group_cooldown"].clear()  # skip the 20 s pause between answers
            b.commands()
        self.assertEqual(uploads, [("sendDocument", "document", "OrangeOrangus_Racing.pdf")])
        sent = [f for m, f in fake.calls if m == "sendDocument"]
        self.assertEqual([f["document"] for f in sent], ["FID"])
        self.assertEqual(sent[0]["reply_to_message_id"], 2)

    def test_updated_default_replaces_saved_text_once(self):
        state = json.loads((self.dir / "state.json").read_text())
        state["filters"] = {"/social": "old list", "/x": "my x"}
        state["filters_seeded"] = ["/x", "/demo", "/social"]
        (self.dir / "state.json").write_text(json.dumps(state))
        b = bot.Bot(now=datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC))
        self.assertIn("orangeorangus.duckdns.org", b.group.filters["/social"])
        self.assertEqual(b.group.filters["/x"], "my x")  # defaults without a new revision are left alone
        b.group.filters["/social"] = "admin edit"
        self.assertEqual(b.group.filters["/social"], "admin edit")  # and the update is applied only once

    # --- programma: niente sondaggio delle 12, niente Peel Friday, niente X ----------
    ROME = bot.ZoneInfo("Europe/Rome")

    def group_posts(self, fake, since=0):
        return [(m, f) for m, f in fake.calls[since:] if m in ("sendPoll", "sendMessage", "sendPhoto") and f["chat_id"] == "@test"]

    def test_daily_schedule_quiz_meme_reward_engage(self):
        fake, got = FakeTelegram(), {}
        for h in (10, 12, 14, 16, 18, 22):
            before = len(fake.calls)
            self.make(datetime.datetime(2026, 11, 20, h, 5, tzinfo=self.ROME), fake)  # 20/11/2026 è un venerdì
            got[h] = self.group_posts(fake, before)
        hist = json.loads((self.dir / "history.json").read_text(encoding="utf-8"))
        self.assertEqual([(x["ts"][11:13], x["type"]) for x in hist], [("10", "quiz"), ("14", "meme"), ("22", "engage")])
        self.assertEqual(got[12], [])  # nessun sondaggio a mezzogiorno
        self.assertEqual(got[16], [])  # nessun Peel Friday
        self.assertEqual(len(got[18]), 1)  # alle 18:00 solo il promemoria Orange Racing
        self.assertIn("orangeracing.duckdns.org", got[18][0][1]["text"])
        self.assertFalse(any("PEEL FRIDAY" in f.get("text", "").upper() for _, f in fake.calls))

    def test_x_posting_removed(self):
        self.assertFalse((REPO / "xapi.py").exists())
        self.assertTrue((REPO / "content" / "x.json").exists())  # contenuti X conservati come archivio
        self.assertNotIn("x", json.loads((REPO / "config.json").read_text(encoding="utf-8")))
        fake = FakeTelegram()
        with mock.patch.dict(os.environ, {"X_API_KEY": "k", "X_API_SECRET": "k", "X_ACCESS_TOKEN": "k", "X_ACCESS_SECRET": "k"}):
            for h in range(24):  # tutta la giornata, compresi i vecchi orari X 11:30 e 19:30
                self.make(datetime.datetime(2026, 11, 16, h, 31, tzinfo=self.ROME), fake)
        hist = json.loads((self.dir / "history.json").read_text(encoding="utf-8"))
        self.assertFalse([x for x in hist if x["platform"] != "telegram"])

    # --- promemoria giornaliero Orange Racing ----------------------------------------
    def rewards(self, fake):
        return [(m, f) for m, f in fake.calls if m in ("sendPhoto", "sendMessage") and "orangeracing" in f.get("caption", f.get("text", ""))]

    def test_daily_reward_text_only_when_image_missing(self):
        fake = FakeTelegram()
        self.make(datetime.datetime(2026, 11, 14, 18, 0, tzinfo=self.ROME), fake)
        r = self.rewards(fake)
        self.assertEqual([m for m, _ in r], ["sendMessage"])
        self.assertEqual(r[0][1]["chat_id"], "@test")
        self.assertEqual(r[0][1]["reply_markup"]["inline_keyboard"][0][0]["url"], "https://orangeracing.duckdns.org")

    def test_daily_reward_photo_once_per_day_survives_restart_and_rotates(self):
        (self.dir / "assets").mkdir()
        (self.dir / "assets/daily-reward.png").write_bytes(b"PNG fake")
        fake, uploads = FakeTelegram(), []
        def upload(method, fields, field, path, **_):
            uploads.append((method, field, Path(path).name, json.loads(fields["reply_markup"])))
            return {"message_id": 1, "photo": [{"file_id": "small"}, {"file_id": "PHOTO_ID"}]}
        day1 = datetime.datetime(2026, 11, 14, 18, 1, tzinfo=self.ROME)
        with mock.patch.object(tg, "upload", upload):
            for minutes in (0, 1, 30, 120):  # ogni make() = nuovo Bot = riavvio
                self.make(day1 + datetime.timedelta(minutes=minutes), fake)
            self.make(day1 + datetime.timedelta(days=1), fake)
        self.assertEqual([u[:3] for u in uploads], [("sendPhoto", "photo", "daily-reward.png")])  # caricata una volta
        self.assertEqual(uploads[0][3]["inline_keyboard"][0][0]["url"], "https://orangeracing.duckdns.org")
        again = [f for m, f in fake.calls if m == "sendPhoto"]
        self.assertEqual([f["photo"] for f in again], ["PHOTO_ID"])  # il giorno dopo: stesso file_id
        self.assertEqual([m for m, _ in self.rewards(fake)], ["sendPhoto"])  # nessun testo di ripiego in più

    def test_daily_reward_not_before_time_and_catch_up_after_downtime(self):
        fake = FakeTelegram()
        self.make(datetime.datetime(2026, 11, 14, 17, 59, tzinfo=self.ROME), fake)
        self.assertEqual(self.rewards(fake), [])
        self.make(datetime.datetime(2026, 11, 14, 20, 30, tzinfo=self.ROME), fake)  # ripartito dopo una pausa
        self.make(datetime.datetime(2026, 11, 14, 20, 31, tzinfo=self.ROME), fake)
        self.assertEqual(len(self.rewards(fake)), 1)
        self.make(datetime.datetime(2026, 11, 15, 23, 0, tzinfo=self.ROME), fake)  # oltre la finestra: niente invio tardivo
        self.assertEqual(len(self.rewards(fake)), 1)
        texts = [f["text"] for _, f in self.rewards(fake)]
        self.assertFalse(any(w in t.lower() for t in texts for w in ("token", "earn", "$orangu", "profit")))

    def test_daily_reward_preview_goes_to_admin_and_test_command(self):
        state = json.loads((self.dir / "state.json").read_text())
        state["preview"] = True
        (self.dir / "state.json").write_text(json.dumps(state))
        fake = FakeTelegram()
        self.make(datetime.datetime(2026, 11, 14, 18, 0, tzinfo=self.ROME), fake)
        self.assertEqual([f["chat_id"] for _, f in self.rewards(fake)], ["1"])
        fake.updates = [[{"update_id": 9, "message": {"chat": {"type": "private", "id": 1}, "from": {"id": 1}, "text": "/reward_test"}}]]
        b = self.make(datetime.datetime(2026, 11, 15, 9, 0, tzinfo=self.ROME), fake)
        self.assertEqual([f["chat_id"] for _, f in self.rewards(fake)], ["1", "1"])
        self.assertEqual(b.state["daily_reward_index"], 0)  # il test non consuma la rotazione

    # --- anti-raid -----------------------------------------------------------
    def group_msg(self, uid, i, text, **extra):
        return {"update_id": i, "message": {"message_id": i, "text": text, "date": 1000, "chat": {"id": -5, "username": "test"},
                                            "from": {"id": uid, "first_name": "U"}, **extra}}

    def join(self, uid, i):
        return {"update_id": i, "chat_member": {"old_chat_member": {"status": "left"},
                                                "new_chat_member": {"status": "member", "user": {"id": uid, "first_name": f"N{uid}"}}}}

    def run_updates(self, updates):
        fake = FakeTelegram()
        fake.updates = [updates]
        with mock.patch.object(tg, "call", fake):
            b = bot.Bot(now=datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC))
            b.commands()
        return b, fake

    def test_antiraid_bans_new_members_only_while_on(self):
        b, fake = self.run_updates([self.join(10, 1), self.group_msg(1, 2, "/antiraid 2h"), self.join(11, 3), self.join(12, 4),
                                    self.group_msg(1, 5, "/antiraid off"), self.join(13, 6)])
        bans = [f for m, f in fake.calls if m == "banChatMember"]
        self.assertEqual([f["user_id"] for f in bans], [11, 12])
        self.assertEqual(bans[0]["until_date"], int(b.clock().timestamp()) + 3600)  # a one-hour temporary ban
        welcomes = [f["text"] for m, f in fake.calls if m == "sendMessage" and "Welcome" in f.get("text", "")]
        self.assertTrue(welcomes and "N11" not in welcomes[0] and "N10" in welcomes[0] and "N13" in welcomes[0])

    def test_auto_antiraid_switches_on_at_threshold(self):
        b, fake = self.run_updates([self.group_msg(1, 1, "/autoantiraid 3")] + [self.join(20 + i, 2 + i) for i in range(5)])
        banned = [f["user_id"] for m, f in fake.calls if m == "banChatMember"]
        self.assertEqual(banned, [22, 23, 24])  # the third join trips it; the first two got in
        self.assertTrue(b.raid.active())

    def test_antiraid_and_lock_commands_are_admin_only(self):
        b, fake = self.run_updates([self.group_msg(3, 1, "/antiraid"), self.group_msg(3, 2, "/lock all"), self.join(30, 3)])
        self.assertFalse(b.raid.active())
        self.assertEqual([m for m, _ in fake.calls if m in ("banChatMember", "setChatPermissions")], [])

    def test_lock_links_deletes_only_non_admin_links(self):
        b, fake = self.run_updates([self.group_msg(1, 1, "/lock links"), self.group_msg(3, 2, "join https://evil.example now"),
                                    self.group_msg(3, 3, "hello"), self.group_msg(1, 4, "see https://orangeorangus.duckdns.org")])
        self.assertEqual([f["message_id"] for m, f in fake.calls if m == "deleteMessage"], [2])

    def test_lock_all_restores_the_saved_permissions(self):
        fake = FakeTelegram()
        fake.updates = [[self.group_msg(1, 1, "/lock all"), self.group_msg(1, 2, "/unlock all")]]
        original = {"can_send_messages": True, "can_send_polls": False}
        orig_call = fake.__call__
        def call(method, fields, **kw):
            return {"permissions": original} if method == "getChat" else orig_call(method, fields, **kw)
        with mock.patch.object(tg, "call", call):
            bot.Bot(now=datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC)).commands()
        perms = [f["permissions"] for m, f in fake.calls if m == "setChatPermissions"]
        self.assertEqual(perms, [{"can_send_messages": False}, original])

    def test_default_group_commands(self):
        fake = FakeTelegram()
        fake.updates = [[{"update_id": 1, "message": {"message_id": 1, "text": "/x", "chat": {"id": -5, "username": "test"}, "from": {"id": 3}}},
                         {"update_id": 2, "message": {"message_id": 2, "text": "/demo", "chat": {"id": -5, "username": "test"}, "from": {"id": 3}}},
                         {"update_id": 3, "message": {"message_id": 3, "text": "/social", "chat": {"id": -5, "username": "test"}, "from": {"id": 3}}}]]
        with mock.patch.object(tg, "call", fake):
            bot.Bot(now=datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC)).commands()
        sent = [f["text"] for m, f in fake.calls if m == "sendMessage"]
        self.assertIn("https://x.com/orangeorangus", sent[0])
        self.assertIn("orangeracing.duckdns.org", sent[1])
        for link in ("orangeorangus.duckdns.org", "x.com/orangeorangus", "instagram.com/orangeorangus", "t.me/OrangeOrangus", "discord.gg/", "orangeracing.duckdns.org"):
            self.assertIn(link, sent[2])  # /social lists every official link

    def test_og_announcement_once(self):
        state = json.loads((self.dir / "state.json").read_text())
        state.pop("og_existing_done")
        (self.dir / "state.json").write_text(json.dumps(state))
        fake = FakeTelegram(members=9)
        at = datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
        self.make(at, fake)
        self.make(at + datetime.timedelta(minutes=1), fake)
        og = [f["text"] for m, f in fake.calls if m == "sendMessage" and "OG PEELERS" in f.get("text", "")]
        self.assertEqual(len(og), 1)
        self.assertIn("first 9 members", og[0])

    def test_milestone_announced_once(self):
        fake = FakeTelegram(members=60)
        at = datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
        self.make(at, fake)
        self.make(at + datetime.timedelta(minutes=1), fake)
        self.assertEqual(sum(1 for m, f in fake.calls if m == "sendMessage" and "MILESTONE: 50" in f.get("text", "")), 1)

    def test_rate_limit_retries_with_backoff(self):
        import urllib.error, io
        err = urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b'{"parameters":{"retry_after":3},"description":"Too Many Requests"}'))
        ok = mock.MagicMock()
        ok.__enter__.return_value = io.BytesIO(b'{"result": 5}')
        slept = []
        with mock.patch("urllib.request.urlopen", side_effect=[err, ok]):
            self.assertEqual(tg.call("getChatMemberCount", {}, sleep=slept.append), 5)
        self.assertEqual(slept, [3])



if __name__ == "__main__":
    unittest.main()
