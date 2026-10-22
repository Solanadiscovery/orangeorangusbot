# Bot Discord OrangeOrangus

Segue la guida `guida-server-discord.md`:
- **Ruolo automatico**: chi entra riceve **OranguTeam**.
- **Benvenuto**: a ogni nuovo membro il bot scrive in #welcome (`welcome_message`).
- **OG**: solo i primi 500 membri (in ordine di ingresso, bot esclusi). Gli assegnati sono salvati in `og_members.json`: non cancellarlo, così un posto non viene mai riassegnato.
- **Moderazione** (staff escluso, log in #mod-log; server e messaggi del bot in inglese):
  - frasi truffa (`scam_patterns`) → messaggio eliminato
  - link nella categoria COMMUNITY (eccetto `allowed_domains`) → eliminato
  - 5+ menzioni, 70%+ maiuscole, 3 messaggi uguali, 5 messaggi in 5 secondi → eliminato + timeout 10 minuti
- **/x /tlg /ds /demo**: chiunque, in qualsiasi canale, riceve il link (X, Telegram, invito Discord creato dal bot, demo). Testi in `link_commands`.
- **/setup** (solo admin): crea ruoli, categorie, canali, slowmode (5s #general-chat, 30s #memes), PDF della roadmap in #roadmap (sola lettura), messaggi in #welcome, #rules, #official-links e #scam-alerts (`channel_posts` in config.json), verifica Alta; toglie a @everyone "Menziona @everyone" e "Crea inviti". Si può rilanciare: non duplica nulla.

Tutto si modifica in `config.json`. Aggiungi i domini ufficiali ad `allowed_domains` solo dopo averli verificati.

## Attivazione
1. https://discord.com/developers/applications → New Application → **Bot** → Reset Token (copialo, non condividerlo mai).
2. Sempre in Bot: attiva **Server Members Intent** e **Message Content Intent**.
3. OAuth2 → URL Generator: scope `bot` + `applications.commands`, permesso **Administrator** → apri il link e aggiungi il bot al server.
4. Avvio su Windows: doppio clic su `avvia-bot.bat`. La prima volta chiede il token e lo salva in `token.txt` (resta solo sul tuo PC, non condividerlo). Altrimenti: `DISCORD_TOKEN=xxx python discord_bot/bot.py`
5. Nel server scrivi `/setup` (oppure `!setup`). Poi in Impostazioni → Ruoli controlla che il ruolo del bot stia **sopra** OranguTeam.

Da fare a mano (il bot non può): abilitare Community, filtro spam DM, protezione raid/CAPTCHA, 2FA obbligatoria per i moderatori.

## Hosting 24/7
Il bot deve restare sempre acceso (GitHub Actions non va bene). Opzioni: un PC sempre acceso (€0), Oracle Cloud Always Free (€0, chiede una carta per la verifica) oppure un piccolo VPS (circa €4-5/mese).

Test: `python -m unittest discover tests`
