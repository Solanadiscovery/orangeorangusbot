#!/usr/bin/env bash
# Uso: bash staking-localnet/start.sh TUO_INDIRIZZO_PHANTOM
set -e
ADDR="$1"; [ -z "$ADDR" ] && { echo "Uso: bash staking-localnet/start.sh TUO_INDIRIZZO_PHANTOM"; exit 1; }
cd "$(dirname "$0")"
PROGRAM=FJCVCn2714BjcYCBKoqL2v6kQvfYPoHtLghnEPeHRm79
solana-test-validator --reset --quiet --ledger /tmp/test-ledger \
  --upgradeable-program $PROGRAM deploy/orange_stake.so "$ADDR" > /tmp/validator.out 2>&1 &
echo "Avvio validator..."
for i in $(seq 1 60); do solana cluster-version --url localhost >/dev/null 2>&1 && break; sleep 2; done
solana airdrop 100 "$ADDR" --url localhost
echo "Per altri SOL (anche ad altri wallet): solana airdrop 100 INDIRIZZO --url localhost"
node server.js
