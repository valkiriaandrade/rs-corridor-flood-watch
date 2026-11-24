# S2iD export VM (Brazil)

> Not in use: the export currently comes from the project PC (`scripts/s2id_export.ps1`, see the runbook). This VM
> is the alternative if the PC stops being switched on. With it, the 06:00/18:00 UTC exports keep the data under a day old.

S2iD (`s2id.mi.gov.br`) answers only IP addresses located in Brazil. GitHub's runners are abroad and get the page
"Acesso bloqueado por localização geográfica" (seen 2026-11-17), so the daily S2iD export cannot run in the
forecast workflow. A small VM in a Brazilian cloud region does only that export:

```
VM in São Paulo (cron 06:00 and 18:00 UTC)                GitHub Actions (daily forecast, 20:00 UTC)
  scripts/s2id_vm/export.sh                                 restores the CSV from branch `s2id`
  python -m floodwatch.official_records export-s2id   ->    FLOODWATCH_S2ID=file: loads it if it is < 36 h old
  force-push CSV + provenance to branch `s2id`              (older: "S2iD export failed: ... h old" in the log)
```

The VM runs the code of `origin/main` at every export, so it needs no maintenance when the code changes. It writes
only to the branch `s2id` (a single force-pushed commit, like `archive`).

## Setup (Oracle Cloud Always Free, about 20 minutes)

Any Linux VM in Brazil works (AWS `sa-east-1`, Google `southamerica-east1`, Azure Brazil South). Oracle is used here
because its Always Free tier covers this VM at no cost.

1. **Account.** Sign up at <https://cloud.oracle.com>. Choose **Brazil East (São Paulo)** as the home region:
   Always Free resources exist only in the home region, and it cannot be changed later. A card is asked for
   verification; Always Free resources are not charged.
2. **VM.** Compute → Instances → Create instance.
   - Image: Canonical Ubuntu 24.04.
   - Shape: Ampere `VM.Standard.A1.Flex` with 1 OCPU / 6 GB (Always Free). If São Paulo has no A1 capacity, use
     `VM.Standard.E2.1.Micro` (1 GB; `setup.sh` adds swap for Chromium).
   - SSH keys: "Generate a key pair for me" and download the private key.
   - Create, then copy the instance's public IP.
3. **Deploy key** (lets the VM push the export to this repository, and nothing else on your account).
   On your computer: `ssh -i <downloaded key> ubuntu@<public IP>`, then on the VM:
   ```bash
   ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 && cat ~/.ssh/id_ed25519.pub
   ```
   On GitHub: repository → Settings → Deploy keys → Add deploy key, paste the line, tick **Allow write access**.
4. **Install** (still on the VM):
   ```bash
   curl -fsSLO https://raw.githubusercontent.com/valkiriaandrade/rs-corridor-flood-watch/main/scripts/s2id_vm/setup.sh
   bash setup.sh
   ```
   It installs git, Python, pandas, Playwright and Chromium, clones the repository, schedules the export (cron
   06:00 and 18:00 UTC) and runs a first export. The last line must be `pushed to branch s2id`.
5. **Check.** The branch `s2id` appears on GitHub; the next forecast run logs `S2iD: <n> corridor flood records`.

## Operation

- Log on the VM: `~/s2id_export.log`. Manual export: `bash ~/rs-corridor-flood-watch/scripts/s2id_vm/export.sh`.
- If the VM stops (deleted, reclaimed), the forecast keeps running; its log says `S2iD export failed: no file from the
  Brazil VM` or `... h old`, and the verification simply receives no new S2iD records until the VM is back.
- Oracle may reclaim Always Free instances that stay idle for 7 days on a free-tier account. Converting the account
  to Pay As You Go (still no charge within the Always Free limits) avoids this.
- Removing it: delete the instance in Oracle and the deploy key on GitHub.
