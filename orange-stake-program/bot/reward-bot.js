/* $ORANGU reward bot - Orange Stake Club
 * Each run: 1) collect pump.fun creator fees (SOL) into the bot wallet
 *           (optional) send treasurySharePct % of that SOL to the main treasury
 *           2) buy back $ORANGU with the SOL above the reserve
 *           3) send eventsSharePct % of the tokens JUST BOUGHT to the events wallet
 *           4) load the rest into the staking reward pool (fund_rewards, streamed over rewardDays)
 * Only tokens bought in this run are moved: anything else in the wallet is never touched.
 * The bot wallet must be set as "reward bot" (funder) in the staking admin page: it can only ADD rewards.
 * dryRun: true (default) = shows what it would do, sends nothing.
 * Usage: node reward-bot.js          (one run, e.g. from Task Scheduler / cron)
 *        node reward-bot.js --loop   (runs every intervalMinutes) */
'use strict';
const fs = require('fs');
const path = require('path');
const W = require('@solana/web3.js');
const C = require('../app/staking-core.js')(W);

const DIR = __dirname;
const cfg = JSON.parse(fs.readFileSync(process.env.BOT_CONFIG || path.join(DIR, 'config.json'), 'utf8'));
const STATE = path.join(DIR, 'bot-state.json');
const readCarry = () => { try { return BigInt(JSON.parse(fs.readFileSync(STATE, 'utf8')).carryRaw || 0); } catch { return 0n; } };
const writeCarry = v => fs.writeFileSync(STATE, JSON.stringify({ carryRaw: v.toString() }));
const LOG = path.join(DIR, 'bot-log.jsonl');
const SOL_MINT = 'So11111111111111111111111111111111111111112';
let conn = new W.Connection(cfg.rpcUrl, 'confirmed');
const bot = W.Keypair.fromSecretKey(Uint8Array.from(JSON.parse(fs.readFileSync(path.resolve(DIR, cfg.keypairPath), 'utf8'))));
const mint = new W.PublicKey(cfg.mint);
const DRY = cfg.dryRun !== false;

const log = (step, data = {}) => {
  const row = { t: new Date().toISOString(), step, dry: DRY, ...data };
  console.log(`[${row.t}] ${step}`, Object.keys(data).length ? JSON.stringify(data) : '');
  fs.appendFileSync(LOG, JSON.stringify(row) + '\n');
};
const lamports = sol => BigInt(Math.floor(sol * 1e9));

async function sendVersioned(bytes, label) {
  const tx = W.VersionedTransaction.deserialize(bytes);
  tx.sign([bot]);
  const sig = await conn.sendRawTransaction(tx.serialize(), { maxRetries: 3 });
  const bh = await conn.getLatestBlockhash();
  const r = await conn.confirmTransaction({ signature: sig, ...bh }, 'confirmed');
  if (r.value.err) throw new Error(label + ' failed: ' + JSON.stringify(r.value.err));
  log(label + ' ok', { sig });
  return sig;
}

async function pumpPortal(body) {
  const res = await fetch('https://pumpportal.fun/api/trade-local', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ publicKey: bot.publicKey.toBase58(), priorityFee: 0.00001, ...body })
  });
  if (res.status !== 200) throw new Error('PumpPortal ' + res.status + ': ' + (await res.text()).slice(0, 200));
  return new Uint8Array(await res.arrayBuffer());
}

async function tokenBalance(ata) {
  const info = await conn.getAccountInfo(ata);
  return info ? C.tokenAmount(info.data) : 0n;
}

let buyFn = buy;
async function buy(solAmount) {
  const amount = lamports(solAmount).toString();
  // 1st choice: Jupiter (best route, works after graduation to PumpSwap)
  try {
    const q = await (await fetch(`https://lite-api.jup.ag/swap/v1/quote?inputMint=${SOL_MINT}&outputMint=${mint.toBase58()}&amount=${amount}&slippageBps=${cfg.slippageBps}`)).json();
    if (!q.outAmount) throw new Error(q.error || 'no route');
    log('quote', { sol: solAmount, expectedTokensRaw: q.outAmount, via: 'jupiter' });
    if (DRY) return;
    const s = await (await fetch('https://lite-api.jup.ag/swap/v1/swap', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quoteResponse: q, userPublicKey: bot.publicKey.toBase58(), wrapAndUnwrapSol: true,
        dynamicComputeUnitLimit: true, prioritizationFeeLamports: 'auto' })
    })).json();
    if (!s.swapTransaction) throw new Error(s.error || 'swap build failed');
    return sendVersioned(Buffer.from(s.swapTransaction, 'base64'), 'buyback');
  } catch (e) {
    log('jupiter unavailable, using pump.fun', { reason: String(e.message || e) });
  }
  // fallback: pump.fun bonding curve / PumpSwap via PumpPortal
  if (DRY) { log('quote', { sol: solAmount, via: 'pumpportal' }); return; }
  const bytes = await pumpPortal({ action: 'buy', mint: mint.toBase58(), amount: solAmount, denominatedInSol: 'true',
    slippage: Math.max(1, Math.round(cfg.slippageBps / 100)), pool: 'auto' });
  return sendVersioned(bytes, 'buyback');
}

