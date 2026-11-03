// Builds instructions with staking-core.js for pubkeys given by the Rust test; prints JSON.
const W = require('@solana/web3.js');
const C = require('../app/staking-core.js')(W);
const a = JSON.parse(process.argv[2]); const P = k => new W.PublicKey(a[k]);
const admin = P('admin'), user = P('user'), mint = P('mint');
const out = {
  create_mint: C.createMint(admin, mint, 6, Number(a.rent)),
  atas: [C.createAtaIdempotent(admin, admin, mint), C.createAtaIdempotent(admin, user, mint)],
  mint_admin: [C.mintTo(mint, C.ata(admin, mint), admin, C.toUnits('1000000', 6))],
  mint_user: [C.mintTo(mint, C.ata(user, mint), admin, C.toUnits('500', 6))],
  initialize: [C.initialize(admin, mint, mint, 60)],
  unpause: [C.setPaused(admin, mint, false)],
  pause: [C.setPaused(admin, mint, true)],
  fund: [C.fundRewards(admin, mint, mint, C.toUnits('1000', 6), 1000)],
  stake: [C.stake(user, mint, C.toUnits('100', 6))],
  claim: [C.claim(user, mint, mint)],
  unstake: [C.unstake(user, mint, C.toUnits('40', 6))],
  emergency: [C.emergencyWithdraw(user, mint)],
  addr: { config: C.pdas(mint).config.toBase58(), stake_vault: C.pdas(mint).stakeVault.toBase58(),
          user_pda: C.userPda(C.pdas(mint).config, user).toBase58(), user_ata: C.ata(user, mint).toBase58() }
};
const ser = i => ({ program: i.programId.toBase58(), data: Array.from(i.data), keys: i.keys.map(k => [k.pubkey.toBase58(), k.isSigner, k.isWritable]) });
for (const k of Object.keys(out)) if (Array.isArray(out[k])) out[k] = out[k].map(ser);
console.log(JSON.stringify(out));
