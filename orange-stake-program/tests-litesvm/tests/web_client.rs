//! Runs the instructions built by the web page's staking-core.js (through Node) on LiteSVM,
//! to prove the page talks to the program correctly. Needs node and `npm i @solana/web3.js@1.98.4` in this folder.
use litesvm::LiteSVM;
use solana_sdk::{account::Account, bpf_loader_upgradeable, clock::Clock, instruction::{AccountMeta, Instruction},
    pubkey::Pubkey, signature::{Keypair, Signer}, transaction::Transaction};
use std::str::FromStr;

const PID: &str = "FJCVCn2714BjcYCBKoqL2v6kQvfYPoHtLghnEPeHRm79";

fn ixs(v: &serde_json::Value) -> Vec<Instruction> {
    v.as_array().unwrap().iter().map(|i| Instruction {
        program_id: Pubkey::from_str(i["program"].as_str().unwrap()).unwrap(),
        data: i["data"].as_array().unwrap().iter().map(|x| x.as_u64().unwrap() as u8).collect(),
        accounts: i["keys"].as_array().unwrap().iter().map(|k| AccountMeta {
            pubkey: Pubkey::from_str(k[0].as_str().unwrap()).unwrap(), is_signer: k[1].as_bool().unwrap(), is_writable: k[2].as_bool().unwrap() }).collect(),
    }).collect()
}
fn send(svm: &mut LiteSVM, ix: Vec<Instruction>, payer: &Keypair, extra: &[&Keypair]) {
    svm.expire_blockhash();
    let mut s: Vec<&Keypair> = vec![payer]; s.extend_from_slice(extra);
    let tx = Transaction::new_signed_with_payer(&ix, Some(&payer.pubkey()), &s, svm.latest_blockhash());
    if let Err(e) = svm.send_transaction(tx) { panic!("{:?}\n{}", e.err, e.meta.logs.join("\n")) }
}
fn bal(svm: &LiteSVM, k: &str) -> u64 { let a = svm.get_account(&Pubkey::from_str(k).unwrap()).unwrap(); u64::from_le_bytes(a.data[64..72].try_into().unwrap()) }
fn set_time(svm: &mut LiteSVM, t: i64) { let mut c: Clock = svm.get_sysvar(); c.unix_timestamp = t; svm.set_sysvar(&c); }

#[test]
fn web_page_instructions_work_end_to_end() {
    let pid = Pubkey::from_str(PID).unwrap();
    let mut svm = LiteSVM::new();
    set_time(&mut svm, 1_800_000_000);
    let (admin, user, mint) = (Keypair::new(), Keypair::new(), Keypair::new());
    svm.airdrop(&admin.pubkey(), 100_000_000_000).unwrap();
    svm.airdrop(&user.pubkey(), 10_000_000_000).unwrap();
    let elf = std::fs::read("../target/deploy/orange_stake.so").unwrap();
    let pd = Pubkey::find_program_address(&[pid.as_ref()], &bpf_loader_upgradeable::id()).0;
    let mut d = vec![3u8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]; d.extend_from_slice(admin.pubkey().as_ref()); d.extend_from_slice(&elf);
    let l = svm.minimum_balance_for_rent_exemption(d.len());
    svm.set_account(pd, Account { lamports: l, data: d, owner: bpf_loader_upgradeable::id(), executable: false, rent_epoch: 0 }).unwrap();
    let mut p = vec![2u8, 0, 0, 0]; p.extend_from_slice(pd.as_ref());
    svm.set_account(pid, Account { lamports: 10_000_000, data: p, owner: bpf_loader_upgradeable::id(), executable: true, rent_epoch: 0 }).unwrap();

    let args = serde_json::json!({ "admin": admin.pubkey().to_string(), "user": user.pubkey().to_string(),
        "mint": mint.pubkey().to_string(), "rent": svm.minimum_balance_for_rent_exemption(82) });
    let out = std::process::Command::new("node").arg("gen.js").arg(args.to_string()).output().unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let j: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    let a = &j["addr"];

    send(&mut svm, ixs(&j["create_mint"]), &admin, &[&mint]);
    send(&mut svm, ixs(&j["atas"]), &admin, &[]);
    send(&mut svm, ixs(&j["mint_admin"]), &admin, &[]);
    send(&mut svm, ixs(&j["mint_user"]), &admin, &[]);
    send(&mut svm, ixs(&j["initialize"]), &admin, &[]);
    send(&mut svm, ixs(&j["unpause"]), &admin, &[]);
    send(&mut svm, ixs(&j["fund"]), &admin, &[]);
    send(&mut svm, ixs(&j["stake"]), &user, &[]);
    assert_eq!(bal(&svm, a["stake_vault"].as_str().unwrap()), 100_000_000);
    set_time(&mut svm, 1_800_000_500);
    send(&mut svm, ixs(&j["claim"]), &user, &[]);
    assert_eq!(bal(&svm, a["user_ata"].as_str().unwrap()), 400_000_000 + 500_000_000);
    set_time(&mut svm, 1_800_000_600);
    send(&mut svm, ixs(&j["unstake"]), &user, &[]);
    send(&mut svm, ixs(&j["pause"]), &admin, &[]);
    send(&mut svm, ixs(&j["emergency"]), &user, &[]);
    assert_eq!(bal(&svm, a["stake_vault"].as_str().unwrap()), 0);
    assert!(bal(&svm, a["user_ata"].as_str().unwrap()) >= 1_000_000_000);
}
