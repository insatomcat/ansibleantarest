# Hardening

A blank VM, a few minutes, and an Antares-Web reachable on the internet with 22 and 80 open is exactly what this playbook makes easy, so the `hardening` role runs right after the base configuration and before anything is deployed. Five independent blocks, each switched on its own:

```yaml
hardening_enabled: true               # roles/antares_defaults/defaults/main/hardening.yml
hardening_firewall_enabled: false     # off: a cloud VM already has a security group
hardening_fail2ban_enabled: true
hardening_ssh_enabled: true
hardening_unattended_upgrades: true
hardening_journal_persistent: true
```

Everything is on except the firewall, which duplicates what a cloud provider's security group already does, and two filters that have to agree is one more place for a rule to go missing. Turn it on for a machine with nothing in front of it, and in particular for a Slurm front-end on a network you do not control: its NFS export uses `no_root_squash`.

**Firewall.** An nftables input chain with a drop policy, in a table of its own (`inet antares_fw`) loaded by `antares-firewall.service`. `/etc/nftables.conf` is left alone: what both families ship in it starts with `flush ruleset`, which would take the rules netavark writes for the containers down with it. On a RHEL rebuild, firewalld is masked whether this is on or off, see below.

```bash
nft list table inet antares_fw
systemctl reload antares-firewall     # re-apply after an edit
```

Open to the world: the ports sshd actually listens on, read from `sshd -T` rather than assumed to be 22 (the inventory of this repository has a machine answering on 2222), and the interface ports on an `antares_web` machine. Open to the other machines of the inventory, on every port: that is what keeps NFS, Slurm and the job submission path working without exposing 2049 or 6817 to the internet, and it is the reason the NFS export with `no_root_squash` on the front-end stops being a hole. Add anything else with `hardening_firewall_extra_tcp_ports` or `hardening_firewall_extra_sources`.

That "open to the other machines of the inventory" is also what the monitoring half relies on: the exporters listen on every interface and are scraped by the web machine, so they need no rule of their own and are dropped for everyone else. `verify.yml` probes them from the controller, which is outside the trusted set, and expects nothing to answer. See [Monitoring](monitoring.md).

Two things this deliberately does not do. It does not filter the `forward` hook, because a packet aimed at a published container port is DNATed and routed, never traverses `input`, and a forward chain with a drop policy would take every container down, outgoing traffic included: what the containers expose is decided by their `PublishPort`, and the two that are not meant to be public (adminer, the accounting MariaDB) are bound to `127.0.0.1` in their units. And it accepts everything arriving on `podman*` interfaces, because aardvark-dns listens on the bridge address, which belongs to the host: without that rule, container name resolution dies and the backend never finds `postgresql`.

The peer addresses come from the gathered facts, so a `--limit` run on an expired fact cache would leave them out; the role says which machines it could not resolve rather than silently isolating them.

**fail2ban.** The `sshd` jail, plus a jail on the Antares-Web login form: the API answers 401 on a wrong password and nginx logs the request. Both read the journal (`backend = systemd`) because the Ubuntu images ship no rsyslog at all, so a jail pointed at `/var/log/auth.log` starts dead, which is incidentally the state a stock Debian fail2ban is in. On the RedHat family the packages come from EPEL, which splits them: `fail2ban-server` and `fail2ban-systemd` are installed, deliberately not the `fail2ban` metapackage, which drags in `fail2ban-firewalld` and its `banaction = firewalld`.

```bash
fail2ban-client status
fail2ban-client status antares-web-login
fail2ban-client set antares-web-login unbanip 203.0.113.7
```

Bans are dropped in the `prerouting` hook at priority `raw`, not in `input` like the stock actions. This is the difference everybody meets with docker and ufw: an input-hook ban is reported by the jail and does nothing at all, since the traffic to a container is DNATed at `nat prerouting` and routed onward. Dropping earlier catches the containers and the host alike. The machines of the inventory are never banned.

**SSH.** A drop-in in `/etc/ssh/sshd_config.d/`: no password authentication, no root password login, `MaxAuthTries 4`, a 30 second grace time, no X11 forwarding. TCP forwarding stays on, since the documentation reaches adminer and the Keycloak console through `ssh -L`. Before closing the password, the role checks that the account Ansible connects with has a non-empty `authorized_keys` and stops if it does not, rather than leaving an unreachable machine; set `hardening_ssh_disable_password_auth: false` if the machine authenticates through something else, an SSH certificate authority for instance. The resulting configuration is checked with `sshd -t`, and the drop-in is removed again if sshd refuses it.

**Unattended upgrades.** On the Debian family, `unattended-upgrades` enabled on the origins the distribution already restricts to the security pocket. On the RedHat family, `dnf-automatic` with `upgrade_type = security` and its timer enabled, which is the same policy with different machinery. Neither reboots on its own: a study can run for hours and a machine that reboots in the middle of one loses it. `/var/run/reboot-required` and `dnf needs-restarting -r` say when one is due.

**Journal.** `Storage=persistent` and `SystemMaxUse=500M` (`hardening_journal_max_use`) in `/etc/systemd/journald.conf.d/10-antares.conf`, so that the journal is in `/var/log/journal` instead of the `/run` tmpfs it is wiped from at every reboot. This is not a detail of taste: the bans, the backend's crash loops, the container logs (`LogDriver=journald` in every quadlet) and the report of the unattended updates all live there and nowhere else on the Debian family, which ships no rsyslog, so a machine that reboots after a kernel update loses the log of whatever led to it. The default is `auto` on both families, which means "persistent if `/var/log/journal` exists" and therefore leaves the answer to whoever built the image: Ubuntu ships the directory, the Debian and EL cloud images do not. A drop-in rather than `journald.conf` itself, which the cloud images write their own settings into. The block runs before the others, since applying it restarts `systemd-journald` and the jails read the journal.

```bash
journalctl --disk-usage
journalctl --list-boots        # more than one line: it is persistent
```

**firewalld (RedHat family).** The RHEL rebuilds boot with firewalld enabled and a default zone that accepts SSH and nothing else. Debian and Ubuntu ship no host filter, so `hardening_firewall_enabled: false` (the default: the cloud security group is enough) only meant the same thing on one family. firewalld is therefore stopped, disabled and **masked** whether our nftables table is on or not. `systemctl unmask firewalld` puts it back. Set `hardening_manage_firewalld: false` to be left alone with it.

**Secrets.** The role also reports the secrets of [Before production](../README.md#before-production) still holding the value this repository ships, admin/admin being a faster way in than any brute force. `hardening_fail_on_default_secrets` is on by default, so that is a failure naming the variables to set, not a message you can scroll past. Set it to false on a throwaway machine. Every secret is only asked about on the hosts that actually run the thing it belongs to, group by group: the Antares-Web, Keycloak and Grafana ones on `antares_web`, the accounting one on `slurm_frontend`. This role is the one part of `site.yml` that runs on `all`, so a compute node, or a `builder` host listed in the same inventory, is asked about nothing and holds nothing.

The bans do not depend on the firewall: fail2ban writes its own table, so it keeps working with `hardening_firewall_enabled: false`.

Each block can also be flipped for a run, or per host in the inventory:

```bash
ansible-playbook site.yml -e hardening_firewall_enabled=true     # this run only
ansible-playbook site.yml -e hardening_enabled=false             # none of it
```

