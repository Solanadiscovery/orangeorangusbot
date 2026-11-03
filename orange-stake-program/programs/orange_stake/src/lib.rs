//! Orange Stake Club - staking program for $ORANGU.
//!
//! How it works
//! - Users lock (stake) tokens of one SPL mint in a vault owned by the program.
//! - Rewards come ONLY from tokens the admin, or the optional funder bot, deposits in a separate
//!   reward vault (`fund_rewards`). The funder can ONLY add rewards: it cannot pause, change rules,
//!   reclaim, or touch stakes.
//!   They are streamed linearly over a period chosen at funding time and shared pro rata between
//!   stakers (classic "reward per share" accumulator). No tokens are ever minted.
//! - A payout can never exceed what is in the reward vault. If nobody is staked, nothing is emitted.
//! - The pool starts PAUSED. While paused: no new stakes and no claims; unstake and
//!   emergency_withdraw always work, so users can always take their own tokens back.
//! - The admin can never touch staked tokens. The admin can only reclaim reward tokens that are
//!   not owed to anyone, and only after the reward period has ended.
//! - Supports SPL Token and Token-2022 mints WITHOUT transfer fees (transfer-fee mints are refused
//!   at initialization because vault balances would not match the accounting).

use anchor_lang::prelude::*;
use anchor_spl::token_interface::{
    self, Mint, TokenAccount, TokenInterface, TransferChecked,
};

declare_id!("FJCVCn2714BjcYCBKoqL2v6kQvfYPoHtLghnEPeHRm79");

/// Fixed-point precision of the reward-per-share accumulator.
pub const ACC_PRECISION: u128 = 1_000_000_000_000;
/// Longest allowed reward period and lock (5 years), to keep the maths far from overflow.
pub const MAX_DURATION_SECS: i64 = 5 * 365 * 24 * 3600;
/// The reward bot (funder) must stream over at least this long and can never shorten the current
/// stream, so a leaked bot key cannot dump the pending rewards on a staker in a few seconds.
pub const MIN_FUNDER_DURATION_SECS: i64 = 24 * 3600;

pub const CONFIG_SEED: &[u8] = b"config";
pub const STAKE_VAULT_SEED: &[u8] = b"stake_vault";
pub const REWARD_VAULT_SEED: &[u8] = b"reward_vault";
pub const USER_SEED: &[u8] = b"user";

#[program]
pub mod orange_stake {
    use super::*;

    /// Creates the pool for one stake mint and one reward mint (they can be the same mint).
    /// The pool starts paused.
    pub fn initialize(ctx: Context<Initialize>, min_lock_secs: i64) -> Result<()> {
        require!((0..=MAX_DURATION_SECS).contains(&min_lock_secs), StakeError::InvalidDuration);
        no_transfer_fee(&ctx.accounts.stake_mint.to_account_info())?;
        no_transfer_fee(&ctx.accounts.reward_mint.to_account_info())?;

        let now = Clock::get()?.unix_timestamp;
        let c = &mut ctx.accounts.config;
        c.admin = ctx.accounts.admin.key();
        c.stake_mint = ctx.accounts.stake_mint.key();
        c.reward_mint = ctx.accounts.reward_mint.key();
        c.stake_vault = ctx.accounts.stake_vault.key();
        c.reward_vault = ctx.accounts.reward_vault.key();
        c.paused = true;
        c.min_lock_secs = min_lock_secs;
        c.total_staked = 0;
        c.reward_rate = 0;
        c.reward_end = now;
        c.last_update = now;
        c.acc_reward_per_share = 0;
        c.total_emitted = 0;
        c.total_claimed = 0;
        c.bump = ctx.bumps.config;
        c.stake_vault_bump = ctx.bumps.stake_vault;
        c.reward_vault_bump = ctx.bumps.reward_vault;
        c.funder = Pubkey::default();
        emit!(PoolCreated { config: c.key(), stake_mint: c.stake_mint, reward_mint: c.reward_mint });
        Ok(())
    }

