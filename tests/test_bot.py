"""Test offline: le chiamate a Telegram e X sono simulate. Esegui con: python -m unittest discover tests"""
import datetime, json, os, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import bot, content, countdown, tg, xapi

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
        if method in ("sendMessage", "sendPoll"):
            self.next_id += 1
            return {"message_id": self.next_id}
        return True

    def methods(self):
        return [m for m, _ in self.calls]


class BotTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        shutil.copy(REPO / "config.json", self.dir / "config.json")
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

    def test_x_and_telegram_get_different_content(self):
        fake = FakeTelegram()
        sent = []
        env = {k: "k" for k in xapi.KEYS}
        with mock.patch.dict(os.environ, env), mock.patch.object(xapi, "post", lambda item, footer: sent.append(item)):
            self.make(datetime.datetime(2026, 10, 20, 8, 5, tzinfo=UTC), fake)
            self.make(datetime.datetime(2026, 10, 20, 9, 35, tzinfo=UTC), fake)  # 11:35 a Roma: slot X
        self.assertEqual(len(sent), 1)
        hist = json.loads((self.dir / "history.json").read_text())
        tg_item = [h for h in hist if h["platform"] == "telegram"][-1]
        self.assertLess(content.similarity(tg_item["text"], content.text_of(sent[0])), 0.72)

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
        self.assertEqual(list(b.state["filters"]), ["/x", "/demo", "/tlg"])

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
        self.assertEqual(b.group.filters, {"/x": "old x", "/tlg": "👉 Join the Troop: https://t.me/OrangeOrangus"})
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

    def test_default_group_commands(self):
        fake = FakeTelegram()
        fake.updates = [[{"update_id": 1, "message": {"message_id": 1, "text": "/x", "chat": {"id": -5, "username": "test"}, "from": {"id": 3}}},
                         {"update_id": 2, "message": {"message_id": 2, "text": "/demo", "chat": {"id": -5, "username": "test"}, "from": {"id": 3}}}]]
        with mock.patch.object(tg, "call", fake):
            bot.Bot(now=datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC)).commands()
        sent = [f["text"] for m, f in fake.calls if m == "sendMessage"]
        self.assertIn("https://x.com/orangeorangus", sent[0])
        self.assertIn("orangeorangus-racingdemo.netlify.app", sent[1])

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

    def test_x_error_does_not_cause_duplicate_post(self):
        fake = FakeTelegram()
        env = {k: "k" for k in xapi.KEYS}
        calls = []

        def boom(item, cfg):
            calls.append(item["id"])
            raise RuntimeError("X 503")
        with mock.patch.dict(os.environ, env), mock.patch.object(xapi, "post", boom):
            self.make(datetime.datetime(2026, 10, 20, 9, 35, tzinfo=UTC), fake)      # slot 11:30: fails
            self.make(datetime.datetime(2026, 10, 20, 9, 40, tzinfo=UTC), fake)      # same slot, restart: no retry
        self.assertEqual(len(calls), 1)
        hist = json.loads((self.dir / "history.json").read_text())
        self.assertEqual([h["id"] for h in hist if h["platform"] == "x"].count(calls[0]), 1)

    def test_x_min_gap_blocks_bursts(self):
        fake = FakeTelegram()
        env = {k: "k" for k in xapi.KEYS}
        sent = []
        cfg = json.loads((self.dir / "config.json").read_text())
        cfg["x"]["times"] = ["11:30", "12:00"]  # misconfigured: two posts 30 min apart
        (self.dir / "config.json").write_text(json.dumps(cfg))
        with mock.patch.dict(os.environ, env), mock.patch.object(xapi, "post", lambda item, c: sent.append(item)):
            self.make(datetime.datetime(2026, 10, 20, 9, 35, tzinfo=UTC), fake)      # 11:35
            self.make(datetime.datetime(2026, 10, 20, 10, 5, tzinfo=UTC), fake)      # 12:05
        self.assertEqual(len(sent), 1)

    def test_x_only_hype_never_quiz_or_poll(self):
        fake = FakeTelegram()
        env = {k: "k" for k in xapi.KEYS}
        sent = []
        with mock.patch.dict(os.environ, env), mock.patch.object(xapi, "post", lambda item, c: sent.append(item)):
            for day in range(20, 26):
                for hh in (9, 13, 17, 21):  # UTC: after every X slot (min gap is honoured)
                    self.make(datetime.datetime(2026, 10, day, hh, 35, tzinfo=UTC), fake)
        self.assertGreater(len(sent), 4)
        self.assertTrue(all(i["type"] == "hype" for i in sent))
        self.assertEqual(len({i["id"] for i in sent}), len(sent))


class XNoLinks(unittest.TestCase):
    def test_links_stripped(self):
        b = xapi.body_for({"type": "text", "text": "Join us https://t.me/OrangeOrangus now t.me/x"}, "#OrangeOrangus")
        self.assertNotIn("t.me", b["text"]); self.assertNotIn("http", b["text"])

    def test_footer_telegram_in_bio(self):
        f = "Telegram in bio 👆 #OrangeOrangus"
        self.assertIn("Telegram in bio", xapi.body_for({"type": "poll", "question": "Pick one", "options": ["a", "b"]}, f)["text"])
        t = xapi.body_for({"type": "text", "text": "Join the Troop (link in bio)."}, f)["text"]
        self.assertEqual(t.lower().count("in bio"), 1)

    def test_x_hashtags_topical_allowed_and_not_repetitive(self):
        cfg = json.load(open(REPO / "config.json"))["x"]
        pool = json.load(open(REPO / "content" / "x.json"))
        combos = set()
        for item in pool:
            text = xapi.body_for(item, cfg)["text"]
            tags = [w for w in text.splitlines()[-1].split() if w.startswith("#")]
            self.assertLessEqual(xapi.weight(text), 280)
            self.assertNotIn("http", text)
            self.assertIn("Telegram in bio", text) if "in bio" not in item.get("text", "").lower() else None
            self.assertLessEqual(len(tags), 1 + cfg["max_topic_hashtags"])
            allowed = {h.lower() for h in cfg["allowed_hashtags"] + cfg["hashtags"]}
            self.assertTrue(all(h.lower().rstrip('.!?,') in allowed for h in tags), tags)
            combos.add(tuple(tags))
        # a generic post gets no extra hashtag; an off-list or untagged one is ignored
        plain = xapi.body_for({"type": "text", "text": "Orango peels."}, cfg)["text"]
        self.assertNotIn("#Solana", plain)
        rogue = xapi.body_for({"type": "text", "text": "Orango peels.", "tags": ["#100x", "#Solana"]}, cfg)["text"]
        self.assertNotIn("#100x", rogue)
        self.assertIn("#Solana", rogue)
        self.assertGreater(len(combos), 2)  # not the same combination everywhere

    def test_x_text_never_cut_when_long(self):
        cfg = json.load(open(REPO / "config.json"))["x"]
        long = xapi.body_for({"type": "text", "text": "x" * 250, "tags": ["#Solana"]}, cfg)["text"]
        self.assertTrue(long.startswith("x" * 250))
        self.assertLessEqual(xapi.weight(long), 280)


if __name__ == "__main__":
    unittest.main()