// SPL TransferChecked (tag 12), works for SPL Token and Token-2022
function transferChecked(src, dst, owner, amount, decimals) {
  const d = new Uint8Array(10); d[0] = 12; new DataView(d.buffer).setBigUint64(1, amount, true); d[9] = decimals;
  return new W.TransactionInstruction({ programId: C.tokenProgram(), data: Buffer.from(d), keys: [
    { pubkey: src, isSigner: false, isWritable: true }, { pubkey: mint, isSigner: false, isWritable: false },
    { pubkey: dst, isSigner: false, isWritable: true }, { pubkey: owner, isSigner: true, isWritable: false }] });
}

let send = tx => W.sendAndConfirmTransaction(conn, tx, [bot], { commitment: 'confirmed' });

async function runOnce() {
  const mintInfo = await conn.getAccountInfo(mint);
  if (!mintInfo) throw new Error('Token mint not found: check "mint" and "rpcUrl" in config.json');
  C.useTokenProgram(mintInfo.owner);
  const decimals = C.mintDecimals(mintInfo.data);
  const p = C.pdas(mint);
  const pool = await conn.getAccountInfo(p.config);
  const pc = pool && C.decodeConfig(pool.data);
  if (!pc) throw new Error('Staking pool not found for this token');
  const me = bot.publicKey;
  if (!me.equals(pc.admin) && !(pc.funder && me.equals(pc.funder)))
    throw new Error('This wallet is not the reward bot of the pool: set it in the admin page (step 6)');

  // 1) creator fees
  if (cfg.claimCreatorFees) {
    if (DRY) log('would collect creator fees');
    else {
      try { await sendVersioned(await pumpPortal({ action: 'collectCreatorFee' }), 'collect creator fees'); }
      catch (e) { log('no creator fees collected', { reason: String(e.message || e) }); }
    }
  }

  // 2) buyback with SOL above the reserve
  const sol = (await conn.getBalance(me)) / 1e9;
  const spend = Math.min(sol - cfg.solReserve, cfg.maxSolPerRun);
  log('balance', { sol, spend: Math.max(0, spend) });
  if (spend < cfg.minSolToBuy) { log('not enough SOL yet, nothing to do'); return; }
  // optional: a share of the SOL goes to the main treasury (address only, the bot has no access to it)
  let buySol = spend;
  const tPct = cfg.treasuryWallet ? Math.max(0, Math.min(100, Number(cfg.treasurySharePct) || 0)) : 0;
  if (tPct > 0) {
    const tSol = Number((spend * tPct / 100).toFixed(9));
    buySol = Number((spend - tSol).toFixed(9));
    if (DRY) log('would send SOL to treasury', { sol: tSol });
    else {
      const tx = new W.Transaction().add(W.SystemProgram.transfer({ fromPubkey: me, toPubkey: new W.PublicKey(cfg.treasuryWallet), lamports: lamports(tSol) }));
      log('sent SOL to treasury', { sol: tSol, sig: await send(tx) });
    }
    if (buySol < cfg.minSolToBuy) return;
  }
  const myAta = C.ata(me, mint);
  const before = await tokenBalance(myAta);
  await buyFn(Number(buySol.toFixed(9)));
  if (DRY) { log('dry run done: set "dryRun": false in config.json to go live'); return; }
  const bought = (await tokenBalance(myAta)) - before;
  // tokens bought in earlier runs whose loading failed are retried here (never other tokens)
  const total = (bought > 0n ? bought : 0n) + readCarry();
  writeCarry(total);
  if (total <= 0n) { log('buyback returned no tokens'); return; }

  // 3) + 4) split only what was just bought
  const pct = cfg.eventsWallet ? BigInt(Math.max(0, Math.min(100, Math.round(cfg.eventsSharePct)))) : 0n;
  const toEvents = total * pct / 100n;
  const toPool = total - toEvents;
  const tx = new W.Transaction();
  if (toEvents > 0n) {
    const ev = new W.PublicKey(cfg.eventsWallet);
    tx.add(C.createAtaIdempotent(me, ev, mint), transferChecked(myAta, C.ata(ev, mint), me, toEvents, decimals));
  }
  // the contract never lets the bot shorten the running stream (min 1 day): extend it if needed
  const nowS = Math.floor(Date.now() / 1000);
  const dur = Math.max(Math.round(cfg.rewardDays * 86400), 86400, Number(pc.rewardEnd) - nowS + 120);
  if (toPool > 0n) tx.add(C.fundRewards(me, mint, mint, toPool, dur));
  const sig = await send(tx);
  writeCarry(0n);
  log('rewards loaded', { sig, boughtRaw: total.toString(), toPoolRaw: toPool.toString(), toEventsRaw: toEvents.toString(), decimals });
}

async function main() {
  const loop = process.argv.includes('--loop');
  do {
    try { await runOnce(); } catch (e) { log('error', { message: String(e.message || e) }); if (!loop) process.exitCode = 1; }
    if (loop) await new Promise(r => setTimeout(r, Math.max(5, cfg.intervalMinutes) * 60000));
  } while (loop);
}
if (require.main === module) main();
else module.exports = { runOnce, _test: o => { conn = o.conn; buyFn = o.buy; send = o.send; } };