    /// Admin: pause or unpause the pool.
    pub fn set_paused(ctx: Context<AdminOnly>, paused: bool) -> Result<()> {
        ctx.accounts.config.paused = paused;
        emit!(PausedChanged { paused });
        Ok(())
    }

    /// Admin: change the minimum lock for FUTURE stakes and top-ups (it is applied at stake time).
    pub fn set_min_lock(ctx: Context<AdminOnly>, min_lock_secs: i64) -> Result<()> {
        require!((0..=MAX_DURATION_SECS).contains(&min_lock_secs), StakeError::InvalidDuration);
        ctx.accounts.config.min_lock_secs = min_lock_secs;
        Ok(())
    }

    /// Admin: hand the admin role to another key. Both keys must sign, so it cannot go to a typo.
    pub fn set_admin(ctx: Context<SetAdmin>) -> Result<()> {
        ctx.accounts.config.admin = ctx.accounts.new_admin.key();
        Ok(())
    }

    /// Admin: set the key allowed to add rewards (e.g. the automatic buyback bot).
    /// Pubkey::default() disables it. The funder can only call `fund_rewards`.
    pub fn set_funder(ctx: Context<AdminOnly>, funder: Pubkey) -> Result<()> {
        ctx.accounts.config.funder = funder;
        emit!(FunderChanged { funder });
        Ok(())
    }

    /// Admin or funder: deposit `amount` reward tokens and stream them, plus whatever is still left to stream,
    /// over the next `duration_secs`.
    pub fn fund_rewards(ctx: Context<FundRewards>, amount: u64, duration_secs: i64) -> Result<()> {
        require!(amount > 0, StakeError::ZeroAmount);
        require!(duration_secs > 0 && duration_secs <= MAX_DURATION_SECS, StakeError::InvalidDuration);
        let now = Clock::get()?.unix_timestamp;
        if ctx.accounts.funder.key() != ctx.accounts.config.admin {
            require!(duration_secs >= MIN_FUNDER_DURATION_SECS, StakeError::InvalidDuration);
            require!(now + duration_secs >= ctx.accounts.config.reward_end, StakeError::InvalidDuration);
        }

        update_pool(&mut ctx.accounts.config, now)?;

        let before = ctx.accounts.reward_vault.amount;
        token_interface::transfer_checked(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                TransferChecked {
                    from: ctx.accounts.funder_token.to_account_info(),
                    mint: ctx.accounts.reward_mint.to_account_info(),
                    to: ctx.accounts.reward_vault.to_account_info(),
                    authority: ctx.accounts.funder.to_account_info(),
                },
            ),
            amount,
            ctx.accounts.reward_mint.decimals,
        )?;
        ctx.accounts.reward_vault.reload()?;
        let received = ctx.accounts.reward_vault.amount.checked_sub(before).ok_or(StakeError::MathOverflow)?;
        require!(received == amount, StakeError::UnexpectedTransferAmount);

        let c = &mut ctx.accounts.config;
        let leftover: u128 = if now < c.reward_end {
            (c.reward_end - now) as u128 * c.reward_rate as u128
        } else {
            0
        };
        let total = leftover.checked_add(amount as u128).ok_or(StakeError::MathOverflow)?;
        let rate = total / duration_secs as u128;
        require!(rate > 0, StakeError::RewardRateTooLow);
        c.reward_rate = u64::try_from(rate).map_err(|_| StakeError::MathOverflow)?;
        c.reward_end = now + duration_secs;
        c.last_update = now;

        // The new stream can never promise more than the vault really holds.
        let owed = c.total_emitted.checked_sub(c.total_claimed).ok_or(StakeError::MathOverflow)?;
        let committed = (c.reward_rate as u128).checked_mul(duration_secs as u128)
            .and_then(|x| x.checked_add(owed)).ok_or(StakeError::MathOverflow)?;
        require!(committed <= ctx.accounts.reward_vault.amount as u128, StakeError::Underfunded);

