/* Converts a private key exported from Phantom (base58 text) into bot-wallet.json for the bot.
 * Usage: node import-key.js   then paste the key and press Enter. The key is only written to this folder. */
'use strict';
const fs = require('fs'), path = require('path'), rl = require('readline').createInterface({ input: process.stdin, output: process.stdout });
const A = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function b58(s) {
  let n = 0n; for (const c of s) { const i = A.indexOf(c); if (i < 0) throw new Error('Invalid character in key'); n = n * 58n + BigInt(i); }
  const out = []; while (n > 0n) { out.unshift(Number(n & 255n)); n >>= 8n; }
  for (const c of s) { if (c !== '1') break; out.unshift(0); }
  return out;
}
rl.question('Paste the bot wallet private key (from Phantom): ', k => {
  rl.close();
  const bytes = b58(k.trim());
  if (bytes.length !== 64) { console.error('This is not a Solana private key (expected 64 bytes, got ' + bytes.length + ')'); process.exit(1); }
  const W = require('@solana/web3.js');
  const kp = W.Keypair.fromSecretKey(Uint8Array.from(bytes));
  const out = path.join(__dirname, 'bot-wallet.json');
  fs.writeFileSync(out, JSON.stringify(bytes));
  console.log('Saved ' + out + '\nBot address: ' + kp.publicKey.toBase58() + '\nNever share this file.');
});
