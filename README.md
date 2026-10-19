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

## X (opzionale)
Se aggiungi nei Secrets `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`, ogni post esce anche su X.
Chiavi da https://developer.x.com → app con permessi "Read and write" → Keys and tokens (genera Access Token dopo aver impostato i permessi).
X API è a pagamento a consumo: ricarica pochi crediti. Il bot non pubblica link su X (costano molto di più).

## Contatore live
Il bot crea un messaggio "LIVE TROOP COUNTDOWN" e il workflow "Live member counter" lo aggiorna ogni minuto con i membri reali, anche quando qualcuno esce.
Avvio manuale da Actions = aggiorna subito il contatore. Con "Pubblica solo su X" = prova su X.

## Come gira il bot
Il workflow "Live bot" resta sempre acceso (si riavvia da solo ogni ~5h40): pubblica i post agli orari previsti
(08, 12, 16, 18, 20 UTC) e aggiorna il contatore ogni minuto. "Daily Telegram post" ora serve solo per avvii manuali.