        emit!(RewardsFunded { amount, rate: c.reward_rate, reward_end: c.reward_end });
        Ok(())
    }

    /// Lock `amount` tokens. Topping up restarts the minimum lock for the whole position.
    pub fn stake(ctx: Context<Stake>, amount: u64) -> Result<()> {
        require!(amount > 0, StakeError::ZeroAmount);
        require!(!ctx.accounts.config.paused, StakeError::Paused);
        let now = Clock::get()?.unix_timestamp;

        let user = &mut ctx.accounts.user_stake;
        if user.owner == Pubkey::default() {
            user.owner = ctx.accounts.owner.key();
            user.config = ctx.accounts.config.key();
            user.bump = ctx.bumps.user_stake;
        }
        update_pool(&mut ctx.accounts.config, now)?;
        settle(&ctx.accounts.config, user)?;

        let before = ctx.accounts.stake_vault.amount;
        token_interface::transfer_checked(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                TransferChecked {
                    from: ctx.accounts.owner_token.to_account_info(),
                    mint: ctx.accounts.stake_mint.to_account_info(),
                    to: ctx.accounts.stake_vault.to_account_info(),
                    authority: ctx.accounts.owner.to_account_info(),
                },
            ),
            amount,
            ctx.accounts.stake_mint.decimals,
        )?;
        ctx.accounts.stake_vault.reload()?;
        let received = ctx.accounts.stake_vault.amount.checked_sub(before).ok_or(StakeError::MathOverflow)?;
        require!(received == amount, StakeError::UnexpectedTransferAmount);

        let c = &mut ctx.accounts.config;
        user.amount = user.amount.checked_add(amount).ok_or(StakeError::MathOverflow)?;
        c.total_staked = c.total_staked.checked_add(amount).ok_or(StakeError::MathOverflow)?;
        user.unlock_at = now.checked_add(c.min_lock_secs).ok_or(StakeError::MathOverflow)?;
        user.reward_debt = debt(user.amount, c.acc_reward_per_share)?;
        emit!(Staked { owner: user.owner, amount, total: user.amount });
        Ok(())
    }

    /// Unlock `amount` tokens after the minimum lock. Works while paused. Pending rewards stay
    /// credited and can be claimed later.
    pub fn unstake(ctx: Context<Unstake>, amount: u64) -> Result<()> {
        require!(amount > 0, StakeError::ZeroAmount);
        let now = Clock::get()?.unix_timestamp;
        require!(amount <= ctx.accounts.user_stake.amount, StakeError::InsufficientStake);
        require!(now >= ctx.accounts.user_stake.unlock_at, StakeError::StillLocked);

        update_pool(&mut ctx.accounts.config, now)?;
        settle(&ctx.accounts.config, &mut ctx.accounts.user_stake)?;

        {
            let c = &mut ctx.accounts.config;
            let user = &mut ctx.accounts.user_stake;
            user.amount -= amount;
            c.total_staked = c.total_staked.checked_sub(amount).ok_or(StakeError::MathOverflow)?;
            user.reward_debt = debt(user.amount, c.acc_reward_per_share)?;
        }
        pay_from_stake_vault(&ctx.accounts.config, &ctx.accounts.stake_vault, &ctx.accounts.stake_mint,
            &ctx.accounts.owner_token, &ctx.accounts.token_program, amount)?;
        emit!(Unstaked { owner: ctx.accounts.owner.key(), amount });
        Ok(())
    }

    /// Pay out the caller's pending rewards (capped by what is in the reward vault).
    pub fn claim(ctx: Context<Claim>) -> Result<()> {
        require!(!ctx.accounts.config.paused, StakeError::Paused);
        let now = Clock::get()?.unix_timestamp;
        update_pool(&mut ctx.accounts.config, now)?;
        settle(&ctx.accounts.config, &mut ctx.accounts.user_stake)?;

        let pending = ctx.accounts.user_stake.pending;
        let pay = pending.min(ctx.accounts.reward_vault.amount);
        require!(pay > 0, StakeError::NothingToClaim);
        {
            let user = &mut ctx.accounts.user_stake;
            user.pending -= pay;
            let c = &mut ctx.accounts.config;
            c.total_claimed = c.total_claimed.checked_add(pay as u128).ok_or(StakeError::MathOverflow)?;
        }
        let c = &ctx.accounts.config;
        let stake_mint = c.stake_mint;
        let seeds: &[&[u8]] = &[CONFIG_SEED, stake_mint.as_ref(), &[c.bump]];
        token_interface::transfer_checked(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                TransferChecked {
                    from: ctx.accounts.reward_vault.to_account_info(),
                    mint: ctx.accounts.reward_mint.to_account_info(),
                    to: ctx.accounts.owner_reward_token.to_account_info(),
                    authority: ctx.accounts.config.to_account_info(),
                },
                &[seeds],
            ),
            pay,
            ctx.accounts.reward_mint.decimals,
        )?;
        emit!(Claimed { owner: ctx.accounts.owner.key(), amount: pay });
        Ok(())
    }

    /// Safety exit: take the whole stake back immediately, ignoring the lock, even while paused.
    /// Rewards not yet claimed are given up (they stay in the reward vault).
    pub fn emergency_withdraw(ctx: Context<Unstake>) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        update_pool(&mut ctx.accounts.config, now)?;
        let amount = ctx.accounts.user_stake.amount;
        require!(amount > 0, StakeError::InsufficientStake);
        {
            let c = &mut ctx.accounts.config;
            let user = &mut ctx.accounts.user_stake;
            // rewards earned but never claimed go back to the pool: count them as no longer owed
            let earned = debt(amount, c.acc_reward_per_share)?
                .saturating_sub(user.reward_debt) + user.pending as u128;
            c.total_claimed = c.total_claimed.checked_add(earned).ok_or(StakeError::MathOverflow)?;
            c.total_staked = c.total_staked.checked_sub(amount).ok_or(StakeError::MathOverflow)?;
            user.amount = 0;
            user.pending = 0;
            user.reward_debt = 0;
        }
        pay_from_stake_vault(&ctx.accounts.config, &ctx.accounts.stake_vault, &ctx.accounts.stake_mint,
            &ctx.accounts.owner_token, &ctx.accounts.token_program, amount)?;
        emit!(EmergencyWithdrawn { owner: ctx.accounts.owner.key(), amount });
        Ok(())
    }

    /// Admin: after the reward period, take back reward tokens that nobody is owed.
    pub fn reclaim_rewards(ctx: Context<ReclaimRewards>) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        update_pool(&mut ctx.accounts.config, now)?;
        let c = &ctx.accounts.config;
        require!(now >= c.reward_end, StakeError::RewardsStillStreaming);
        let owed = c.total_emitted.checked_sub(c.total_claimed).ok_or(StakeError::MathOverflow)?;
        let spare = (ctx.accounts.reward_vault.amount as u128).saturating_sub(owed);
        let spare = u64::try_from(spare).map_err(|_| StakeError::MathOverflow)?;
        require!(spare > 0, StakeError::NothingToClaim);
        // if stake and reward mint are the same, the two vaults are still separate accounts,
        // so staked tokens are never part of `spare`.
        let stake_mint = c.stake_mint;
        let seeds: &[&[u8]] = &[CONFIG_SEED, stake_mint.as_ref(), &[c.bump]];
        token_interface::transfer_checked(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                TransferChecked {
                    from: ctx.accounts.reward_vault.to_account_info(),
                    mint: ctx.accounts.reward_mint.to_account_info(),
                    to: ctx.accounts.admin_token.to_account_info(),
                    authority: ctx.accounts.config.to_account_info(),
                },
                &[seeds],
            ),
            spare,
            ctx.accounts.reward_mint.decimals,
        )?;
        Ok(())
    }
}

