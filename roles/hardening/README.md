# hardening

Runs on every machine, right after `common` and before anything is deployed:
the window where a blank VM is reachable with 22 and 80 open is exactly what
this playbook makes easy to create.

Five independent blocks, each with its own switch, plus two housekeeping ones.
The order in `main.yml` is deliberate.

| Task file | What it does |
|---|---|
| `facts.yml` | Collects what the rules have to let through: the ports sshd really listens on (from `sshd -T`), and the addresses of the other machines of the inventory |
| `journal.yml` | `Storage=persistent`. First, because it restarts `systemd-journald` and the jails read the journal |
| `firewall.yml` | The `inet antares_fw` nftables table, loaded by `antares-firewall.service`. `/etc/nftables.conf` is left alone |
| `firewalld.yml` | Masks firewalld on the RedHat family, so that "no host firewall" means the same thing on both. Skipped entirely with `hardening_manage_firewalld: false`, and the `podman` role then trusts the container bridges in it |
| `fail2ban.yml` | The `sshd` jail and a jail on the Antares-Web login form, both reading the journal, both banning in `prerouting` |
| `ssh.yml` | A drop-in in `/etc/ssh/sshd_config.d/`, checked with `sshd -t` and removed again if sshd refuses it |
| `updates.yml` | `unattended-upgrades` or `dnf-automatic`, security pocket only, no automatic reboot |
| `secrets.yml` | Reports, or refuses, the shipped secrets still in place |

**What the role will not do.** It never closes password authentication without
first finding a non-empty `authorized_keys` on the account Ansible connects
with, and it never filters the `forward` hook, which would take every container
down. Both are load-bearing, see [Hardening](../../docs/hardening.md) for the
reasoning and for the operator-facing switches.

The peer addresses come from gathered facts: a `--limit` run on a stale fact
cache would leave machines out, so the role says which ones it could not
resolve instead of silently isolating them.
