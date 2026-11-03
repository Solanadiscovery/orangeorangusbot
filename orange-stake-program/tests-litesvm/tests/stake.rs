//! End-to-end tests of the compiled orange_stake program on a local simulated chain (LiteSVM).
//! Build the program first: `cargo-build-sbf --manifest-path ../programs/orange_stake/Cargo.toml`.

use litesvm::LiteSVM;
use sha2::{Digest, Sha256};
use solana_sdk::{
    clock::Clock,
    instruction::{AccountMeta, Instruction},
    program_pack::Pack,
    pubkey::Pubkey,
    signature::{Keypair, Signer},
    system_instruction, system_program,
    transaction::Transaction,
};
use std::str::FromStr;

const PROGRAM_ID: &str = "FJCVCn2714BjcYCBKoqL2v6kQvfYPoHtLghnEPeHRm79";
const SO: &str = "../target/deploy/orange_stake.so";

fn pid() -> Pubkey { Pubkey::from_str(PROGRAM_ID).unwrap() }
fn tok() -> Pubkey { spl_token::id() }

fn disc(name: &str) -> Vec<u8> {
    Sha256::digest(format!("global:{name}").as_bytes())[..8].to_vec()
}

struct Env {
    svm: LiteSVM,
    admin: Keypair,
    stake_mint: Pubkey,
    reward_mint: Pubkey,
    config: Pubkey,
    stake_vault: Pubkey,
    reward_vault: Pubkey,
    admin_reward_ata: Pubkey,
}

fn send(svm: &mut LiteSVM, ixs: &[Instruction], payer: &Keypair, signers: &[&Keypair]) -> Result<(), String> {
    svm.expire_blockhash();
    let tx = Transaction::new_signed_with_payer(ixs, Some(&payer.pubkey()), signers, svm.latest_blockhash());
    svm.send_transaction(tx).map(|_| ()).map_err(|e| format!("{:?}", e.err) + &e.meta.logs.join("\n"))
}

fn create_mint(svm: &mut LiteSVM, payer: &Keypair) -> Pubkey {
    let m = Keypair::new();
    let rent = svm.minimum_balance_for_rent_exemption(spl_token::state::Mint::LEN);
    let ixs = [
        system_instruction::create_account(&payer.pubkey(), &m.pubkey(), rent, spl_token::state::Mint::LEN as u64, &tok()),
        spl_token::instruction::initialize_mint2(&tok(), &m.pubkey(), &payer.pubkey(), None, 6).unwrap(),
    ];
    send(svm, &ixs, payer, &[payer, &m]).unwrap();
    m.pubkey()
}

fn create_token_account(svm: &mut LiteSVM, payer: &Keypair, mint: &Pubkey, owner: &Pubkey) -> Pubkey {
    let a = Keypair::new();
    let rent = svm.minimum_balance_for_rent_exemption(spl_token::state::Account::LEN);
    let ixs = [
        system_instruction::create_account(&payer.pubkey(), &a.pubkey(), rent, spl_token::state::Account::LEN as u64, &tok()),
        spl_token::instruction::initialize_account3(&tok(), &a.pubkey(), mint, owner).unwrap(),
    ];
    send(svm, &ixs, payer, &[payer, &a]).unwrap();
    a.pubkey()
}

fn mint_to(svm: &mut LiteSVM, admin: &Keypair, mint: &Pubkey, to: &Pubkey, amount: u64) {
    let ix = spl_token::instruction::mint_to(&tok(), mint, to, &admin.pubkey(), &[], amount).unwrap();
    send(svm, &[ix], admin, &[admin]).unwrap();
}

fn balance(svm: &LiteSVM, acc: &Pubkey) -> u64 {
    let a = svm.get_account(acc).unwrap();
    u64::from_le_bytes(a.data[64..72].try_into().unwrap())
}

fn set_time(svm: &mut LiteSVM, t: i64) {
    let mut c: Clock = svm.get_sysvar();
    c.unix_timestamp = t;
    svm.set_sysvar(&c);
}

fn user_pda(config: &Pubkey, owner: &Pubkey) -> Pubkey {
    Pubkey::find_program_address(&[b"user", config.as_ref(), owner.as_ref()], &pid()).0
}

const T0: i64 = 1_800_000_000;