// ---------------------------------------------------------------- maths

/// Bring the accumulator up to `now` (never past the end of the reward period).
pub fn update_pool(c: &mut Config, now: i64) -> Result<()> {
    let t = now.min(c.reward_end);
    if t > c.last_update {
        if c.total_staked > 0 {
            let emitted = (t - c.last_update) as u128 * c.reward_rate as u128;
            c.acc_reward_per_share = c.acc_reward_per_share
                .checked_add(emitted.checked_mul(ACC_PRECISION).ok_or(StakeError::MathOverflow)? / c.total_staked as u128)
                .ok_or(StakeError::MathOverflow)?;
            c.total_emitted = c.total_emitted.checked_add(emitted).ok_or(StakeError::MathOverflow)?;
        }
        c.last_update = t;
    }
    if now > c.last_update && now >= c.reward_end {
        c.last_update = now;
    }
    Ok(())
}

/// amount * acc / ACC_PRECISION without overflowing the intermediate product.
/// (amount * acc can exceed u128 when a tiny stake was alone in the pool for a while; splitting acc
/// into quotient and remainder keeps the exact same floor result with no overflow.)
fn debt(amount: u64, acc: u128) -> Result<u128> {
    let a = amount as u128;
    let hi = a.checked_mul(acc / ACC_PRECISION).ok_or(StakeError::MathOverflow)?;
    let lo = a * (acc % ACC_PRECISION) / ACC_PRECISION; // < 2^64 * 10^12, fits
    Ok(hi.checked_add(lo).ok_or(StakeError::MathOverflow)?)
}

