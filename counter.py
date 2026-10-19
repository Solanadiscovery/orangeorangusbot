"""Tiene aggiornato il contatore live: controlla i membri ogni minuto e modifica il messaggio
solo quando il numero cambia (in su o in giù). Gira per ~5,5 ore, poi il workflow lo riavvia."""
import os, time
import post

DURATION = 5 * 3600 + 30 * 60
chat = os.environ["CHAT_ID"].strip()
end, last = time.time() + DURATION, None
while time.time() < end:
    try:
        c, state = post.load("campaign.json"), post.load("state.json")
        count = post.api("getChatMemberCount", {"chat_id": chat})["result"]
        if count != last and c["active"] and state.get("counter_id"):
            post.update_counter(chat, count, state, c)
            print(f"Membri: {count}", flush=True)
            last = count
    except (Exception, SystemExit) as e:  # un errore temporaneo non ferma il contatore
        print(f"Errore: {e}", flush=True)
    time.sleep(60)
