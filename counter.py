"""Processo sempre attivo del bot (GitHub Actions avvia gli orari programmati con forte ritardo).

Ogni minuto:
- aggiorna il contatore live se il numero di membri cambia (in su o in giù);
- negli orari dei post (ore UTC in SLOTS, primi 30 minuti) pubblica il post una sola volta.
Dopo ~5h40 avvia da solo il proprio successore, così non si ferma mai."""
import datetime, json, os, subprocess, time, urllib.request
import post

SLOTS = ["08", "12", "16", "18", "20"]
DURATION = 5 * 3600 + 40 * 60
chat = os.environ["CHAT_ID"].strip()
end, last = time.time() + DURATION, None


def git(*args):
    subprocess.run(["git", *args], check=False)


def save_state(msg):
    git("config", "user.name", "orangeorangus-bot")
    git("config", "user.email", "bot@users.noreply.github.com")
    git("commit", "-qm", msg, "state.json")
    git("pull", "-q", "--rebase", "origin", "main")
    git("push", "-q", "origin", "HEAD:main")


def restart_self():
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/workflows/live-counter.yml/dispatches",
        json.dumps({"ref": "main"}).encode(),
        {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    urllib.request.urlopen(req).close()


while time.time() < end:
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        c, state = post.load("campaign.json"), post.load("state.json")
        count = post.api("getChatMemberCount", {"chat_id": chat})["result"]
        if count != last and c["active"] and state.get("counter_id"):
            post.update_counter(chat, count, state, c)
            print(f"Membri: {count}", flush=True)
            last = count
        key = now.strftime("%Y-%m-%dT%H")
        if f"{now.hour:02d}" in SLOTS and now.minute < 30 and state.get("last_post") != key:
            os.environ["SLOT"] = f"{now.hour:02d}"
            post.main()  # pubblica e salva state.json
            state = post.load("state.json")
            state["last_post"] = key
            (post.ROOT / "state.json").write_text(json.dumps(state) + "\n")
            save_state(f"Post {key}")
    except (Exception, SystemExit) as e:  # un errore temporaneo non ferma il bot
        print(f"Errore: {e}", flush=True)
    time.sleep(60)

restart_self()