/// Move what the user earned since the last action into `pending`.
fn settle(c: &Config, user: &mut UserStake) -> Result<()> {
    let accrued = debt(user.amount, c.acc_reward_per_share)?.saturating_sub(user.reward_debt);
    let accrued = u64::try_from(accrued).map_err(|_| StakeError::MathOverflow)?;
    user.pending = user.pending.checked_add(accrued).ok_or(StakeError::MathOverflow)?;
    user.reward_debt = debt(user.amount, c.acc_reward_per_share)?;
    Ok(())
}

fn pay_from_stake_vault<'info>(
    c: &Account<'info, Config>,
    vault: &InterfaceAccount<'info, TokenAccount>,
    mint: &InterfaceAccount<'info, Mint>,
    to: &InterfaceAccount<'info, TokenAccount>,
    token_program: &Interface<'info, TokenInterface>,
    amount: u64,
) -> Result<()> {
    let stake_mint = c.stake_mint;
    let seeds: &[&[u8]] = &[CONFIG_SEED, stake_mint.as_ref(), &[c.bump]];
    token_interface::transfer_checked(
        CpiContext::new_with_signer(
            token_program.to_account_info(),
            TransferChecked {
                from: vault.to_account_info(),
                mint: mint.to_account_info(),
                to: to.to_account_info(),
                authority: c.to_account_info(),
            },
            &[seeds],
        ),
        amount,
        mint.decimals,
    )
}

/// Refuse Token-2022 mints that carry extensions changing transfer amounts or control.
fn no_transfer_fee(mint: &AccountInfo) -> Result<()> {
    if mint.owner == &anchor_spl::token_2022::ID {
        use anchor_spl::token_2022::spl_token_2022::extension::{BaseStateWithExtensions, ExtensionType, StateWithExtensions};
        use anchor_spl::token_2022::spl_token_2022::state::Mint as M22;
        let data = mint.try_borrow_data()?;
        let state = StateWithExtensions::<M22>::unpack(&data)?;
        for ext in state.get_extension_types()? {
            require!(
                !matches!(ext, ExtensionType::TransferFeeConfig | ExtensionType::TransferHook
                    | ExtensionType::PermanentDelegate | ExtensionType::NonTransferable
                    | ExtensionType::ConfidentialTransferMint),
                StakeError::UnsupportedMint
            );
        }
    }
    Ok(())
}

// ---------------------------------------------------------------- state

#[account]
#[derive(InitSpace)]
pub struct Config {
    pub admin: Pubkey,
    pub stake_mint: Pubkey,
    pub reward_mint: Pubkey,
    pub stake_vault: Pubkey,
    pub reward_vault: Pubkey,
    pub paused: bool,
    pub min_lock_secs: i64,
    pub total_staked: u64,
    /// reward tokens (smallest unit) emitted per second while someone is staked
    pub reward_rate: u64,
    pub reward_end: i64,
    pub last_update: i64,
    pub acc_reward_per_share: u128,
    pub total_emitted: u128,
    pub total_claimed: u128,
    pub bump: u8,
    pub stake_vault_bump: u8,
    pub reward_vault_bump: u8,
    /// optional key that may only add rewards (default = none)
    pub funder: Pubkey,
}

