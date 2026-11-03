# Bot premi $ORANGU

Ogni ciclo il bot:
1. riscuote le **creator fees** di pump.fun (in SOL) nel wallet del bot;
2. (opzionale) manda `treasurySharePct` % dei SOL alla Orange Treasury;
3. con i SOL rimasti sopra la riserva **ricompra $ORANGU** (Jupiter, oppure pump.fun se il token non è ancora "graduato");
4. manda la quota eventi (`eventsSharePct`, es. 20%) dei token **appena comprati** al wallet eventi;
5. carica il resto nel **pool dello staking**, distribuito agli staker in modo continuo per `rewardDays` giorni.

Muove solo i token comprati da lui: qualsiasi altro token nel wallet non viene mai toccato.
Nel programma di staking il bot ha il ruolo "solo ricarica": può solo aggiungere premi, non può mettere in pausa, cambiare regole, riprendersi premi o toccare gli stake.
Ogni operazione viene scritta in `bot-log.jsonl` con la firma della transazione, verificabile su Solscan.

I 3 wallet: **Orange Stake Club** = wallet del bot (l'unico di cui il bot ha la chiave) · **Orange Rewards Treasury** = `eventsWallet` · **Orange Treasury** = `treasuryWallet`. Gli ultimi due il bot li conosce solo per indirizzo: può mandarci fondi, mai prelevarli.

## Setup (una volta)

1. **Wallet dedicato**: in Phantom crea un nuovo account usato **solo** per il token. Lancia $ORANGU su pump.fun **da quell'account**, così le creator fees arrivano lì. Non usarlo per altro e non tenerci i token del team.
2. Installa **Node.js 18 o più recente** (nodejs.org). In PowerShell, nella cartella `bot`:
   ```
   npm install
   ```
3. Esporta la chiave privata di quell'account da Phantom (Impostazioni → account → Mostra chiave privata) e salvala per il bot:
   ```
   node import-key.js
   ```
   Crea `bot-wallet.json`. **Non condividere mai questo file** e non caricarlo online.
4. Copia `config.example.json` in `config.json` e compila:
   - `mint`: indirizzo del token $ORANGU
   - `eventsWallet`: wallet eventi (vuoto = 100% allo staking)
   - `eventsSharePct`: % per eventi
   - `treasuryWallet` / `treasurySharePct`: Orange Treasury e % in SOL (vuoto o 0 = niente)
   - `rewardDays`: su quanti giorni spalmare ogni ricarica (7 = flusso regolare)
   - `rpcUrl`: va bene quello pubblico; per più affidabilità un RPC gratuito (Helius, QuickNode)
5. Nella pagina admin dello staking, sezione **6 · Reward bot**, incolla l'indirizzo del bot e conferma con il tuo Phantom admin.
6. Lascia nel wallet del bot circa 0,05 SOL per le commissioni di rete (`solReserve`).

## Avvio

Prova (non invia nulla, `"dryRun": true`):
```
node reward-bot.js
```
Quando l'output è corretto metti `"dryRun": false` in `config.json` e avvia:
```
node reward-bot.js --loop
```
Gira ogni `intervalMinutes` minuti finché la finestra resta aperta. Per farlo girare sempre, usa un PC acceso o un piccolo server (VPS), oppure l'Utilità di pianificazione di Windows con `node reward-bot.js` ogni ora.

## Limiti
- `maxSolPerRun` limita quanto compra per ciclo, per non muovere troppo il prezzo.
- Se un caricamento fallisce, i token comprati vengono ritentati al ciclo dopo (`bot-state.json`).
- I premi dipendono solo dalle fee effettivamente generate: nessun rendimento è garantito.
