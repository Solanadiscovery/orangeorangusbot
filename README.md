# OrangeOrangus bot (Telegram + X)

Un solo processo sempre attivo (workflow **Live bot**) che ogni minuto:
1. legge i comandi dell'admin;
2. aggiorna il **countdown fissato** modificando sempre lo stesso messaggio (mai uno nuovo);
3. pubblica i contenuti programmati su Telegram e su X, **senza mai ripetere** un contenuto già usato.

Si riavvia da solo ogni ~5h40 (più un riavvio di riserva ogni 5 ore). Costo: €0 su GitHub (repo pubblico), X a consumo.

## File
| File | Cosa contiene |
|---|---|
| `config.json` | fuso orario, orari, rotazione dei formati, countdown, soglia di somiglianza |
| `content/telegram.json`, `content/x.json` | contenuti (quiz, meme, sondaggi, ecc.), separati per piattaforma |
| `history.json` | tutto ciò che è stato pubblicato (testo, tipo, concetto, data) |
| `state.json` | ID del messaggio countdown, slot pubblicati, traguardi, pausa/anteprima |
| `bot.py` | ciclo principale; `tg.py`, `xapi.py`, `content.py`, `countdown.py` moduli |
| `tests/` | test offline (`python -m unittest discover tests`), eseguiti a ogni avvio |

## Secrets (Settings → Secrets → Actions)
`BOT_TOKEN`, `CHAT_ID`, `ADMIN_USER_ID` (il tuo ID Telegram numerico, da @userinfobot), `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`.

## Comandi admin (scrivi al bot in privato)
`/status` stato e contenuti rimasti · `/pause` `/resume` pubblicazioni · `/preview_on` `/preview_off` i post arrivano solo a te · `/next` prossimi contenuti.
Il bot avvisa l'admin se il countdown non si trova, se una pubblicazione fallisce o se i contenuti stanno finendo.

## Anti-ripetizione
Prima di pubblicare, ogni contenuto è confrontato con tutto lo storico (entrambe le piattaforme):
stesso ID o stesso concetto → scartato; testo identico dopo normalizzazione → scartato;
somiglianza (sequenza o parole in comune) ≥ `similarity_threshold` → scartato. Lo slot viene salvato **prima** dell'invio, quindi un riavvio non crea doppioni.

## Countdown
`countdown.mode`: `members` (membri reali fino a `goal`) oppure `time` (tempo fino a `target`, data assoluta con fuso, es. `2026-11-01T20:00:00+01:00`).
Si aggiorna ogni minuto (limiti Telegram), solo se il testo cambia. Se il messaggio sparisce il bot **non** ne crea un altro: avvisa l'admin.
Il bot non annuncia mai da solo un lancio: a fine countdown mostra solo il testo di completamento.

## Aggiungere contenuti
Aggiungi elementi a `content/*.json` con `id` e `concept` unici. Tipi Telegram: `quiz`, `poll`, `meme`, `engage`. Tipi X: `meme`, `community`, `question`, `teaser`, `challenge`, `poll`, `culture`.
