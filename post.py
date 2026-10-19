"""Pubblica il post del mattino o della sera sul canale Telegram di OrangeOrangus.

Variabili d'ambiente: BOT_TOKEN, CHAT_ID (es. @orangeorangus o -100...).
Uso: python post.py            -> pubblica il post di oggi
     python post.py --dry-run  -> mostra il post senza inviarlo
"""
import datetime, json, os, sys, urllib.request, uuid
from pathlib import Path

ROOT = Path(__file__).parent
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def pick_post(today, slot):
    content = json.loads((ROOT / "content.json").read_text(encoding="utf-8"))
    posts = content[DAYS[today.weekday()]][slot]
    week = today.isocalendar()[1]
    post = posts[week % len(posts)]  # ruota i post settimana dopo settimana
    return post["text"] + "\n\n" + content["footer"], post.get("photo")


def api(method, fields, photo=None):
    url = f"https://api.telegram.org/bot{os.environ['BOT_TOKEN']}/{method}"
    if photo is None:
        data = json.dumps(fields).encode()
        headers = {"Content-Type": "application/json"}
    else:  # multipart per caricare l'immagine
        b = uuid.uuid4().hex
        parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="{photo.name}"\r\n\r\n'.encode()
                     + photo.read_bytes() + f"\r\n--{b}--\r\n".encode())
        data = b"".join(parts)
        headers = {"Content-Type": f"multipart/form-data; boundary={b}"}
    with urllib.request.urlopen(urllib.request.Request(url, data, headers)) as r:
        return json.load(r)


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    slot = "am" if now.hour < 14 else "pm"  # run del mattino o della sera
    text, photo = pick_post(now.date(), slot)
    if "--dry-run" in sys.argv:
        print(text, "\n[photo]", photo)
        return
    chat = os.environ["CHAT_ID"]
    photo_path = ROOT / photo if photo else None
    if photo_path and photo_path.exists():
        api("sendPhoto", {"chat_id": chat, "caption": text[:1024]}, photo_path)
    else:
        api("sendMessage", {"chat_id": chat, "text": text, "disable_web_page_preview": True})
    print("Pubblicato.")


if __name__ == "__main__":
    main()
