"""Pubblica i post di OrangeOrangus sul canale Telegram.

Durante il countdown (3 giorni prima del lancio + giorno del lancio) usa campaign.json,
4 post al giorno con sondaggi e quiz. Negli altri giorni usa content.json, 2 post al giorno.

Variabili d'ambiente: BOT_TOKEN, CHAT_ID (es. @orangeorangus o -100...), SLOT (ora UTC, impostata dal workflow).
Uso: python post.py            -> pubblica il post di questo orario
     python post.py --dry-run  -> mostra il post senza inviarlo
"""
import datetime, json, os, sys, urllib.error, urllib.request, uuid
from pathlib import Path

ROOT = Path(__file__).parent
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
CAMPAIGN_SLOTS = ["08", "12", "16", "20"]
REGULAR_SLOTS = {"08": "am", "18": "pm"}


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def current_slot(now):
    slot = os.environ.get("SLOT", "").strip()
    if slot:
        return slot
    # avvio manuale: l'ultimo orario previsto prima di adesso
    past = [s for s in sorted(set(CAMPAIGN_SLOTS) | set(REGULAR_SLOTS)) if int(s) <= now.hour]
    return past[-1] if past else "08"


def pick_post(now, slot):
    """Restituisce il post da pubblicare, oppure None se in questo orario non c'è nulla."""
    content = load("content.json")
    campaign = load("campaign.json")
    if campaign["launch_date"]:
        offset = str((now.date() - datetime.date.fromisoformat(campaign["launch_date"])).days)
        if offset in campaign["days"]:
            post = campaign["days"][offset].get(slot)
            return dict(post, footer=content["footer"]) if post else None
    if slot not in REGULAR_SLOTS:
        return None
    posts = content[DAYS[now.weekday()]][REGULAR_SLOTS[slot]]
    post = posts[now.isocalendar()[1] % len(posts)]  # ruota i post settimana dopo settimana
    return dict(post, footer=content["footer"])


def api(method, fields, photo=None):
    token = os.environ.get("BOT_TOKEN", "").strip().removeprefix("bot")
    if not token:
        sys.exit("BOT_TOKEN mancante: aggiungilo nei Secrets del repository.")
    url = f"https://api.telegram.org/bot{token}/{method}"
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
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers)) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        hint = {404: "token del bot non valido", 400: "CHAT_ID errato", 403: "il bot non è admin del canale"}
        sys.exit(f"Errore Telegram {e.code} ({hint.get(e.code, '?')}): {e.read().decode()}")


def send(chat, post):
    if "poll" in post or "quiz" in post:  # sondaggi e quiz: interazione diretta del pubblico
        fields = {"chat_id": chat, "question": post.get("poll") or post["quiz"], "options": post["options"]}
        if "quiz" in post:
            fields.update(type="quiz", correct_option_id=post["correct"])
        return api("sendPoll", fields)
    text = post["text"] + "\n\n" + post["footer"]
    photo = ROOT / post["photo"] if post.get("photo") else None
    if photo and photo.exists():
        return api("sendPhoto", {"chat_id": chat, "caption": text[:1024]}, photo)
    return api("sendMessage", {"chat_id": chat, "text": text, "disable_web_page_preview": True})


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    slot = current_slot(now)
    post = pick_post(now, slot)
    if post is None:
        print(f"Nessun post previsto alle {slot}:00 UTC.")
        return
    if "--dry-run" in sys.argv:
        print(json.dumps(post, ensure_ascii=False, indent=1))
        return
    chat = os.environ.get("CHAT_ID", "").strip()
    if not chat:
        sys.exit("CHAT_ID mancante: aggiungilo nei Secrets del repository.")
    send(chat, post)
    print("Pubblicato.")


if __name__ == "__main__":
    main()
