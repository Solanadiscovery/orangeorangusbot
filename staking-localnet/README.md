# Staking su localnet in GitHub Codespaces

1. Su GitHub: Code → Codespaces → `...` → **New with options** → Branch `claude/project-thread-jan3v5`, Dev container **Orange Stake - localnet** → Create.
2. Attendi la fine dell'installazione (2-4 minuti), poi nel terminale:
   ```
   bash staking-localnet/start.sh TUO_INDIRIZZO_PHANTOM
   ```
3. Scheda **Porte** → porta 3000 → apri il link e aggiungi `?rpc=proxy` alla fine.
4. Collega Phantom. La pagina invia le transazioni al validator, Phantom firma soltanto (se mostra un avviso di simulazione, conferma: SOL finti).

Ricorda di fermare il Codespace a fine test (consuma le 60 ore gratuite al mese).
