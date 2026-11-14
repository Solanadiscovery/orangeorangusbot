# OrangeOrangus bot (Telegram)

Un solo processo sempre attivo (workflow **Live bot**) che ogni minuto:
1. legge i comandi dell'admin;
2. aggiorna il **countdown fissato** modificando sempre lo stesso messaggio (mai uno nuovo);
3. pubblica i contenuti programmati su Telegram, **senza mai ripetere** un contenuto già usato, e il promemoria giornaliero Orange Racing.

La pubblicazione automatica su X è stata rimossa: `content/x.json` resta solo come archivio (il modulo `xapi.py` è recuperabile dalla storia git).

Si riavvia da solo ogni ~5h40 (più un riavvio di riserva ogni 5 ore). Costo: €0 su GitHub (repo pubblico).

## File
| File | Cosa contiene |
|---|---|
| `config.json` | fuso orario, orari, rotazione dei formati, countdown, soglia di somiglianza |
| `content/telegram.json`, `content/x.json` | contenuti (quiz, meme, sondaggi, ecc.), separati per piattaforma |
| `history.json` | tutto ciò che è stato pubblicato (testo, tipo, concetto, data) |
| `members.json` | numero membri Telegram pubblico, letto dal sito web (aggiornato solo quando cambia) |
| `state.json` | ID del messaggio countdown, slot pubblicati, traguardi, pausa/anteprima |
| `bot.py` | ciclo principale; `groupfilters.py` (filtri/regole), `antiraid.py` (anti-raid), `tg.py`, `content.py`, `countdown.py` moduli |
| `tests/` | test offline (`python -m unittest discover tests`), eseguiti a ogni avvio |

## Secrets (Settings → Secrets → Actions)
`BOT_TOKEN`, `CHAT_ID`, `ADMIN_USER_ID` (il tuo ID Telegram numerico, da @userinfobot). I secret `X_*` non sono più usati dal bot.

## Comandi admin (scrivi al bot in privato)
`/status` stato e contenuti rimasti · `/pause` `/resume` pubblicazioni · `/preview_on` `/preview_off` i post arrivano solo a te · `/next` prossimi contenuti.
Il bot avvisa l'admin se il countdown non si trova, se una pubblicazione fallisce o se i contenuti stanno finendo.

## Filtri e regole del gruppo (come Rose)
Nel gruppo, gli admin scrivono `/filter parola testo` (la parola può essere anche un comando, es. `/filter /ac testo`; oppure `/filter "due parole" testo`, anche rispondendo a un messaggio), `/filters` per l'elenco, `/stop parola` per eliminarlo, `/setrules testo` per le regole. Chiunque può usare `/rules`. Quando un membro scrive la parola, il bot risponde (una volta ogni 10 minuti per parola, ogni 20 secondi per i /comandi). I filtri sono in `state.json`. Il bot deve vedere i messaggi del gruppo: sia admin del gruppo oppure disattiva il Privacy mode in BotFather.

Antiflood: chi invia più di 6 messaggi in 10 secondi viene silenziato per 10 minuti (gli admin sono esclusi). Si regola in `config.json` → `antiflood`; il bot deve essere admin del gruppo con il permesso di limitare i membri. `/x`, `/demo`, `/tlg`, `/discord`, `/web` e `/social` (tutti i link) sono filtri già pronti; `/roadmap` invia il PDF in `assets/` (file e didascalia in `config.json` → `group_documents`).

## Anti-raid (come Rose)
Comandi per gli admin del gruppo: `/antiraid` (attiva/disattiva) · `/antiraid 2h` · `/antiraid off` bannano per un po' chi entra (ban temporaneo, `/raidactiontime 1h`; durata standard `/raidtime 6h`) · `/autoantiraid 10` lo attiva da solo se entrano 10 persone in un minuto (di base è spento, per non fermare gli ingressi veri) · `/lock all` / `/unlock all` blocca e riapre la chat · `/lock links` / `/unlock links` cancella i link dei non admin · `/locks` mostra lo stato. Il bot deve essere admin con "Bannare utenti", "Eliminare messaggi" e "Modificare info gruppo". Codice in `antiraid.py`.

## Programma giornaliero (Telegram, ora di Roma)
| Ora | Post |
|---|---|
| 10:00 | quiz |
| 14:00 | meme |
| 18:00 | promemoria Orange Racing (foto + pulsante) |
| 22:00 | engage |

