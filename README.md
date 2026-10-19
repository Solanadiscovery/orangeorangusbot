# OrangeOrangus Telegram bot

Pubblica 2 post al giorno, tutti i giorni (08:00 e 18:00 UTC), sul canale Telegram. Costo: €0 (GitHub Actions gratuito).

## Setup (una volta)
1. Su Telegram apri **@BotFather** → `/newbot` → copia il token.
2. Aggiungi il bot come **amministratore** del canale (permesso "Pubblica messaggi").
3. Crea un repository GitHub **privato** e carica questi file.
4. Nel repo: Settings → Secrets and variables → Actions → aggiungi
   - `BOT_TOKEN` = token di BotFather
   - `CHAT_ID` = `@nomecanale` (o l'ID numerico `-100...`)
5. Actions → "Daily Telegram post" → **Run workflow** per un test.

## Contenuti
- `content.json`: per ogni giorno c'è una lista `am` (mattina) e `pm` (sera). Aggiungi più post a una lista e il bot li alterna settimana dopo settimana.
- `images/`: metti qui le immagini dei meme con i nomi usati in `content.json`. Se manca l'immagine, il bot invia solo il testo.
- Orario: modifica `cron` in `.github/workflows/daily-post.yml` (in UTC).

## Sicurezza
Non condividere mai il token e non scriverlo nei file. Se esce, rigeneralo con `/revoke` su BotFather.
Il bot non pubblica link: aggiungi link ufficiali solo dopo averli verificati.
