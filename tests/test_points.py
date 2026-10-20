"""Test offline dei Peel Points: Telegram e X sono simulati. Esegui con: python -m unittest discover tests"""
import datetime, json, os, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import bot, points, tg

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def tid(at):  # id di un post X creato all'istante `at`
    return str(((int(at.timestamp() * 1000) - points.X_EPOCH) << 22) | 1)


class Fake:
    def __init__(self):
        self.calls, self.members, self.n = [], {"10", "11", "12", "99"}, 100

    def __call__(self, method, fields, **_):
        self.calls.append((method, fields))
        if method == "getChatMember":
            return {"status": "member" if str(fields["user_id"]) in self.members else "left"}
        if method == "createChatInviteLink":
            return {"invite_link": f"https://t.me/+{fields['name']}"}
        if method == "getMe":
            return {"username": "OrangeOrangusBot"}
        if method == "sendMessage":
            self.n += 1
            return {"message_id": self.n}
        return True

    def to(self, uid):
        return [f["text"] for m, f in self.calls if m == "sendMessage" and str(f["chat_id"]) == str(uid)]


class PointsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        for f in ("config.json", "history.json"):
            shutil.copy(REPO / f, self.dir / f)
        shutil.copytree(REPO / "content", self.dir / "content")
        (self.dir / "state.json").write_text("{}")
        self.fake = Fake()
        self.ps = [mock.patch.object(bot, "ROOT", self.dir), mock.patch.object(tg, "call", self.fake),
                   mock.patch.dict(os.environ, {"CHAT_ID": "@test", "BOT_TOKEN": "x", "ADMIN_USER_ID": "1"})]
        for p in self.ps:
            p.start()
        os.environ.pop("GITHUB_ACTIONS", None)
        self.b = bot.Bot(now=T0)
        self.p = self.b.points
        self.p.fetch = lambda url: {"author": url.split("/")[3].lower(), "text": "gm #OrangeOrangus peel the hype"}
        self.p.d["open"] = True

    def tearDown(self):
        for p in self.ps:
            p.stop()
        shutil.rmtree(self.dir)

    def say(self, uid, text, admin=False):
        return self.p.on_message({"from": {"id": uid, "first_name": f"U{uid}"}, "text": text}, admin)

    def pts(self, uid):
        return self.p.d["users"][str(uid)]["pts"]

    def link(self, uid=10, handle="ana"):
        self.say(uid, f"/x @{handle}")

    def test_closed_gives_no_reply_to_users_but_admin_can_test(self):
        self.p.d["open"] = False
        self.say(10, "/start")
        self.assertEqual(self.fake.to(10), [])
        self.say(1, "/points", admin=True)
        self.assertTrue(self.fake.to(1))

    def test_join_points_once_and_requires_membership(self):
        self.say(55, "/start")
        self.assertIn("Join the Troop first", self.fake.to(55)[0])
        self.say(10, "/start"); self.say(10, "/start")
        self.assertEqual(self.pts(10), 10)

    def test_checkin_once_per_day(self):
        self.say(10, "/checkin"); self.say(10, "/checkin")
        self.assertEqual(self.pts(10), 5)
        self.b.now = T0 + datetime.timedelta(days=1)
        self.say(10, "/checkin")
        self.assertEqual(self.pts(10), 10)

    def test_post_verified_awards_once_a_day(self):
        self.link()
        t = tid(T0 - datetime.timedelta(hours=2))
        self.say(10, f"/post https://x.com/ana/status/{t}")
        self.assertEqual(self.pts(10), 20)
        self.say(10, f"/post https://x.com/ana/status/{t}")  # stesso post
        self.say(10, f"/post https://x.com/ana/status/{tid(T0 - datetime.timedelta(hours=1))}")  # secondo post nello stesso giorno
        self.assertEqual(self.pts(10), 20)

    def test_post_rejected_cases(self):
        self.say(10, f"/post https://x.com/ana/status/{tid(T0)}")
        self.assertIn("Link your X account", self.fake.to(10)[-1])
        self.link()
        self.say(10, f"/post https://x.com/bob/status/{tid(T0)}")
        self.assertIn("not from your linked account", self.fake.to(10)[-1])
        self.say(10, f"/post https://x.com/ana/status/{tid(T0 - datetime.timedelta(days=5))}")
        self.assertIn("last 48 hours", self.fake.to(10)[-1])
        self.say(10, "/post https://evil.com/ana/status/123456")
        self.assertIn("Send the link", self.fake.to(10)[-1])
        self.p.fetch = lambda url: {"author": "ana", "text": "hello world"}
        self.say(10, f"/post https://x.com/ana/status/{tid(T0)}")
        self.assertIn("must mention", self.fake.to(10)[-1])
        self.p.fetch = lambda url: {"author": "other", "text": "#OrangeOrangus"}
        self.say(10, f"/post https://x.com/ana/status/{tid(T0)}")
        self.assertIn("does not match", self.fake.to(10)[-1])
        self.assertEqual(self.pts(10), 0)

    def test_one_x_account_per_member(self):
        self.link(10, "ana"); self.link(11, "ana")
        self.assertIn("already linked", self.fake.to(11)[-1])

    def test_x_down_waits_for_admin_then_approve_or_reject(self):
        def down(url): raise OSError("offline")
        self.p.fetch = down
        self.link()
        t = tid(T0)
        self.say(10, f"/post https://x.com/ana/status/{t}")
        self.assertEqual(self.pts(10), 0)
        self.assertTrue(any("review" in x for x in self.fake.to(1)))
        self.p.on_callback({"id": "c", "from": {"id": 1}, "data": f"ok:{t}"})
        self.assertEqual(self.pts(10), 20)
        self.link(11, "bo")
        t2 = tid(T0 - datetime.timedelta(minutes=3))
        self.say(11, f"/post https://x.com/bo/status/{t2}")
        self.p.on_callback({"id": "c", "from": {"id": 1}, "data": f"no:{t2}"})
        self.assertEqual(self.pts(11), 0)
        self.assertEqual(self.p.d["tweets"][t2]["status"], "rejected")

    def test_only_admin_can_use_buttons(self):
        self.p.fetch = lambda url: (_ for _ in ()).throw(OSError("offline"))
        self.link()
        t = tid(T0)
        self.say(10, f"/post https://x.com/ana/status/{t}")
        self.p.on_callback({"id": "c", "from": {"id": 10}, "data": f"ok:{t}"})
        self.assertEqual(self.pts(10), 0)

    def test_revoke_removes_points_and_two_strikes_exclude(self):
        self.link()
        for i, d in enumerate((0, 1)):
            self.b.now = T0 + datetime.timedelta(days=d)
            t = tid(self.b.now - datetime.timedelta(minutes=5))
            self.say(10, f"/post https://x.com/ana/status/{t}")
            self.p.on_callback({"id": "c", "from": {"id": 1}, "data": f"no:{t}"})
        self.assertEqual(self.pts(10), 0)
        self.assertEqual(self.p.d["users"]["10"]["strikes"], 2)
        self.say(10, "/checkin")
        self.assertIn("excluded", self.fake.to(10)[-1])

    def test_daily_cap(self):
        self.p.cfg["daily_cap"] = 12
        self.say(10, "/start"); self.say(10, "/checkin")
        self.assertEqual(self.pts(10), 12)

    def test_referral_pays_after_hold_if_friend_stays(self):
        self.say(10, "/invite")
        link = self.p.d["users"]["10"]["link"]
        join = lambda uid: {"invite_link": {"invite_link": link}, "new_chat_member": {"user": {"id": uid}}}
        self.p.on_join(join(10))  # auto-invito ignorato
        self.p.on_join(join(11)); self.p.on_join(join(11))  # doppio ingresso contato una volta
        self.p.on_join(join(12))
        self.p.tick()
        self.assertEqual(self.pts(10), 0)  # prima delle 24h niente
        self.b.now = T0 + datetime.timedelta(hours=25)
        self.fake.members.discard("12")  # il secondo amico è uscito
        self.p.tick()
        self.assertEqual(self.pts(10), 30)
        self.assertEqual(self.p.d["users"]["10"]["invites"], 1)

    def test_admin_open_announces_once(self):
        self.p.d["open"] = False
        self.say(1, "/points_on", admin=True); self.say(1, "/points_off", admin=True); self.say(1, "/points_on", admin=True)
        posts = [f["text"] for m, f in self.fake.calls if m == "sendMessage" and f["chat_id"] == "@test"]
        self.assertEqual(len(posts), 1)
        self.assertIn("t.me/OrangeOrangusBot", posts[0])
        self.assertIn("no monetary value", posts[0])
        self.assertTrue(self.p.d["open"])

    def test_points_errors_never_stop_the_bot(self):
        with mock.patch.object(points.Points, "on_message", side_effect=RuntimeError("boom")):
            self.fake.updates = [[{"update_id": 1, "message": {"chat": {"type": "private"}, "from": {"id": 10}, "text": "/points"}}]]
            self.fake.getUpdates = True
            orig = self.fake.__call__
            with mock.patch.object(tg, "call", lambda m, f, **k: self.fake.updates.pop(0) if m == "getUpdates" and self.fake.updates else orig(m, f, **k)):
                self.b.commands()
        self.assertTrue(any("Peel Points" in x for x in self.fake.to(1)))  # avviso all'admin

    def test_disabled_by_default_in_repo_data(self):
        self.assertFalse(json.loads((REPO / "points.json").read_text()).get("open", False))


if __name__ == "__main__":
    unittest.main()
