"""Pubblica i post di OrangeOrangus sul canale Telegram.

Campagna a traguardi (campaign.json): finché il canale non raggiunge "goal" membri,
4 post al giorno con barra di avanzamento, sondaggi, quiz e inviti a ripostare su X.
Ad ogni traguardo pubblica un annuncio (una sola volta, salvato in state.json).
Raggiunto il goal, torna ai 2 post al giorno di content.json.

Ogni post viene pubblicato anche su X se ci sono le chiavi X_* (altrimenti solo Telegram).

Variabili d'ambiente: BOT_TOKEN, CHAT_ID (es. @orangeorangus o -100...), SLOT (ora UTC, dal workflow).
Uso: python post.py            -> pubblica il post di questo orario
     python post.py --dry-run  -> mostra il post senza inviarlo (membri finti: 137)
"""
import base64, datetime, hashlib, hmac, json, os, sys, time, urllib.error, urllib.parse, urllib.request, uuid
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


def fill(text, count, c):
    goal = c["goal"]
    done = min(10, max(count * 10 // goal, 1 if count else 0))
    return text.format(count=count, goal=goal, left=max(goal - count, 0), m=count,
                       bar=f"{'🟧' * done}{'⬜' * (10 - done)} {count}/{goal}",
                       x=f"\n👉 {c['x_url']}" if c["x_url"] else "")


def pick_posts(now, slot, count, state):
    """Restituisce la lista di post da pubblicare in questo orario."""
    content, c = load("content.json"), load("campaign.json")
    footer = content["footer"]
    if c["active"] and c["goal"] not in state["announced"]:
        out = []
        new = [m for m in c["milestones"] if count >= m and m not in state["announced"]]
        if new:  # annuncia solo il traguardo più alto appena raggiunto
            m = max(new)
            text = c["goal_text"] if m == c["goal"] else c["milestone_text"].replace("{m}", str(m))
            out.append({"text": fill(text, count, c), "footer": footer})
            state["announced"] += new
        if not state.get("started"):  # primo avvio: spiega subito l'obiettivo
            state["started"] = True
            slot, i = "intro", 0
        if slot == "intro" or slot in CAMPAIGN_SLOTS and c["goal"] not in state["announced"]:
            i = 0 if slot == "intro" else (now.timetuple().tm_yday * len(CAMPAIGN_SLOTS) + CAMPAIGN_SLOTS.index(slot)) % len(c["posts"])
            post = dict(c["posts"][i], footer=footer)
            for k in ("text", "poll", "quiz"):
                if k in post:
                    post[k] = fill(post[k], count, c)
            out.append(post)
        return out
    if slot not in REGULAR_SLOTS:
        return []
    posts = content[DAYS[now.weekday()]][REGULAR_SLOTS[slot]]
    post = posts[now.isocalendar()[1] % len(posts)]  # ruota i post settimana dopo settimana
    return [dict(post, footer=footer)]


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


X_KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")
X_FOOTER = "🍊 Peel the hype. Release the ape.\nJoin the Troop on Telegram (link in bio)."


def x_post(post):
    """Pubblica su X (API v2, OAuth 1.0a). Link solo nel post di apertura: su X costano molto di più."""
    key, secret, token, token_secret = (os.environ[k].strip() for k in X_KEYS)
    if "poll" in post or "quiz" in post:
        body = {"text": post.get("poll") or post["quiz"],
                "poll": {"options": [o[:25] for o in post["options"]], "duration_minutes": 240}}
    elif post.get("raw"):
        body = {"text": post["text"]}
    else:
        body = {"text": (post["text"] + "\n\n" + X_FOOTER)[:280]}
    url = "https://api.x.com/2/tweets"
    oauth = {"oauth_consumer_key": key, "oauth_nonce": uuid.uuid4().hex, "oauth_signature_method": "HMAC-SHA1",
             "oauth_timestamp": str(int(time.time())), "oauth_token": token, "oauth_version": "1.0"}
    q = lambda v: urllib.parse.quote(v, safe="")
    params = "&".join(f"{q(k)}={q(v)}" for k, v in sorted(oauth.items()))
    base = f"POST&{q(url)}&{q(params)}"
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(f"{q(secret)}&{q(token_secret)}".encode(), base.encode(), hashlib.sha1).digest()).decode()
    auth = "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in oauth.items())
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Authorization": auth, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # X non blocca Telegram: segnala e continua
        print(f"Errore X {e.code}: {e.read().decode()}")


def update_counter(chat, count, state, c):
    """Messaggio contatore unico: creato una volta, poi modificato a ogni avvio con i membri reali."""
    text = fill(c["counter_text"] if count < c["goal"] else c["counter_done"], count, c)
    if state.get("counter_id"):
        token = os.environ["BOT_TOKEN"].strip().removeprefix("bot")
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/editMessageText",
                                     json.dumps({"chat_id": chat, "message_id": state["counter_id"], "text": text}).encode(),
                                     {"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req).close()
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if "not modified" not in body:  # stesso numero di prima: nessun errore
                print(f"Contatore non aggiornato: {body}")
        return
    msg = api("sendMessage", {"chat_id": chat, "text": text})["result"]
    state["counter_id"] = msg["message_id"]
    try:  # se il bot non ha il permesso di fissare, lo fissate voi a mano
        api_quiet = urllib.request.Request(
            f"https://api.telegram.org/bot{os.environ['BOT_TOKEN'].strip().removeprefix('bot')}/pinChatMessage",
            json.dumps({"chat_id": chat, "message_id": msg["message_id"], "disable_notification": True}).encode(),
            {"Content-Type": "application/json"})
        urllib.request.urlopen(api_quiet).close()
    except urllib.error.HTTPError as e:
        print(f"Contatore non fissato: {e.read().decode()}")


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    slot = current_slot(now)
    state = load("state.json")
    dry = "--dry-run" in sys.argv
    only_x = bool(os.environ.get("ONLY_X"))  # prova manuale solo su X
    x_on = all(os.environ.get(k, "").strip() for k in X_KEYS)
    chat = os.environ.get("CHAT_ID", "").strip()
    if not dry and not chat:
        sys.exit("CHAT_ID mancante: aggiungilo nei Secrets del repository.")
    count = 137 if dry else api("getChatMemberCount", {"chat_id": chat})["result"]
    if not dry and not only_x and load("campaign.json")["active"]:
        update_counter(chat, count, state, load("campaign.json"))
    if slot == "counter":  # avvio frequente: solo aggiornamento del contatore
        (ROOT / "state.json").write_text(json.dumps(state) + "\n")
        print(f"Membri: {count}. Contatore aggiornato.")
        return
    posts = None
    if x_on and not state.get("x_started"):  # primo post su X: invito al canale Telegram
        c = load("campaign.json")
        intro = {"text": fill(c["x_intro"], count, c), "raw": True}
        if dry:
            print(json.dumps(intro, ensure_ascii=False, indent=1))
        elif x_post(intro):
            state["x_started"] = True
        if only_x:
            posts = []
    if posts is None:  # in prova solo X lo stato dei traguardi non viene toccato
        posts = pick_posts(now, slot, count, json.loads(json.dumps(state)) if only_x else state)
    for post in posts:
        if dry:
            print(json.dumps(post, ensure_ascii=False, indent=1))
            continue
        if not only_x:
            send(chat, post)
        if x_on:
            x_post(post)
    if not dry:
        (ROOT / "state.json").write_text(json.dumps(state) + "\n")
    print(f"Membri: {count}. Post pubblicati: {len(posts)} (slot {slot}:00 UTC).")


if __name__ == "__main__":
    main()
