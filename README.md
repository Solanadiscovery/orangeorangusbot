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
| `members.json` | numero membri Telegram pubblico, letto dal sito web (aggiornato solo quando cambia) |
| `state.json` | ID del messaggio countdown, slot pubblicati, traguardi, pausa/anteprima |
| `bot.py` | ciclo principale; `groupfilters.py` (filtri/regole), `tg.py`, `xapi.py`, `content.py`, `countdown.py` moduli |
| `tests/` | test offline (`python -m unittest discover tests`), eseguiti a ogni avvio |

## Secrets (Settings → Secrets → Actions)
`BOT_TOKEN`, `CHAT_ID`, `ADMIN_USER_ID` (il tuo ID Telegram numerico, da @userinfobot), `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`.

## Comandi admin (scrivi al bot in privato)
`/status` stato e contenuti rimasti · `/pause` `/resume` pubblicazioni · `/preview_on` `/preview_off` i post arrivano solo a te · `/next` prossimi contenuti.
Il bot avvisa l'admin se il countdown non si trova, se una pubblicazione fallisce o se i contenuti stanno finendo.

## Filtri e regole del gruppo (come Rose)
Nel gruppo, gli admin scrivono `/filter parola testo` (la parola può essere anche un comando, es. `/filter /ac testo`; oppure `/filter "due parole" testo`, anche rispondendo a un messaggio), `/filters` per l'elenco, `/stop parola` per eliminarlo, `/setrules testo` per le regole. Chiunque può usare `/rules`. Quando un membro scrive la parola, il bot risponde (una volta ogni 10 minuti per parola, ogni 20 secondi per i /comandi). I filtri sono in `state.json`. Il bot deve vedere i messaggi del gruppo: sia admin del gruppo oppure disattiva il Privacy mode in BotFather.

Antiflood: chi invia più di 6 messaggi in 10 secondi viene silenziato per 10 minuti (gli admin sono esclusi). Si regola in `config.json` → `antiflood`; il bot deve essere admin del gruppo con il permesso di limitare i membri. `/x`, `/demo`, `/tlg`, `/discord` e `/social` (tutti i link) sono filtri già pronti; `/roadmap` invia il PDF in `assets/` (file e didascalia in `config.json` → `group_documents`).

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

## Peel Points (punti della community)

Modulo `points.py`, **chiuso di default**: gli utenti non ricevono risposte finché l'admin non scrive al bot in privato `/points_on` (annuncia una sola volta nel gruppo e apre). `/points_off` richiude, `/points_stats` mostra i numeri.

Comandi utente (in chat privata con il bot): `/start`, `/missions`, `/points`, `/badges`, `/rank`, `/checkin`, `/x @handle`, `/post <link>`, `/invite`, `/rules`.

- Join Telegram +10 (verificato con getChatMember), check-in +5, post su X +20 (una volta al giorno), invito +30 (max 10).
- Post su X: verifica con oEmbed pubblico (autore = account collegato, testo con #OrangeOrangus o $ORANGU, data dall'id del post, link mai usato prima). Se X non risponde il post attende l'admin con pulsanti Approva/Rifiuta. Un campione (1 su 5) dei post approvati arriva comunque all'admin con "Revoca": revoca = punti tolti e 1 avviso, 2 avvisi = escluso.
- Inviti: link personale; i punti arrivano dopo 24 ore se l'amico è ancora nel gruppo. Richiede che il bot sia admin del gruppo con il permesso di invitare (e di vedere i cambi di membri).
- Tetto 100 punti al giorno (gli inviti hanno il limite proprio). Dati in `points.json`. Gli errori dei punti non fermano countdown e post. Impostazioni e testo dell'annuncio in `config.json` → `points`.
- I punti non hanno valore economico e non promettono nulla: il testo lo ripete.
- Livelli (soglie in `config.json` → `points.levels`): 🌱 Seedling 0, 🍊 Peeler 50, 🧗 Climber 150, 🦧 Troop Elite 400, 👑 OG Legend 1000. Badge: First Peel, On Fire (streak 3 giorni), Unstoppable (7), X Voice (1 post), Megaphone (5), Recruiter (3 amici), Pack Leader (10). Solo status: nessun valore economico.