/// Deploy the program with the upgradeable loader, `authority` as upgrade authority. Returns ProgramData address.
fn deploy_upgradeable(svm: &mut LiteSVM, authority: &Pubkey) -> Pubkey {
    use solana_sdk::{account::Account, bpf_loader_upgradeable};
    let elf = std::fs::read(SO).expect("build the program first");
    let pd = Pubkey::find_program_address(&[pid().as_ref()], &bpf_loader_upgradeable::id()).0;
    let mut pd_data = vec![3u8, 0, 0, 0];
    pd_data.extend_from_slice(&0u64.to_le_bytes());
    pd_data.push(1);
    pd_data.extend_from_slice(authority.as_ref());
    pd_data.extend_from_slice(&elf);
    let lam = svm.minimum_balance_for_rent_exemption(pd_data.len());
    svm.set_account(pd, Account { lamports: lam, data: pd_data, owner: bpf_loader_upgradeable::id(), executable: false, rent_epoch: 0 }).unwrap();
    let mut p_data = vec![2u8, 0, 0, 0];
    p_data.extend_from_slice(pd.as_ref());
    let lam = svm.minimum_balance_for_rent_exemption(p_data.len());
    svm.set_account(pid(), Account { lamports: lam, data: p_data, owner: bpf_loader_upgradeable::id(), executable: true, rent_epoch: 0 }).unwrap();
    pd
}

fn setup(same_mint: bool, min_lock: i64) -> Env {
    let mut svm = LiteSVM::new();
    set_time(&mut svm, T0);
    let admin = Keypair::new();
    let program_data = deploy_upgradeable(&mut svm, &admin.pubkey());
    svm.airdrop(&admin.pubkey(), 100_000_000_000).unwrap();
    let stake_mint = create_mint(&mut svm, &admin);
    let reward_mint = if same_mint { stake_mint } else { create_mint(&mut svm, &admin) };
    let config = Pubkey::find_program_address(&[b"config", stake_mint.as_ref()], &pid()).0;
    let stake_vault = Pubkey::find_program_address(&[b"stake_vault", config.as_ref()], &pid()).0;
    let reward_vault = Pubkey::find_program_address(&[b"reward_vault", config.as_ref()], &pid()).0;

    let mut data = disc("initialize");
    data.extend_from_slice(&min_lock.to_le_bytes());
    let ix = Instruction::new_with_bytes(pid(), &data, vec![
        AccountMeta::new(admin.pubkey(), true),
        AccountMeta::new(config, false),
        AccountMeta::new_readonly(stake_mint, false),
        AccountMeta::new_readonly(reward_mint, false),
        AccountMeta::new(stake_vault, false),
        AccountMeta::new(reward_vault, false),
        AccountMeta::new_readonly(tok(), false),
        AccountMeta::new_readonly(system_program::id(), false),
        AccountMeta::new_readonly(pid(), false),
        AccountMeta::new_readonly(program_data, false),
    ]);
    send(&mut svm, &[ix], &admin, &[&admin]).unwrap();
    let admin_reward_ata = create_token_account(&mut svm, &admin, &reward_mint, &admin.pubkey());
    mint_to(&mut svm, &admin, &reward_mint, &admin_reward_ata, 10_000_000_000);
    Env { svm, admin, stake_mint, reward_mint, config, stake_vault, reward_vault, admin_reward_ata }
}

