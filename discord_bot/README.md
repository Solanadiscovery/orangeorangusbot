# Bot Discord OrangeOrangus

Segue la guida `guida-server-discord.md`:
- **Ruolo automatico**: chi entra riceve **OranguTeam**.
- **Moderazione** (staff escluso, log in #mod-log):
  - frasi truffa (`scam_patterns`) → messaggio eliminato
  - link nella categoria COMMUNITY (eccetto `allowed_domains`) → eliminato
  - 5+ menzioni, 70%+ maiuscole, 3 messaggi uguali, 5 messaggi in 5 secondi → eliminato + timeout 10 minuti
- **/setup** (solo admin): crea ruoli, categorie, canali, slowmode (5s #chat-generale, 30s #meme), testo #regole, verifica Alta; toglie a @everyone "Menziona @everyone" e "Crea inviti". Si può rilanciare: non duplica nulla.

Tutto si modifica in `config.json`. Aggiungi i domini ufficiali ad `allowed_domains` solo dopo averli verificati.

## Attivazione
1. https://discord.com/developers/applications → New Application → **Bot** → Reset Token (copialo, non condividerlo mai).
2. Sempre in Bot: attiva **Server Members Intent** e **Message Content Intent**.
3. OAuth2 → URL Generator: scope `bot` + `applications.commands`, permesso **Administrator** → apri il link e aggiungi il bot al server.
4. Avvio: `pip install -r discord_bot/requirements.txt` poi `DISCORD_TOKEN=xxx python discord_bot/bot.py`
5. Nel server scrivi `/setup`. Poi in Impostazioni → Ruoli controlla che il ruolo del bot stia **sopra** OranguTeam.

Da fare a mano (il bot non può): abilitare Community, filtro spam DM, protezione raid/CAPTCHA, 2FA obbligatoria per i moderatori.

## Hosting 24/7
Il bot deve restare sempre acceso (GitHub Actions non va bene). Opzioni: un PC sempre acceso (€0), Oracle Cloud Always Free (€0, chiede una carta per la verifica) oppure un piccolo VPS (circa €4-5/mese).

Test: `python -m unittest discover tests`
