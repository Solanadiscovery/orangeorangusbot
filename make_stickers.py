"""One-off: create the OG Peeler sticker pack owned by the admin."""
import json, os, sys, uuid, urllib.request, urllib.error

TOKEN = os.environ["BOT_TOKEN"]
ADMIN = int(os.environ["ADMIN_USER_ID"])
API = f"https://api.telegram.org/bot{TOKEN}/"
STICKERS = [("og-badge.png", "🍊"), ("og-cool.png", "😎"), ("peel-the-hype.png", "🔥"),
            ("gm.png", "☀️"), ("still-peeling.png", "💪"), ("not-in-this-jungle.png", "🙅")]


def call(method, data=None, files=None):
    if files:
        b = uuid.uuid4().hex
        body = b""
        for k, v in (data or {}).items():
            body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, path in files.items():
            body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{k}.png"\r\n'
                     f'Content-Type: image/png\r\n\r\n').encode() + open(path, "rb").read() + b"\r\n"
        body += f"--{b}--\r\n".encode()
        req = urllib.request.Request(API + method, body, {"Content-Type": f"multipart/form-data; boundary={b}"})
    else:
        req = urllib.request.Request(API + method, json.dumps(data or {}).encode(), {"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        return json.load(e)


bot = call("getMe")["result"]["username"]
name = f"og_peelers_by_{bot}"
link = f"https://t.me/addstickers/{name}"


def announce():
    if os.environ.get("ANNOUNCE") != "1":
        return
    chat = os.environ["CHAT_ID"]
    st = call("getStickerSet", {"name": name})["result"]["stickers"][0]["file_id"]
    call("sendSticker", {"chat_id": chat, "sticker": st})
    print(call("sendMessage", {"chat_id": chat, "disable_web_page_preview": True, "text":
        "🏅 OG PEELER STICKERS ARE HERE 🏅\n\nOfficial sticker pack for the OG Peelers, the first 500 of the Troop. "
        "Add it and flex your OG status in every chat 🦧🍊\n👇\n" + link}).get("ok"))


cur = call("getStickerSet", {"name": name})
if cur.get("ok"):
    if os.environ.get("REPLACE") == "1":
        for i, old in enumerate(cur["result"]["stickers"][:len(STICKERS)]):
            f, e = STICKERS[i]
            r = call("replaceStickerInSet", {"user_id": ADMIN, "name": name, "old_sticker": old["file_id"],
                     "sticker": json.dumps({"sticker": "attach://s", "format": "static", "emoji_list": [e]})},
                     {"s": os.path.join("stickers", f)})
            print(f, r.get("ok"), r.get("description", ""))
    print("exists", link); announce(); sys.exit(0)
items = [{"sticker": f"attach://s{i}", "format": "static", "emoji_list": [e]} for i, (_, e) in enumerate(STICKERS)]
files = {f"s{i}": os.path.join("stickers", f) for i, (f, _) in enumerate(STICKERS)}
r = call("createNewStickerSet", {"user_id": ADMIN, "name": name, "title": "OG Peeler - OrangeOrangus",
                                 "stickers": json.dumps(items)}, files)
print(r if not r.get("ok") else f"created {link}")
if r.get("ok"):
    announce()
sys.exit(0 if r.get("ok") else 1)