#[account]
#[derive(InitSpace)]
pub struct UserStake {
    pub owner: Pubkey,
    pub config: Pubkey,
    pub amount: u64,
    pub reward_debt: u128,
    pub pending: u64,
    pub unlock_at: i64,
    pub bump: u8,
}

// ---------------------------------------------------------------- accounts

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub admin: Signer<'info>,
    #[account(init, payer = admin, space = 8 + Config::INIT_SPACE, seeds = [CONFIG_SEED, stake_mint.key().as_ref()], bump)]
    pub config: Account<'info, Config>,
    #[account(mint::token_program = token_program)]
    pub stake_mint: InterfaceAccount<'info, Mint>,
    #[account(mint::token_program = token_program)]
    pub reward_mint: InterfaceAccount<'info, Mint>,
    #[account(init, payer = admin, seeds = [STAKE_VAULT_SEED, config.key().as_ref()], bump,
        token::mint = stake_mint, token::authority = config, token::token_program = token_program)]
    pub stake_vault: InterfaceAccount<'info, TokenAccount>,
    #[account(init, payer = admin, seeds = [REWARD_VAULT_SEED, config.key().as_ref()], bump,
        token::mint = reward_mint, token::authority = config, token::token_program = token_program)]
    pub reward_vault: InterfaceAccount<'info, TokenAccount>,
    pub token_program: Interface<'info, TokenInterface>,
    pub system_program: Program<'info, System>,
    /// Only the program's upgrade authority can create a pool, so nobody can front-run the
    /// official pool for the $ORANGU mint and become its admin.
    #[account(constraint = program.programdata_address()? == Some(program_data.key()) @ StakeError::Unauthorized)]
    pub program: Program<'info, crate::program::OrangeStake>,
    #[account(constraint = program_data.upgrade_authority_address == Some(admin.key()) @ StakeError::Unauthorized)]
    pub program_data: Account<'info, ProgramData>,
}

#[derive(Accounts)]
pub struct AdminOnly<'info> {
    pub admin: Signer<'info>,
    #[account(mut, has_one = admin @ StakeError::Unauthorized)]
    pub config: Account<'info, Config>,
}

#[derive(Accounts)]
pub struct SetAdmin<'info> {
    pub admin: Signer<'info>,
    pub new_admin: Signer<'info>,
    #[account(mut, has_one = admin @ StakeError::Unauthorized)]
    pub config: Account<'info, Config>,
}

#[derive(Accounts)]
pub struct FundRewards<'info> {
    pub funder: Signer<'info>,
    #[account(mut, has_one = reward_mint, has_one = reward_vault,
        constraint = funder.key() == config.admin
            || (config.funder != Pubkey::default() && funder.key() == config.funder) @ StakeError::Unauthorized)]
    pub config: Account<'info, Config>,
    pub reward_mint: InterfaceAccount<'info, Mint>,
    #[account(mut)]
    pub reward_vault: InterfaceAccount<'info, TokenAccount>,
    #[account(mut, token::mint = reward_mint, token::authority = funder, token::token_program = token_program)]
    pub funder_token: InterfaceAccount<'info, TokenAccount>,
    pub token_program: Interface<'info, TokenInterface>,
}

#[derive(Accounts)]
pub struct Stake<'info> {
    #[account(mut)]
    pub owner: Signer<'info>,
    #[account(mut, has_one = stake_mint, has_one = stake_vault)]
    pub config: Account<'info, Config>,
    #[account(init_if_needed, payer = owner, space = 8 + UserStake::INIT_SPACE,
        seeds = [USER_SEED, config.key().as_ref(), owner.key().as_ref()], bump)]
    pub user_stake: Account<'info, UserStake>,
    pub stake_mint: InterfaceAccount<'info, Mint>,
    #[account(mut)]
    pub stake_vault: InterfaceAccount<'info, TokenAccount>,
    #[account(mut, token::mint = stake_mint, token::authority = owner, token::token_program = token_program)]
    pub owner_token: InterfaceAccount<'info, TokenAccount>,
    pub token_program: Interface<'info, TokenInterface>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Unstake<'info> {
    pub owner: Signer<'info>,
    #[account(mut, has_one = stake_mint, has_one = stake_vault)]
    pub config: Account<'info, Config>,
    #[account(mut, seeds = [USER_SEED, config.key().as_ref(), owner.key().as_ref()], bump = user_stake.bump,
        has_one = owner, has_one = config)]
    pub user_stake: Account<'info, UserStake>,
    pub stake_mint: InterfaceAccount<'info, Mint>,
    #[account(mut)]
    pub stake_vault: InterfaceAccount<'info, TokenAccount>,
    #[account(mut, token::mint = stake_mint, token::token_program = token_program)]
    pub owner_token: InterfaceAccount<'info, TokenAccount>,
    pub token_program: Interface<'info, TokenInterface>,
}