impl Env {
    fn set_paused(&mut self, signer: &Keypair, paused: bool) -> Result<(), String> {
        let mut data = disc("set_paused");
        data.push(paused as u8);
        let ix = Instruction::new_with_bytes(pid(), &data, vec![
            AccountMeta::new_readonly(signer.pubkey(), true),
            AccountMeta::new(self.config, false),
        ]);
        send(&mut self.svm, &[ix], signer, &[signer])
    }
    fn fund(&mut self, signer: &Keypair, from: Pubkey, amount: u64, duration: i64) -> Result<(), String> {
        let mut data = disc("fund_rewards");
        data.extend_from_slice(&amount.to_le_bytes());
        data.extend_from_slice(&duration.to_le_bytes());
        let ix = Instruction::new_with_bytes(pid(), &data, vec![
            AccountMeta::new_readonly(signer.pubkey(), true),
            AccountMeta::new(self.config, false),
            AccountMeta::new_readonly(self.reward_mint, false),
            AccountMeta::new(self.reward_vault, false),
            AccountMeta::new(from, false),
            AccountMeta::new_readonly(tok(), false),
        ]);
        send(&mut self.svm, &[ix], signer, &[signer])
    }
    fn set_funder(&mut self, signer: &Keypair, funder: Pubkey) -> Result<(), String> {
        let mut data = disc("set_funder");
        data.extend_from_slice(funder.as_ref());
        let ix = Instruction::new_with_bytes(pid(), &data, vec![
            AccountMeta::new_readonly(signer.pubkey(), true),
            AccountMeta::new(self.config, false),
        ]);
        send(&mut self.svm, &[ix], signer, &[signer])
    }
    fn new_user(&mut self, tokens: u64) -> (Keypair, Pubkey, Pubkey) {
        let u = Keypair::new();
        self.svm.airdrop(&u.pubkey(), 10_000_000_000).unwrap();
        let st = create_token_account(&mut self.svm, &self.admin, &self.stake_mint, &u.pubkey());
        let rw = if self.stake_mint == self.reward_mint { st } else { create_token_account(&mut self.svm, &self.admin, &self.reward_mint, &u.pubkey()) };
        let admin = self.admin.insecure_clone();
        mint_to(&mut self.svm, &admin, &self.stake_mint, &st, tokens);
        (u, st, rw)
    }
    fn stake(&mut self, u: &Keypair, from: Pubkey, amount: u64) -> Result<(), String> {
        let mut data = disc("stake");
        data.extend_from_slice(&amount.to_le_bytes());
        let ix = Instruction::new_with_bytes(pid(), &data, vec![
            AccountMeta::new(u.pubkey(), true),
            AccountMeta::new(self.config, false),
            AccountMeta::new(user_pda(&self.config, &u.pubkey()), false),
            AccountMeta::new_readonly(self.stake_mint, false),
            AccountMeta::new(self.stake_vault, false),
            AccountMeta::new(from, false),
            AccountMeta::new_readonly(tok(), false),
            AccountMeta::new_readonly(system_program::id(), false),
        ]);
        send(&mut self.svm, &[ix], u, &[u])
    }
    fn unstake_like(&mut self, name: &str, u: &Keypair, to: Pubkey, amount: Option<u64>) -> Result<(), String> {
        let mut data = disc(name);
        if let Some(a) = amount { data.extend_from_slice(&a.to_le_bytes()); }
        let ix = Instruction::new_with_bytes(pid(), &data, vec![
            AccountMeta::new_readonly(u.pubkey(), true),
            AccountMeta::new(self.config, false),
            AccountMeta::new(user_pda(&self.config, &u.pubkey()), false),
            AccountMeta::new_readonly(self.stake_mint, false),
            AccountMeta::new(self.stake_vault, false),
            AccountMeta::new(to, false),
            AccountMeta::new_readonly(tok(), false),
        ]);
        send(&mut self.svm, &[ix], u, &[u])
    }
    fn unstake(&mut self, u: &Keypair, to: Pubkey, amount: u64) -> Result<(), String> { self.unstake_like("unstake", u, to, Some(amount)) }
    fn emergency(&mut self, u: &Keypair, to: Pubkey) -> Result<(), String> { self.unstake_like("emergency_withdraw", u, to, None) }
    fn claim(&mut self, u: &Keypair, to: Pubkey) -> Result<(), String> {
        let ix = Instruction::new_with_bytes(pid(), &disc("claim"), vec![
            AccountMeta::new_readonly(u.pubkey(), true),
            AccountMeta::new(self.config, false),
            AccountMeta::new(user_pda(&self.config, &u.pubkey()), false),
            AccountMeta::new_readonly(self.reward_mint, false),
            AccountMeta::new(self.reward_vault, false),
            AccountMeta::new(to, false),
            AccountMeta::new_readonly(tok(), false),
        ]);
        send(&mut self.svm, &[ix], u, &[u])
    }
    fn reclaim(&mut self, signer: &Keypair, to: Pubkey) -> Result<(), String> {
        let ix = Instruction::new_with_bytes(pid(), &disc("reclaim_rewards"), vec![
            AccountMeta::new_readonly(signer.pubkey(), true),
            AccountMeta::new(self.config, false),
            AccountMeta::new_readonly(self.reward_mint, false),
            AccountMeta::new(self.reward_vault, false),
            AccountMeta::new(to, false),
            AccountMeta::new_readonly(tok(), false),
        ]);
        send(&mut self.svm, &[ix], signer, &[signer])
    }
}

