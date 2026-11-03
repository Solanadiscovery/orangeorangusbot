/* Orange Stake Club - client helpers for the DEVNET test page.
 * Pure functions: build instructions, derive addresses, decode accounts. No keys, no network calls.
 * Works in the browser (window.OrangeStakeCore, needs window.solanaWeb3) and in Node (module.exports). */
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) module.exports = factory;
  else root.OrangeStakeCore = factory(root.solanaWeb3);
})(typeof window !== 'undefined' ? window : globalThis, function (W) {
  'use strict';
  const { PublicKey, TransactionInstruction, SystemProgram, SYSVAR_RENT_PUBKEY } = W;

  const PROGRAM_ID = new PublicKey('FJCVCn2714BjcYCBKoqL2v6kQvfYPoHtLghnEPeHRm79');
  const SPL_TOKEN = new PublicKey('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA');
  const TOKEN_2022 = new PublicKey('TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb');
  let TOKEN_PROGRAM = SPL_TOKEN;
  // pump.fun and other launchpads may create Token-2022 mints: pass the mint account's owner here.
  function useTokenProgram(owner) {
    if (!owner.equals(SPL_TOKEN) && !owner.equals(TOKEN_2022)) throw new Error('Not a token mint');
    const changed = !owner.equals(TOKEN_PROGRAM); TOKEN_PROGRAM = owner; return changed;
  }
  const ATA_PROGRAM = new PublicKey('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL');
  const UPGRADEABLE_LOADER = new PublicKey('BPFLoaderUpgradeab1e11111111111111111111111');
  const MINT_SIZE = 82;

  const D = {
    initialize: [175, 175, 109, 31, 13, 152, 155, 237],
    set_paused: [91, 60, 125, 192, 176, 225, 166, 218],
    set_funder: [13, 121, 13, 251, 79, 198, 48, 187],
    fund_rewards: [114, 64, 163, 112, 175, 167, 19, 121],
    stake: [206, 176, 202, 18, 200, 209, 179, 108],
    unstake: [90, 95, 107, 42, 205, 124, 50, 225],
    claim: [62, 198, 214, 193, 213, 159, 108, 210],
    emergency_withdraw: [239, 45, 203, 64, 150, 73, 218, 92],
    reclaim_rewards: [9, 218, 4, 147, 157, 24, 65, 179]
  };
  const ACC_CONFIG = [155, 12, 170, 224, 30, 250, 204, 130];
  const ACC_USER = [102, 53, 163, 107, 9, 138, 87, 153];
  const ACC_PRECISION = 1000000000000n;

  const enc = s => new TextEncoder().encode(s);
  const u64 = v => { const b = new Uint8Array(8); new DataView(b.buffer).setBigUint64(0, BigInt(v), true); return b; };
  const i64 = v => { const b = new Uint8Array(8); new DataView(b.buffer).setBigInt64(0, BigInt(v), true); return b; };
  const cat = (...a) => { const n = a.reduce((s, x) => s + x.length, 0), o = new Uint8Array(n); let p = 0; for (const x of a) { o.set(x, p); p += x.length; } return o; };
  const buf = u => (typeof Buffer !== 'undefined' ? Buffer.from(u) : u);
  const m = (pubkey, isSigner, isWritable) => ({ pubkey, isSigner, isWritable });
  const ix = (data, keys) => new TransactionInstruction({ programId: PROGRAM_ID, keys, data: buf(data) });

  // ---------- addresses
  function pdas(stakeMint) {
    const config = PublicKey.findProgramAddressSync([enc('config'), stakeMint.toBytes()], PROGRAM_ID)[0];
    return {
      config,
      stakeVault: PublicKey.findProgramAddressSync([enc('stake_vault'), config.toBytes()], PROGRAM_ID)[0],
      rewardVault: PublicKey.findProgramAddressSync([enc('reward_vault'), config.toBytes()], PROGRAM_ID)[0],
      programData: PublicKey.findProgramAddressSync([PROGRAM_ID.toBytes()], UPGRADEABLE_LOADER)[0]
    };
  }
  const userPda = (config, owner) => PublicKey.findProgramAddressSync([enc('user'), config.toBytes(), owner.toBytes()], PROGRAM_ID)[0];
  const ata = (owner, mint) => PublicKey.findProgramAddressSync([owner.toBytes(), TOKEN_PROGRAM.toBytes(), mint.toBytes()], ATA_PROGRAM)[0];

  // ---------- program instructions
  function initialize(admin, stakeMint, rewardMint, minLockSecs) {
    const p = pdas(stakeMint);
    return ix(cat(D.initialize, i64(minLockSecs)), [
      m(admin, true, true), m(p.config, false, true), m(stakeMint, false, false), m(rewardMint, false, false),
      m(p.stakeVault, false, true), m(p.rewardVault, false, true), m(TOKEN_PROGRAM, false, false),
      m(SystemProgram.programId, false, false), m(PROGRAM_ID, false, false), m(p.programData, false, false)]);
  }
  const setFunder = (admin, stakeMint, funder) =>
    ix(cat(D.set_funder, funder.toBytes()), [m(admin, true, false), m(pdas(stakeMint).config, false, true)]);
  const setPaused = (admin, stakeMint, paused) =>
    ix(cat(D.set_paused, [paused ? 1 : 0]), [m(admin, true, false), m(pdas(stakeMint).config, false, true)]);
  function fundRewards(admin, stakeMint, rewardMint, amount, durationSecs) {
    const p = pdas(stakeMint);
    return ix(cat(D.fund_rewards, u64(amount), i64(durationSecs)), [
      m(admin, true, false), m(p.config, false, true), m(rewardMint, false, false), m(p.rewardVault, false, true),
      m(ata(admin, rewardMint), false, true), m(TOKEN_PROGRAM, false, false)]);
  }
  function stake(owner, stakeMint, amount) {
    const p = pdas(stakeMint);
    return ix(cat(D.stake, u64(amount)), [
      m(owner, true, true), m(p.config, false, true), m(userPda(p.config, owner), false, true), m(stakeMint, false, false),
      m(p.stakeVault, false, true), m(ata(owner, stakeMint), false, true), m(TOKEN_PROGRAM, false, false),
      m(SystemProgram.programId, false, false)]);
  }
  function unstakeLike(name, owner, stakeMint, amount) {
    const p = pdas(stakeMint);
    const data = amount === undefined ? cat(D[name]) : cat(D[name], u64(amount));
    return ix(data, [
      m(owner, true, false), m(p.config, false, true), m(userPda(p.config, owner), false, true), m(stakeMint, false, false),
      m(p.stakeVault, false, true), m(ata(owner, stakeMint), false, true), m(TOKEN_PROGRAM, false, false)]);
  }
  const unstake = (owner, stakeMint, amount) => unstakeLike('unstake', owner, stakeMint, amount);
  const emergencyWithdraw = (owner, stakeMint) => unstakeLike('emergency_withdraw', owner, stakeMint);
  function claim(owner, stakeMint, rewardMint) {
    const p = pdas(stakeMint);
    return ix(cat(D.claim), [
      m(owner, true, false), m(p.config, false, true), m(userPda(p.config, owner), false, true), m(rewardMint, false, false),
      m(p.rewardVault, false, true), m(ata(owner, rewardMint), false, true), m(TOKEN_PROGRAM, false, false)]);
  }

  // ---------- SPL token helpers (classic token program)
  const createAtaIdempotent = (payer, owner, mint) => new TransactionInstruction({
    programId: ATA_PROGRAM, data: buf([1]),
    keys: [m(payer, true, true), m(ata(owner, mint), false, true), m(owner, false, false), m(mint, false, false),
      m(SystemProgram.programId, false, false), m(TOKEN_PROGRAM, false, false)]
  });
  function createMint(payer, mint, decimals, rentLamports) {
    return [
      SystemProgram.createAccount({ fromPubkey: payer, newAccountPubkey: mint, lamports: rentLamports, space: MINT_SIZE, programId: TOKEN_PROGRAM }),
      // InitializeMint2: tag 20, decimals, mint authority, no freeze authority
      new TransactionInstruction({ programId: TOKEN_PROGRAM, keys: [m(mint, false, true)],
        data: buf(cat([20, decimals], payer.toBytes(), [0])) })
    ];
  }
  const mintTo = (mint, dest, authority, amount) => new TransactionInstruction({
    programId: TOKEN_PROGRAM, data: buf(cat([7], u64(amount))),
    keys: [m(mint, false, true), m(dest, false, true), m(authority, true, false)]
  });

  // ---------- decoders
  const dv = d => new DataView(d.buffer, d.byteOffset, d.byteLength);
  const pk = (d, o) => new PublicKey(d.slice(o, o + 32));
  const u128 = (v, o) => v.getBigUint64(o, true) + (v.getBigUint64(o + 8, true) << 64n);
  const same = (d, disc) => disc.every((b, i) => d[i] === b);
  function decodeConfig(d) {
    if (!d || d.length < 260 || !same(d, ACC_CONFIG)) return null;
    const v = dv(d);
    return {
      admin: pk(d, 8), stakeMint: pk(d, 40), rewardMint: pk(d, 72), stakeVault: pk(d, 104), rewardVault: pk(d, 136),
      paused: d[168] === 1, minLockSecs: v.getBigInt64(169, true), totalStaked: v.getBigUint64(177, true),
      rewardRate: v.getBigUint64(185, true), rewardEnd: v.getBigInt64(193, true), lastUpdate: v.getBigInt64(201, true),
      accRewardPerShare: u128(v, 209), totalEmitted: u128(v, 225), totalClaimed: u128(v, 241),
      funder: d.length >= 292 ? pk(d, 260) : null
    };
  }
  function decodeUser(d) {
    if (!d || d.length < 113 || !same(d, ACC_USER)) return null;
    const v = dv(d);
    return { owner: pk(d, 8), config: pk(d, 40), amount: v.getBigUint64(72, true), rewardDebt: u128(v, 80),
      pending: v.getBigUint64(96, true), unlockAt: v.getBigInt64(104, true) };
  }
  const tokenAmount = d => (d && d.length >= 72 ? dv(d).getBigUint64(64, true) : 0n);
  const mintDecimals = d => (d && d.length >= 45 ? d[44] : null);

  // what claim() would pay right now (same maths as the program)
  function estimatePending(c, u, nowSecs) {
    if (!c || !u) return 0n;
    let acc = c.accRewardPerShare;
    const t = BigInt(Math.min(Number(nowSecs), Number(c.rewardEnd)));
    if (t > c.lastUpdate && c.totalStaked > 0n) acc += (t - c.lastUpdate) * c.rewardRate * ACC_PRECISION / c.totalStaked;
    const earned = u.amount * acc / ACC_PRECISION - u.rewardDebt;
    return u.pending + (earned > 0n ? earned : 0n);
  }

  // decimal string <-> smallest units
  function toUnits(str, decimals) {
    const s = String(str).trim().replace(',', '.');
    if (!/^\d+(\.\d+)?$/.test(s)) throw new Error('Invalid amount');
    const [i, f = ''] = s.split('.');
    if (f.length > decimals) throw new Error('Too many decimals (max ' + decimals + ')');
    return BigInt(i) * 10n ** BigInt(decimals) + BigInt((f + '0'.repeat(decimals)).slice(0, decimals) || '0');
  }
  function fromUnits(v, decimals) {
    const b = 10n ** BigInt(decimals), i = v / b, f = (v % b).toString().padStart(decimals, '0').replace(/0+$/, '');
    return i.toLocaleString('en-US') + (f ? '.' + f : '');
  }

  return { PROGRAM_ID, SPL_TOKEN, TOKEN_2022, useTokenProgram, tokenProgram: () => TOKEN_PROGRAM, ATA_PROGRAM, MINT_SIZE, pdas, userPda, ata,
    initialize, setPaused, setFunder, fundRewards, stake, unstake, emergencyWithdraw, claim,
    createAtaIdempotent, createMint, mintTo, decodeConfig, decodeUser, tokenAmount, mintDecimals,
    estimatePending, toUnits, fromUnits };
});