#[derive(Accounts)]
pub struct Claim<'info> {
    pub owner: Signer<'info>,
    #[account(mut, has_one = reward_mint, has_one = reward_vault)]
    pub config: Account<'info, Config>,
    #[account(mut, seeds = [USER_SEED, config.key().as_ref(), owner.key().as_ref()], bump = user_stake.bump,
        has_one = owner, has_one = config)]
    pub user_stake: Account<'info, UserStake>,
    pub reward_mint: InterfaceAccount<'info, Mint>,
    #[account(mut)]
    pub reward_vault: InterfaceAccount<'info, TokenAccount>,
    #[account(mut, token::mint = reward_mint, token::token_program = token_program)]
    pub owner_reward_token: InterfaceAccount<'info, TokenAccount>,
    pub token_program: Interface<'info, TokenInterface>,
}

#[derive(Accounts)]
pub struct ReclaimRewards<'info> {
    pub admin: Signer<'info>,
    #[account(mut, has_one = admin @ StakeError::Unauthorized, has_one = reward_mint, has_one = reward_vault)]
    pub config: Account<'info, Config>,
    pub reward_mint: InterfaceAccount<'info, Mint>,
    #[account(mut)]
    pub reward_vault: InterfaceAccount<'info, TokenAccount>,
    #[account(mut, token::mint = reward_mint, token::token_program = token_program)]
    pub admin_token: InterfaceAccount<'info, TokenAccount>,
    pub token_program: Interface<'info, TokenInterface>,
}

// ---------------------------------------------------------------- events & errors

#[event] pub struct PoolCreated { pub config: Pubkey, pub stake_mint: Pubkey, pub reward_mint: Pubkey }
#[event] pub struct PausedChanged { pub paused: bool }
#[event] pub struct FunderChanged { pub funder: Pubkey }
#[event] pub struct RewardsFunded { pub amount: u64, pub rate: u64, pub reward_end: i64 }
#[event] pub struct Staked { pub owner: Pubkey, pub amount: u64, pub total: u64 }
#[event] pub struct Unstaked { pub owner: Pubkey, pub amount: u64 }
#[event] pub struct Claimed { pub owner: Pubkey, pub amount: u64 }
#[event] pub struct EmergencyWithdrawn { pub owner: Pubkey, pub amount: u64 }

#[error_code]
pub enum StakeError {
    #[msg("Not allowed for this key")] Unauthorized,
    #[msg("The pool is paused")] Paused,
    #[msg("Amount must be greater than zero")] ZeroAmount,
    #[msg("Invalid duration")] InvalidDuration,
    #[msg("Not enough staked")] InsufficientStake,
    #[msg("Tokens are still locked")] StillLocked,
    #[msg("Nothing to claim")] NothingToClaim,
    #[msg("Reward rate rounds down to zero: deposit more or use a shorter period")] RewardRateTooLow,
    #[msg("The reward vault does not hold enough tokens for this stream")] Underfunded,
    #[msg("Rewards are still streaming")] RewardsStillStreaming,
    #[msg("Math overflow")] MathOverflow,
    #[msg("Transferred amount differs from the requested amount")] UnexpectedTransferAmount,
    #[msg("Mint type not supported (transfer fees, hooks or similar extensions)")] UnsupportedMint,
}