#[test]
fn only_the_upgrade_authority_can_create_the_pool() {
    let mut svm = LiteSVM::new();
    set_time(&mut svm, T0);
    let owner = Keypair::new();
    let program_data = deploy_upgradeable(&mut svm, &owner.pubkey());
    let attacker = Keypair::new();
    svm.airdrop(&attacker.pubkey(), 10_000_000_000).unwrap();
    let mint = create_mint(&mut svm, &attacker);
    let config = Pubkey::find_program_address(&[b"config", mint.as_ref()], &pid()).0;
    let sv = Pubkey::find_program_address(&[b"stake_vault", config.as_ref()], &pid()).0;
    let rv = Pubkey::find_program_address(&[b"reward_vault", config.as_ref()], &pid()).0;
    let mut data = disc("initialize");
    data.extend_from_slice(&0i64.to_le_bytes());
    let ix = Instruction::new_with_bytes(pid(), &data, vec![
        AccountMeta::new(attacker.pubkey(), true), AccountMeta::new(config, false),
        AccountMeta::new_readonly(mint, false), AccountMeta::new_readonly(mint, false),
        AccountMeta::new(sv, false), AccountMeta::new(rv, false),
        AccountMeta::new_readonly(tok(), false), AccountMeta::new_readonly(system_program::id(), false),
        AccountMeta::new_readonly(pid(), false), AccountMeta::new_readonly(program_data, false),
    ]);
    assert!(send(&mut svm, &[ix], &attacker, &[&attacker]).unwrap_err().contains("Unauthorized"));
}

fn near(a: u64, b: u64, tol: u64) -> bool { a.abs_diff(b) <= tol }

#[test]
fn starts_paused_and_only_admin_can_unpause() {
    let mut e = setup(false, 0);
    let (u, st, _) = e.new_user(1_000);
    assert!(e.stake(&u, st, 100).unwrap_err().contains("Paused"));
    let stranger = Keypair::new();
    e.svm.airdrop(&stranger.pubkey(), 1_000_000_000).unwrap();
    assert!(e.set_paused(&stranger, false).is_err());
    let admin = e.admin.insecure_clone();
    e.set_paused(&admin, false).unwrap();
    e.stake(&u, st, 100).unwrap();
    assert_eq!(balance(&e.svm, &e.stake_vault), 100);
}

#[test]
fn rewards_are_shared_pro_rata_over_time() {
    let mut e = setup(false, 0);
    let admin = e.admin.insecure_clone();
    e.set_paused(&admin, false).unwrap();
    let (a, a_st, a_rw) = e.new_user(1_000);
    let (b, b_st, b_rw) = e.new_user(1_000);
    e.stake(&a, a_st, 100).unwrap();
    e.fund(&admin, e.admin_reward_ata, 1_000_000, 100).unwrap(); // 10_000 per second for 100 s
    set_time(&mut e.svm, T0 + 50);
    e.stake(&b, b_st, 100).unwrap();
    set_time(&mut e.svm, T0 + 200); // well past the end: emission stops at T0+100
    e.claim(&a, a_rw).unwrap();
    e.claim(&b, b_rw).unwrap();
    let (ra, rb) = (balance(&e.svm, &a_rw), balance(&e.svm, &b_rw));
    assert!(near(ra, 750_000, 2), "A got {ra}");
    assert!(near(rb, 250_000, 2), "B got {rb}");
    assert!(ra + rb <= 1_000_000);
    // nothing left to claim
    assert!(e.claim(&a, a_rw).unwrap_err().contains("NothingToClaim"));
}

