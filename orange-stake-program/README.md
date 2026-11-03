# Orange Stake Club

Staking program for **$ORANGU** on Solana, plus the staking web page and the reward bot.

| | |
|---|---|
| Program ID | `FJCVCn2714BjcYCBKoqL2v6kQvfYPoHtLghnEPeHRm79` |
| Framework | Anchor 0.31.1 (Rust) |
| Build | `solanafoundation/solana-verifiable-build:4.0.0` |
| Build hash (sha256 of `orange_stake.so`) | `aae300ecb9ca4837a700f24e8b708f4f72044687ccc3ca87ee18402dbdc3ee3e` |

## What the contract does

- Users stake $ORANGU into a vault owned by the program (PDA). A second PDA vault holds the rewards.
- Rewards are streamed every second and shared pro rata by stake size and time (reward-per-share accumulator).
- Rewards only come from tokens deposited with `fund_rewards`. The program never mints tokens, and a stream can never promise more than the reward vault holds.
- `unstake` works after the minimum lock, even while the pool is paused. `emergency_withdraw` always returns the whole stake immediately (unclaimed rewards stay in the pool).

## Roles

| Role | Can | Cannot |
|---|---|---|
| Admin | pause/unpause stakes and claims, set the minimum lock for future stakes, add rewards, set the reward bot, recover rewards owed to nobody after a period ends | move, freeze or withdraw staked tokens; block unstake or emergency withdraw; take rewards already earned; mint tokens |
| Reward bot (`funder`) | add rewards, streamed over at least 24 h, never shortening the running stream | anything else |
| User | stake, claim, unstake, emergency withdraw | touch other users' positions |

Only the program's upgrade authority can create the pool, so the official pool cannot be front-run.

## Instructions

`initialize`, `set_paused`, `set_min_lock`, `set_admin` (both keys sign), `set_funder`, `fund_rewards`, `stake`, `unstake`, `claim`, `emergency_withdraw`, `reclaim_rewards`.
PDAs: config `["config", stake_mint]`, `["stake_vault", config]`, `["reward_vault", config]`, user `["user", config, owner]`.

## Tests

```
cd tests-litesvm
npm i @solana/web3.js@1.98.4   # only for the web-page test
cargo test --release
```
12 tests on LiteSVM: pool creation rights, pause, pro-rata rewards, lock, emergency exit, funding rights, reward-bot limits, reclaim limits, same-mint vaults, solvency, accumulator overflow with a dust staker, and the instructions built by the web page.

## Verify the deployed program

```
solana-verify verify-from-repo -um --program-id FJCVCn2714BjcYCBKoqL2v6kQvfYPoHtLghnEPeHRm79 \
  https://github.com/solanadiscovery/orangeorangusbot --commit-hash <COMMIT> \
  --mount-path orange-stake-program --library-name orange_stake
```
The hash printed must match the on-chain program hash (`solana-verify get-program-hash -um FJCVCn2714BjcYCBKoqL2v6kQvfYPoHtLghnEPeHRm79`).

## Folders

- `programs/orange_stake` – the contract
- `tests-litesvm` – automated tests
- `app/staking-core.js` – client helpers used by the staking web page to build the instructions
- `bot` – reward bot: collects pump.fun creator fees, buys back $ORANGU, sends the events share and loads the reward pool