Il tipo di ogni orario è fisso (`telegram.slot_types`); se i contenuti di quel tipo finiscono si usa la rotazione normale. Il sondaggio giornaliero è spento (`telegram.poll_times` vuoto) e Peel Friday è disattivato (`telegram.friday.enabled: false`): per riattivarli basta rimettere un orario o `true`. Ogni post di testo finisce con il link a X (`telegram.footer`). Tutti i contenuti pubblici sono in inglese.

## Promemoria giornaliero Orange Racing
Sezione `daily_reward` di `config.json`: una volta al giorno (default 18:00 Europe/Rome) il bot invia nel gruppo la foto `assets/daily-reward.png` con didascalia a rotazione (6 varianti) e il pulsante verso https://orangeracing.duckdns.org. Se l'immagine manca invia solo testo e pulsante. Il giorno è salvato in `state.json` **prima** dell'invio, quindi mai due promemoria nello stesso giorno, anche dopo un riavvio; se il bot era fermo all'orario recupera entro `catch_up_hours` (3). Rispetta `/pause` e `/preview_on`. Prova: scrivi `/reward_test` al bot in privato (arriva solo a te).

## Anti-ripetizione
Prima di pubblicare, ogni contenuto è confrontato con tutto lo storico (entrambe le piattaforme):
stesso ID o stesso concetto → scartato; testo identico dopo normalizzazione → scartato;
somiglianza (sequenza o parole in comune) ≥ `similarity_threshold` → scartato. Lo slot viene salvato **prima** dell'invio, quindi un riavvio non crea doppioni.

## Countdown
`countdown.mode`: `members` (membri reali fino a `goal`) oppure `time` (tempo fino a `target`, data assoluta con fuso, es. `2026-11-01T20:00:00+01:00`).
Si aggiorna ogni minuto (limiti Telegram), solo se il testo cambia. Se il messaggio sparisce il bot **non** ne crea un altro: avvisa l'admin.
Il bot non annuncia mai da solo un lancio: a fine countdown mostra solo il testo di completamento.

## Aggiungere contenuti
Aggiungi elementi a `content/*.json` con `id` e `concept` unici. Tipi Telegram: `quiz`, `poll`, `meme`, `engage`.

## Peel Points (punti della community)

Modulo `points.py`, **chiuso di default**: gli utenti non ricevono risposte finché l'admin non scrive al bot in privato `/points_on` (annuncia una sola volta nel gruppo e apre). `/points_off` richiude, `/points_stats` mostra i numeri.

Comandi utente (in chat privata con il bot): `/start`, `/missions`, `/points`, `/badges`, `/rank`, `/checkin`, `/x @handle`, `/post <link>`, `/invite`, `/rules`.

- Join Telegram +10 (verificato con getChatMember), check-in +5, post su X +20 (una volta al giorno), invito +30 (max 10).
- Post su X: verifica con oEmbed pubblico (autore = account collegato, testo con #OrangeOrangus o $ORANGU, data dall'id del post, link mai usato prima). Se X non risponde il post attende l'admin con pulsanti Approva/Rifiuta. Un campione (1 su 5) dei post approvati arriva comunque all'admin con "Revoca": revoca = punti tolti e 1 avviso, 2 avvisi = escluso.
- Inviti: link personale; i punti arrivano dopo 24 ore se l'amico è ancora nel gruppo. Richiede che il bot sia admin del gruppo con il permesso di invitare (e di vedere i cambi di membri).
- Tetto 100 punti al giorno (gli inviti hanno il limite proprio). Dati in `points.json`. Gli errori dei punti non fermano countdown e post. Impostazioni e testo dell'annuncio in `config.json` → `points`.
- I punti non hanno valore economico e non promettono nulla: il testo lo ripete.
- Livelli (soglie in `config.json` → `points.levels`): 🌱 Seedling 0, 🍊 Peeler 50, 🧗 Climber 150, 🦧 Troop Elite 400, 👑 OG Legend 1000. Badge: First Peel, On Fire (streak 3 giorni), Unstoppable (7), X Voice (1 post), Megaphone (5), Recruiter (3 amici), Pack Leader (10). Solo status: nessun valore economico.