#[test]
fn lock_is_enforced_and_unstake_works_while_paused() {
    let mut e = setup(false, 3600);
    let admin = e.admin.insecure_clone();
    e.set_paused(&admin, false).unwrap();
    let (u, st, _) = e.new_user(1_000);
    e.stake(&u, st, 400).unwrap();
    assert!(e.unstake(&u, st, 100).unwrap_err().contains("StillLocked"));
    set_time(&mut e.svm, T0 + 3600);
    e.set_paused(&admin, true).unwrap();
    e.unstake(&u, st, 100).unwrap();
    assert_eq!(balance(&e.svm, &st), 700);
    assert!(e.unstake(&u, st, 1_000).unwrap_err().contains("InsufficientStake"));
}

#[test]
fn emergency_withdraw_ignores_lock_and_pause() {
    let mut e = setup(false, 86_400);
    let admin = e.admin.insecure_clone();
    e.set_paused(&admin, false).unwrap();
    let (u, st, _) = e.new_user(1_000);
    e.stake(&u, st, 1_000).unwrap();
    e.set_paused(&admin, true).unwrap();
    e.emergency(&u, st).unwrap();
    assert_eq!(balance(&e.svm, &st), 1_000);
    assert_eq!(balance(&e.svm, &e.stake_vault), 0);
}

#[test]
fn only_admin_can_fund_and_claims_are_blocked_while_paused() {
    let mut e = setup(false, 0);
    let admin = e.admin.insecure_clone();
    e.set_paused(&admin, false).unwrap();
    let (u, st, rw) = e.new_user(1_000);
    // a user cannot fund (has_one admin) even with their own tokens
    let admin2 = e.admin.insecure_clone();
    mint_to(&mut e.svm, &admin2, &e.reward_mint, &rw, 500);
    assert!(e.fund(&u, rw, 500, 10).unwrap_err().contains("Unauthorized"));
    e.stake(&u, st, 10).unwrap();
    e.fund(&admin, e.admin_reward_ata, 1_000, 10).unwrap();
    set_time(&mut e.svm, T0 + 5);
    e.set_paused(&admin, true).unwrap();
    assert!(e.claim(&u, rw).unwrap_err().contains("Paused"));
}

#[test]
fn admin_can_only_reclaim_unowed_rewards_after_the_end() {
    let mut e = setup(false, 0);
    let admin = e.admin.insecure_clone();
    e.set_paused(&admin, false).unwrap();
    let (u, st, rw) = e.new_user(1_000);
    e.fund(&admin, e.admin_reward_ata, 1_000_000, 100).unwrap();
    // nobody staked for the first 40 s: those rewards are never emitted
    set_time(&mut e.svm, T0 + 40);
    e.stake(&u, st, 100).unwrap();
    assert!(e.reclaim(&admin, e.admin_reward_ata).unwrap_err().contains("RewardsStillStreaming"));
    set_time(&mut e.svm, T0 + 100);
    let before = balance(&e.svm, &e.admin_reward_ata);
    e.reclaim(&admin, e.admin_reward_ata).unwrap();
    let reclaimed = balance(&e.svm, &e.admin_reward_ata) - before;
    assert!(near(reclaimed, 400_000, 2), "reclaimed {reclaimed}");
    // the user's 600_000 is still there and claimable
    e.claim(&u, rw).unwrap();
    assert!(near(balance(&e.svm, &rw), 600_000, 2));
    // staked tokens were never touched
    assert_eq!(balance(&e.svm, &e.stake_vault), 100);
}

#[test]
fn same_mint_for_stake_and_rewards_keeps_vaults_separate() {
    let mut e = setup(true, 0);
    let admin = e.admin.insecure_clone();
    e.set_paused(&admin, false).unwrap();
    let (u, st, rw) = e.new_user(1_000);
    e.stake(&u, st, 1_000).unwrap();
    e.fund(&admin, e.admin_reward_ata, 5_000, 50).unwrap();
    set_time(&mut e.svm, T0 + 50);
    e.claim(&u, rw).unwrap();
    assert!(near(balance(&e.svm, &st), 5_000, 1));
    assert_eq!(balance(&e.svm, &e.stake_vault), 1_000);
    e.unstake(&u, st, 1_000).unwrap();
    assert!(near(balance(&e.svm, &st), 6_000, 1));
}

#[test]
fn cannot_promise_more_than_the_vault_holds() {
    let mut e = setup(false, 0);
    let admin = e.admin.insecure_clone();
    e.set_paused(&admin, false).unwrap();
    // amount smaller than duration -> rate rounds to 0 -> refused
    assert!(e.fund(&admin, e.admin_reward_ata, 50, 100).unwrap_err().contains("RewardRateTooLow"));
    // re-funding mid-stream adds the leftover, and the total stays backed by the vault
    let (u, st, rw) = e.new_user(1_000);
    e.stake(&u, st, 100).unwrap();
    e.fund(&admin, e.admin_reward_ata, 1_000, 10).unwrap();
    set_time(&mut e.svm, T0 + 5);
    e.fund(&admin, e.admin_reward_ata, 1_000, 10).unwrap();
    set_time(&mut e.svm, T0 + 100);
    e.claim(&u, rw).unwrap();
    let got = balance(&e.svm, &rw);
    assert!(near(got, 2_000, 2), "got {got}");
    assert!(balance(&e.svm, &e.reward_vault) <= 2);
}

#[test]
fn funder_bot_can_only_add_rewards() {
    let mut e = setup(false, 0);
    let admin = e.admin.insecure_clone();
    e.set_paused(&admin, false).unwrap();
    let bot = Keypair::new();
    e.svm.airdrop(&bot.pubkey(), 1_000_000_000).unwrap();
    let bot_ata = create_token_account(&mut e.svm, &admin, &e.reward_mint, &bot.pubkey());
    mint_to(&mut e.svm, &admin, &e.reward_mint, &bot_ata, 200_000_000);
    // not a funder yet
    assert!(e.fund(&bot, bot_ata, 1_000, 10).unwrap_err().contains("Unauthorized"));
    // only the admin can appoint it
    assert!(e.set_funder(&bot, bot.pubkey()).is_err());
    e.set_funder(&admin, bot.pubkey()).unwrap();
    let (u, st, rw) = e.new_user(1_000);
    e.stake(&u, st, 100).unwrap();
    e.fund(&bot, bot_ata, 100_000_000, 86_400).unwrap();
    // the bot can never stream faster than a day
    assert!(e.fund(&bot, bot_ata, 10, 10).unwrap_err().contains("InvalidDuration"));
    // the bot cannot pause, reclaim or appoint someone else
    assert!(e.set_paused(&bot, true).is_err());
    assert!(e.set_funder(&bot, Pubkey::new_unique()).is_err());
    set_time(&mut e.svm, T0 + 86_400 + 1);
    assert!(e.reclaim(&bot, bot_ata).is_err());
    e.claim(&u, rw).unwrap();
    assert!(near(balance(&e.svm, &rw), 1_157 * 86_400, 1));
    // admin still funds; disabling the funder locks the bot out
    e.fund(&admin, e.admin_reward_ata, 100, 10).unwrap();
    e.set_funder(&admin, Pubkey::default()).unwrap();
    assert!(e.fund(&bot, bot_ata, 1_000, 10).unwrap_err().contains("Unauthorized"));
}

#[test]
fn a_dust_staker_alone_cannot_break_the_maths_for_others() {
    // classic accumulator attack: 1 raw unit staked alone while a big stream runs
    let mut e = setup(false, 0);
    let admin = e.admin.insecure_clone();
    e.set_paused(&admin, false).unwrap();
    let big: u64 = 1_000_000_000_000_000; // 1e15 raw units (1B tokens, 6 decimals)
    let ata = e.admin_reward_ata;
    mint_to(&mut e.svm, &admin, &e.reward_mint, &ata, big);
    let (dust, dst, drw) = e.new_user(1);
    e.stake(&dust, dst, 1).unwrap();
    e.fund(&admin, ata, big, 100).unwrap();
    set_time(&mut e.svm, T0 + 50);
    let (whale, wst, wrw) = e.new_user(big);
    e.stake(&whale, wst, big).unwrap();
    set_time(&mut e.svm, T0 + 100);
    e.claim(&whale, wrw).unwrap();
    e.claim(&dust, drw).unwrap();
    e.unstake(&whale, wst, big / 2).unwrap();
    e.emergency(&whale, wst).unwrap();
    assert_eq!(balance(&e.svm, &wst), big);
    assert!(balance(&e.svm, &wrw) > 0 && balance(&e.svm, &drw) > 0);
}
