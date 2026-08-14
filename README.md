# Ansible deployment of Antares-Web (optional Slurm cluster)

This Ansible playbook automates the "Basic Antares-Web and Slurm deployment" procedure (see `antares-slurm-1.3.pdf`), updated for current releases of
[AntaREST](https://github.com/AntaresSimulatorTeam/AntaREST) and
[Antares Simulator](https://github.com/AntaresSimulatorTeam/Antares_Simulator).

Three types of machines are used:

| Inventory group     | Role |
|---|---|
| `antares_web`       | Builds and runs Antares-Web (podman + quadlet, TLS optional) |
| `slurm_frontend`    | Slurm controller, accounting database, NFS server for `/home` |
| `slurm_compute`     | Compute nodes, mounting the shared `/home` via NFS |

Slurm is optional: with `slurm_enabled: false` only Antares-Web is deployed and studies run with the local solver on the web machine. When Slurm is enabled, both launchers are shown in the UI and `antarest_default_launcher` selects the default one.

## Quick start

```bash
ansible-galaxy collection install -r requirements.yml

# edit the inventory and variables
$EDITOR inventory/hosts.yml
$EDITOR group_vars/all.yml      # at least set the secrets (see below)

ansible-playbook site.yml
```

The interface will then be available at `http://<antares_web>/` (default credentials: `admin` / `admin`), or `https://` once TLS is on (see below). The machines are firewalled, fail2banned and their sshd hardened along the way, see "Hardening".

Without a cluster:

```bash
ansible-playbook site.yml -e slurm_enabled=false
```

The inventory should then contain only the `antares_web` group.

## Example inventories

`inventory/hosts.yml` is the default (set in `ansible.cfg`) and shows the full three-group layout. Two ready-to-copy inventories cover the simple cases, each carrying the options that are worth setting per machine, commented:

| File | For |
|---|---|
| `inventory/antares-web.example.yml` | one VM running Antares-Web, no cluster |
| `inventory/build.example.yml` | one VM that only builds the artefacts |

Both assume what a fresh Debian/Ubuntu cloud VM gives you: SSH open, an `ubuntu`, `admin` or `debian` account, `sudo` to root. Nothing else has to be installed, podman included.

**Deploy a working Antares-Web.** Edit `ansible_host`, `ansible_user` and the three secrets, then:

```bash
ansible-playbook -i inventory/antares-web.example.yml site.yml -K
```

The interface answers on `http://<the machine>/` with `admin` / `admin`. `-K` asks for the sudo password; drop it if the account has `NOPASSWD`.

**Build the artefacts once, on a builder.** Edit `ansible_host`, `ansible_user`, and `antares_build_root` if `/data` is not where the disk space is:

```bash
ansible-playbook -i inventory/build.example.yml build.yml -K
```

This produces `./artifacts` on the controller. Deploy it on as many machines as you like without ever building again:

```bash
ansible-playbook -i inventory/antares-web.example.yml site.yml \
    -e antarest_image_source=archive -K
```

The builder and the targets must agree on `antares_uid`/`antares_gid` (baked into the image) and share the same CPU architecture. See "Build once, deploy everywhere" below.

One thing to know when editing these files: settings written **under a host** override `group_vars/all.yml`, while a `vars:` block on a group does *not*, since playbook `group_vars` outrank inventory group vars. That is why everything per-deployment sits on the host in the examples. Anything shared by several machines belongs in `group_vars/all.yml`.

## Requirements

- A Debian-family or RHEL-compatible distribution on all target machines (see supported distros below), root access via `sudo`, and Python 3 installed.
- The `antares_web` machine needs Internet access (container images, npm and Python packages, solver binaries).
- The Slurm frontend also downloads solvers from GitHub.
- A free UID/GID that is identical on all machines for the `antares` account: `9000` by default. The playbook will refuse to continue if the UID/GID are already taken.
- Ansible ≥ 2.15 on the control machine, and `ansible.posix` available.

### Supported distributions

Two families are supported: Debian (Debian and Ubuntu, `apt`) and RedHat (Oracle Linux and the other RHEL rebuilds, `dnf`). Every install goes through `ansible.builtin.package`, and everything that actually differs between the two (package names, service names, repositories) is resolved from `ansible_facts['os_family']` in one place per role, so no task exists twice.

```yaml
supported_distros:      # group_vars/all.yml
  - "Debian 12"
  - "Debian 13"
  - "Ubuntu 22"
  - "Ubuntu 24"
  - "OracleLinux 9"
  - "RedHat 9"
  - "Rocky 9"
  - "AlmaLinux 9"
  - "CentOS 9"
```

The playbook aborts on unsupported distros and prints the variable to extend. A rebuild of a supported major that is not in the list is usually fine to add. Set `distro_check_enabled: false` to disable the check entirely.

Podman comes from the distribution on both families and is recent enough everywhere: quadlet has been part of podman since 4.4, Debian 13 ships 5.x, Ubuntu 24.04 ships 4.9, and EL 9 has been on 4.4 or later since 9.2. The playbook checks the version and stops rather than writing units nothing would generate.

Important cluster note: use one distribution per cluster. Packaged Slurm versions differ (23.11 on Ubuntu 24.04, 24.11 on Debian 13, whatever OpenHPC currently ships on EL 9) and the daemons `slurmctld` / `slurmd` / `slurmdbd` interoperate only across certain major versions. The generated `slurm.conf` works for all of them, but do not mix a front-end on Debian 13 with compute nodes on Oracle Linux 9 in the same cluster. The `antares_web` machine is unaffected: it talks to the Slurm frontend only via SSH, so a Debian web server driving an Oracle Linux cluster is fine.

On the Debian family the dpkg lock is tolerated up to `apt_lock_timeout` seconds (default 300), because Ubuntu images often run `apt-daily` and `unattended-upgrades` on boot. Rather than being passed to every install, this is written to `/etc/apt/apt.conf.d/80-antares-lock-timeout`, so it also covers the apt commands the playbook does not run itself.

### What a RHEL-compatible target needs on top

Everything below is done by the playbook. It is listed because it changes the machine in ways worth knowing about.

| Topic | What happens |
|---|---|
| **Repositories** | The `common` role installs `dnf-plugins-core`, enables **CRB** (`ol9_codeready_builder` on Oracle Linux, `crb` on the other rebuilds) and **EPEL** (`ol9_developer_EPEL` on Oracle Linux, which the release package ships disabled, `epel` on the other rebuilds). Both are needed: `htop`, `fail2ban` and `certbot` come from EPEL, which is built against CRB. |
| **Slurm** | No EL 9 repository ships Slurm, neither the base repositories nor EPEL. It comes from **OpenHPC 3** instead (`slurm_repo: openhpc`, release rpm in `slurm_openhpc_release`). Package names carry an `-ohpc` suffix; `/etc/slurm`, the systemd units and the `slurm` account are where they are everywhere else. Set `slurm_repo: distro` if you install Slurm yourself. |
| **Solver binaries** | The Ubuntu 22.04 build of Antares Simulator is linked against glibc 2.35 and does not start on EL 9, which has 2.34. `antares_solver_os` therefore follows the family and picks the project's **Oracle Linux 8** build there. |
| **SELinux** | Left enforcing. Container bind mounts carry the `z` relabelling flag (`container_volume_opts`), the booleans `nfs_export_all_rw` and `use_nfs_home_dirs` are set on the NFS server and the clients, and the Let's Encrypt tree gets a `semanage fcontext` entry so that a renewal does not silently produce a certificate the nginx container cannot read. |
| **firewalld** | Enabled out of the box on the RHEL rebuilds, SSH only. The default is no host firewall (the cloud security group is enough), so the role masks it. Turn `hardening_firewall_enabled` on for the nftables table instead. Set `hardening_manage_firewalld: false` to leave firewalld alone; the podman role then puts the `podman*` bridges in `trusted`, without which aardvark-dns and `PublishPort` are dropped. That covers what the containers publish and nothing else: the host services the machines use between themselves (NFS 2049, Slurm 6817-6819) are then yours to open in firewalld. |
| **Unattended updates** | `dnf-automatic` with `upgrade_type = security` instead of `unattended-upgrades`, with the same policy: security updates only, no automatic reboot. |

### The antares account: choosing UID/GID

```yaml
antares_uid: 9000       # group_vars/all.yml
antares_gid: 9000
```

This UID/GID pair must be free and identical on all machines (web server, Slurm frontend and compute nodes) so that study files remain readable across the NFS-shared `/home`.

The default intentionally avoids 1000 (commonly used by distribution images). 9000 is well outside the usual allocation and below `UID_MAX`.

The playbook reads `/etc/passwd` and `/etc/group` before creating accounts and will stop if the UID/GID are already claimed. To validate the choice across your inventory without making changes:

```bash
ansible-playbook site.yml --tags common --check
```

Two caveats:
- For machines joined to a central directory service (LDAP, AD via SSSD), reserve the value in the directory. `nsswitch` reveals existing collisions but not a future directory account that may be assigned the same UID.
- Changing the UID on an already deployed machine renumbers the `antares` account and leaves its files orphaned: you must `chown -R` `/var/antares-web` and the shared `/home`.

The UID is also baked into the backend-derived image (`antarest_add_container_user`), so using one unique UID across the fleet means building a single image.

## Before production

Set secrets in `group_vars/all.yml` (or an ansible-vault encrypted file):

| Variable | Default | Notes |
|---|---:|---|
| `antarest_jwt_key` | `secretkeytochange` | JWT signing key |
| `antarest_admin_password` | `admin` | admin user password |
| `antarest_db_password` | `somepass` | PostgreSQL password |
| `slurmdbd_db_password` | `changeme-slurm-acct` | MariaDB password for Slurm accounting |

The PostgreSQL password is read only at the first initialization of the data volume; changing it later requires clearing `/var/antares-web/data/db`.

The `hardening` role reports any of these still holding the shipped value, and refuses to deploy if `hardening_fail_on_default_secrets` is on. On anything reachable from the internet, also turn TLS on and read "Hardening" below.

## Main variables

### Solvers

```yaml
# Ubuntu-22.04 on the Debian family, OracleServer-8.10 on the RedHat one
antares_solver_os: "{{ 'OracleServer-8.10' if ansible_facts['os_family'] == 'RedHat' else 'Ubuntu-22.04' }}"
antares_solvers:
  - version: "8.8.17"      # Antares_Simulator release tag
    study_version: "8.8"   # major.minor string used by Antares-Web
    bin: "antares-8.8-solver"
  - version: "9.2.0"
    study_version: "9.2"
    bin: "antares-solver"
```

Executable names changed across generations: `antares-<X>.<Y>-solver` for the 8.x line and `antares-solver` from 9.x onward. Each entry in this list is installed on both the web machine (local launcher) and in the shared `/home` (Slurm launcher), and populates the binaries table in `config.prod.yaml` and the `case` in `launchAntares.sh`.

`antares_solver_os` selects which build of each release is downloaded, and it is not cosmetic: the Ubuntu 22.04 build needs glibc 2.35 and does not start on EL 9, which has 2.34, while the project's Oracle Linux 8 build (glibc 2.28) runs on every rebuild. The default follows the family of each target, so a Debian web server driving an Oracle Linux cluster installs the right binary on both sides.

### Antares-Web

```yaml
antarest_version: "v2.33.0"   # tag, branch or commit of the AntaREST repo
antarest_http_port: 80
antarest_force_rebuild: false # force rebuild of frontend + image
```

### TLS

There is already an nginx in the stack, so that is the one that terminates TLS: no second reverse proxy to install and no port to move. Switching it on makes the `antares-nginx` container listen on 443 as well and, by default, redirect http to it.

```yaml
antarest_tls_enabled: true
antarest_tls_domain: "antares.example.org"
antarest_tls_provider: letsencrypt   # letsencrypt | selfsigned | manual
antarest_tls_email: "ops@example.org"
```

| Provider | What happens |
|---|---|
| `letsencrypt` | certbot obtains the certificate over http-01, answered by the stack's own nginx (webroot method). Renewal needs no downtime and the `certbot.timer` shipped with the package handles it. |
| `selfsigned`  | A certificate generated on the machine, valid ten years. Encrypts the traffic and makes every browser complain. For an internal network, or to test the plumbing without burning ACME rate limits. |
| `manual`      | A certificate you put on the machine yourself, for instance one issued by a company CA. Point `antarest_tls_certificate` and `antarest_tls_certificate_key` at the full chain and the private key. |

Let's Encrypt needs `antarest_tls_domain` to resolve to this machine and port 80 to be reachable from the internet, since that is where the challenge is fetched (the http-01 challenge has no port to negotiate, hence the playbook refusing to try if `antarest_http_port` is not 80). The first run brings the stack up on plain http, obtains the certificate through it and reloads nginx with TLS on; nothing has to be run twice. Use `antarest_tls_staging: true` while debugging, then remove the certificate (or `certbot renew --force-renewal`) to get a real one, because the playbook only asks for a certificate when there is none.

With TLS off, the `resources/deploy/nginx.conf` of the project is mounted unchanged, exactly as before. With TLS on, a rendered configuration is mounted instead: the same file plus the port 443 server, the redirect and an HSTS header (`antarest_tls_hsts_max_age`, 0 to remove it). The deployment compares the project file to the checksum ours was derived from and says so if upstream changed it.

### Login label for the username field

The login form labels its identifier field "NNI" (the internal RTE identifier) hard-coded in upstream sources. The playbook replaces that label before building the frontend:

```yaml
antarest_patch_login_label: true
antarest_login_username_label: '{t("global.username")}'
```

The default reuses the project's translation key so the field displays "Username" or the localized equivalent according to the browser language, instead of a fixed string. For a fixed literal label put a quoted string: `"'Login ID'"`.

The target file changed location between releases (`webapp/src/components/wrappers/LoginWrapper.tsx` up to 2.19, `webapp/src/routes/login/index.tsx` in 2.33), so the task locates it by content rather than a fixed path. If a future version removes the label the task reports it and does nothing.

### Slurm

```yaml
slurm_cluster_name: antares
slurm_partition: antares
slurm_select_type: "select/cons_tres"   # use select/linear for exclusive nodes
slurmdbd_innodb_buffer_pool_size: "1G"
```

Compute node characteristics (`CPUs`, `SocketsPerBoard`, `CoresPerSocket`, `ThreadsPerCore`, `RealMemory`) are derived from Ansible facts and can be overridden per-host in the inventory using `slurm_node_cpus`, `slurm_node_sockets`, `slurm_node_cores_per_socket`, `slurm_node_threads_per_core` and `slurm_node_real_memory`.

The maximum cores selectable in the job submission UI is capped to the smallest compute node, otherwise jobs requesting more cores than any node has will remain pending forever.

On a RHEL-compatible cluster, Slurm comes from OpenHPC because no EL 9 repository ships it:

```yaml
slurm_repo: openhpc          # `distro` on the Debian family
slurm_openhpc_release: "http://repos.openhpc.community/OpenHPC/3/EL_9/x86_64/ohpc-release-3-1.el9.x86_64.rpm"
```

The release rpm is installed with the GPG check disabled, since it is what brings in the key its own repositories are signed with; everything pulled from them afterwards is verified normally. Package names then carry an `-ohpc` suffix (`slurm-ohpc`, `slurm-slurmctld-ohpc`, `slurm-slurmd-ohpc`, `slurm-slurmdbd-ohpc`) and nothing else moves: the daemons, `/etc/slurm`, the `slurm` account and the generated `slurm.conf` are the same as on Debian. Set `slurm_repo: distro` to install Slurm yourself and only let the playbook configure it.

## Antares-Web server directory layout

```
/var/antares-web/
├── AntaREST/     git checkout, disposable: nothing generated is written here
├── deploy/       config.prod.yaml, id_rsa, solvers
├── image/        derived image build context
└── data/         persistent state: studies, matrices, PostgreSQL, logs

/etc/containers/systemd/     quadlet container units
/etc/systemd/system/antares-web.target

/etc/antares-web/tls/        self-signed or hand-copied certificate
/etc/letsencrypt/            certbot state, when that provider is used
/var/www/certbot/            ACME challenge webroot, served by nginx
```

Configuration and data live outside the git checkout: changing `antarest_version` and re-running the playbook updates the application without touching the data.

## Containers: podman and quadlet

There is no Docker daemon or compose file. Each container is defined by a quadlet unit in `/etc/containers/systemd`, which `podman-system-generator` converts to systemd services at each `daemon-reload`. systemd provides scheduling, restart behavior and logs.

**Restart policy.** Every container unit carries `Restart=on-failure` with `RestartSec=10`, and a budget of `StartLimitBurst=5` over `StartLimitIntervalSec=300` in its `[Unit]` section. Quadlet copies both sections into the generated service verbatim, so this is plain systemd. `on-failure` rather than `always` on purpose: a container that keeps dying exhausts the budget in under a minute and the unit stays `failed`, where `systemctl --failed` shows it, instead of restarting forever with nobody the wiser.

The retries are there for the transient case, and the boot is one. `Requires=`/`After=postgresql.service` is honoured by systemd, but readiness for a container unit comes from conmon: the unit is "started" when the container process is up, not when postgres accepts connections on 5432. `antarest` can therefore start too early after a host reboot, fail, and be restarted into a working stack ten seconds later. (Making `After=` mean what it looks like would take a `HealthCmd=` on postgresql plus `Notify=healthy`, which is podman 5.0 and later: EL 9 has it, Ubuntu 24.04 ships 4.9. Family-dependent units are what the rest of this playbook avoids, hence the retry.)

Podman runs rootful: this matters because rootless podman remaps container UIDs via `/etc/subuid`. A container running as `antares_uid` would not produce host files owned by `antares_uid` when rootless, breaking UID coherence with the NFS `/home`.

The stack is grouped by a `.target`, replacing `compose up/down`:

```bash
systemctl start   antares-web.target
systemctl stop    antares-web.target
systemctl restart antares-web.target     # propagated to containers via PartOf=
systemctl status  antares-web.target
podman ps
journalctl -u antarest.service -f
```

On the web server the generated services are `antarest`, `antarest-celery-beat`, `antarest-celery-worker`, `postgresql`, `redis`, `antares-nginx` and `antares-web-network`. On the Slurm frontend, the accounting DB follows the same pattern under `slurmdb.target` (`slurmdb-mariadb`, and `slurmdb-adminer` if enabled).

Three container names are significant (they become DNS names on the podman network). Renaming them silently breaks the stack:

| Container | Who depends on it |
|---|---|
| `antarest`   | upstream `nginx.conf` proxies to `http://antarest:5000/` |
| `postgresql` | `config.prod.yaml` points DB to `postgresql:5432` |
| `redis`      | `config.prod.yaml` points cache to `redis` |

`postgresql` also has the alias `postgres` (the upstream compose container_name). Compose resolved both service and container names; podman resolves only the container name and aliases.

All images are fully qualified (`docker.io/library/postgres:latest`, `localhost/antarest:latest`): Debian/Ubuntu don't set `unqualified-search-registries`, so short names are not resolved by podman and will be rejected.

## Background maintenance tasks

Everything periodic runs in two containers, `antarest-celery-beat` (the scheduler) and `antarest-celery-worker` (which executes). The API process starts no background service: `server.services` is left unset in `config.prod.yaml`, which is what the application defaults to anyway.

This is not what the upstream `docker-compose.yml` does. That file still declares a `watcher` and a `matrix_gc` container, which are `IService` singletons, the mechanism the project documents as the fallback for non-Celery environments (the desktop build). Celery is the deployment schema the project favours, [stated on PR #3360](https://github.com/AntaresSimulatorTeam/AntaREST/pull/3360), and the compose file is explicitly not a production reference any more. It also covers two of the eight periodic tasks, where the celery pair covers all eight:

| Task | Default interval | Reclaims |
|---|---|---|
| `watcher_scan` | 15 min | nothing (registers studies found in the workspaces) |
| `matrices_cleaner` | 1 h | orphaned matrices |
| `blobs_cleaner` | 24 h | unreferenced blobs |
| `variable_view_cleaner` | 1 h | `output_variables_views` rows, which pin matrices |
| `tasks_cleaner` | 24 h | task rows older than 30 days |
| `auto_archiver` | cron, nightly | archives studies untouched for 60 days |
| `disk_usage` | cron, hourly | nothing (reporting) |
| `disk_space_analyzer` | cron, nightly | nothing (reporting) |

The broker is Redis, on database 1 (the event bus uses 0). The application derives the broker and result-backend URLs from the `redis` section of `config.prod.yaml`, so there is no separate broker to configure.

Upgrading a deployment made before this change takes the `antarest-watcher` and `antarest-matrix-gc` containers down: they stay listed in `antarest_quadlet_all_units`, which is the list of units the role stops and removes once it no longer writes them. Never run both mechanisms at once, two watchers scan the workspaces twice.

**The collectors start in dry run.** Upstream defaults them to destructive from the first run; here all four write only what they *would* delete, which matters because an instance deployed from the compose file has never reclaimed anything and the first real run has a lot of catching up to do.

```yaml
antarest_matrix_gc_dry_run: true         # roles/antares_web/defaults/main.yml
antarest_blob_gc_dry_run: true
antarest_variable_view_gc_dry_run: true
antarest_auto_archive_dry_run: true
```

```bash
journalctl -u antarest-celery-worker -f    # what the tasks did, or would have done
journalctl -u antarest-celery-beat -f      # what was scheduled
```

Read a few cycles before switching one off. `auto_archive` is the one to be careful with: it is not a collector, it moves studies users can see into the archive directory.

Order matters between two of them. Every `output_variables_views` row pins its matrix, so `matrices_cleaner` reclaims almost nothing until `variable_view_cleaner` has run for real.

The worker runs celery's `solo` pool, one task at a time. That is not a conservative default but the correct one: the worker builds its SQLAlchemy engine in the `worker_init` signal, before `prefork` would fork its children, and the children would inherit the same database sockets. `antarest_celery_pool` and `antarest_celery_concurrency` are there for whoever has a reason to change it.

The beat container is the one oddity in the stack. It keeps its "last run" state in a shelve file whose default name is relative to the working directory, which in this image is `/`, not writable by a container running as `antares_uid`. Its unit therefore carries `PodmanArgs=--workdir=/celerybeat --entrypoint=/scripts/start.sh`: the working directory moves onto a bind mount under `data/celerybeat`, and the entrypoint has to be given absolutely because the image declares it as the relative path `./scripts/start.sh`. Both go through `PodmanArgs=` because the `WorkingDir=` and `Entrypoint=` quadlet keys only exist from podman 5.0 and Ubuntu 24.04 ships 4.9.

Intervals are not exposed as Ansible variables. Every `*_sleeping_time` and `*_cron` of the upstream `docs/configuration.md` can be added to `roles/antares_web/templates/config.prod.yaml.j2` under `storage:`. One trap: `auto_archive_sleeping_time` and `auto_archive_cron` are mutually exclusive, setting both makes the application refuse to start.

## Hardening

A blank VM, a few minutes, and an Antares-Web reachable on the internet with 22 and 80 open is exactly what this playbook makes easy, so the `hardening` role runs right after the base configuration and before anything is deployed. Four independent blocks, each switched on its own:

```yaml
hardening_enabled: true               # group_vars/all.yml
hardening_firewall_enabled: false     # off: a cloud VM already has a security group
hardening_fail2ban_enabled: true
hardening_ssh_enabled: true
hardening_unattended_upgrades: true
```

Everything is on except the firewall, which duplicates what a cloud provider's security group already does, and two filters that have to agree is one more place for a rule to go missing. Turn it on for a machine with nothing in front of it, and in particular for a Slurm front-end on a network you do not control: its NFS export uses `no_root_squash`.

**Firewall.** An nftables input chain with a drop policy, in a table of its own (`inet antares_fw`) loaded by `antares-firewall.service`. `/etc/nftables.conf` is left alone: what both families ship in it starts with `flush ruleset`, which would take the rules netavark writes for the containers down with it. On a RHEL rebuild, firewalld is masked whether this is on or off, see below.

```bash
nft list table inet antares_fw
systemctl reload antares-firewall     # re-apply after an edit
```

Open to the world: the ports sshd actually listens on, read from `sshd -T` rather than assumed to be 22 (the inventory of this repository has a machine answering on 2222), and the interface ports on an `antares_web` machine. Open to the other machines of the inventory, on every port: that is what keeps NFS, Slurm and the job submission path working without exposing 2049 or 6817 to the internet, and it is the reason the NFS export with `no_root_squash` on the front-end stops being a hole. Add anything else with `hardening_firewall_extra_tcp_ports` or `hardening_firewall_extra_sources`.

Two things this deliberately does not do. It does not filter the `forward` hook, because a packet aimed at a published container port is DNATed and routed, never traverses `input`, and a forward chain with a drop policy would take every container down, outgoing traffic included: what the containers expose is decided by their `PublishPort`, and the two that are not meant to be public (adminer, the accounting MariaDB) are bound to `127.0.0.1` in their units. And it accepts everything arriving on `podman*` interfaces, because aardvark-dns listens on the bridge address, which belongs to the host: without that rule, container name resolution dies and the backend never finds `postgresql`.

The peer addresses come from the gathered facts, so a `--limit` run on an expired fact cache would leave them out; the role says which machines it could not resolve rather than silently isolating them.

**fail2ban.** The `sshd` jail, plus a jail on the Antares-Web login form: the API answers 401 on a wrong password and nginx logs the request. Both read the journal (`backend = systemd`) because the Ubuntu images ship no rsyslog at all, so a jail pointed at `/var/log/auth.log` starts dead, which is incidentally the state a stock Debian fail2ban is in. On the RedHat family the packages come from EPEL, which splits them: `fail2ban-server` and `fail2ban-systemd` are installed, deliberately not the `fail2ban` metapackage, which drags in `fail2ban-firewalld` and its `banaction = firewalld`.

```bash
fail2ban-client status
fail2ban-client status antares-web-login
fail2ban-client set antares-web-login unbanip 203.0.113.7
```

Bans are dropped in the `prerouting` hook at priority `raw`, not in `input` like the stock actions. This is the difference everybody meets with docker and ufw: an input-hook ban is reported by the jail and does nothing at all, since the traffic to a container is DNATed at `nat prerouting` and routed onward. Dropping earlier catches the containers and the host alike. The machines of the inventory are never banned.

**SSH.** A drop-in in `/etc/ssh/sshd_config.d/`: no password authentication, no root password login, `MaxAuthTries 4`, a 30 second grace time, no X11 forwarding. TCP forwarding stays on, since the README reaches adminer through `ssh -L`. Before closing the password, the role checks that the account Ansible connects with has a non-empty `authorized_keys` and stops if it does not, rather than leaving an unreachable machine; set `hardening_ssh_disable_password_auth: false` if the machine authenticates through something else, an SSH certificate authority for instance. The resulting configuration is checked with `sshd -t`, and the drop-in is removed again if sshd refuses it.

**Unattended upgrades.** On the Debian family, `unattended-upgrades` enabled on the origins the distribution already restricts to the security pocket. On the RedHat family, `dnf-automatic` with `upgrade_type = security` and its timer enabled, which is the same policy with different machinery. Neither reboots on its own: a study can run for hours and a machine that reboots in the middle of one loses it. `/var/run/reboot-required` and `dnf needs-restarting -r` say when one is due.

**firewalld (RedHat family).** The RHEL rebuilds boot with firewalld enabled and a default zone that accepts SSH and nothing else. Debian and Ubuntu ship no host filter, so `hardening_firewall_enabled: false` (the default: the cloud security group is enough) only meant the same thing on one family. firewalld is therefore stopped, disabled and **masked** whether our nftables table is on or not. `systemctl unmask firewalld` puts it back. Set `hardening_manage_firewalld: false` to be left alone with it.

**Secrets.** The role also reports the secrets below still holding the value this repository ships, admin/admin being a faster way in than any brute force. Set `hardening_fail_on_default_secrets: true` to make that a failure rather than a message.

The bans do not depend on the firewall: fail2ban writes its own table, so it keeps working with `hardening_firewall_enabled: false`.

Each block can also be flipped for a run, or per host in the inventory:

```bash
ansible-playbook site.yml -e hardening_firewall_enabled=true     # this run only
ansible-playbook site.yml -e hardening_enabled=false             # none of it
```

## Build once, deploy everywhere

By default (`antarest_image_source: build`) the target clones, builds the frontend with node and produces the image. This is standalone but requires Internet and about 4 GB of heap on the build machine. For repeated destroy/recreate cycles or multiple servers this is wasteful because the build uses `npm install` (not `npm ci`) so builds at different times may produce different artifacts.

```bash
ansible-playbook build.yml                                  # once
ansible-playbook site.yml -e antarest_image_source=archive  # many times
```

`build.yml` runs on the `builder` inventory group (see `inventory/build.example.yml`) and reuses the deployment build tasks, so artifacts are produced exactly by the same recipe that the deployment uses. A builder needs nothing installed beforehand: the play pulls in the same `podman` role the deployment uses. It never starts the stack, so a builder is not an Antares-Web server. It drops artifacts into `./artifacts` (gitignored):

| File | Content |
|---|---|
| `antarest-image.tar.gz` | backend image, UID baked in |
| `thirdparty-*.tar.gz` | postgres, redis, nginx, and adminer if enabled |
| `webapp-dist.tar.gz` | built web application |
| `antares-*.tar.gz` | solver tarballs |
| `manifest.yml` | version, commit, UID, date |

In `archive` mode the target loads images idempotently (no retransfer if present), unpacks the frontend in the checked-out tree where nginx bind-mounts it, and takes solvers from the local cache instead of GitHub. Archives are transported with `rsync`, not the `copy` module, which is unsuitable for hundreds of megabytes.

The solver tarballs are cached for the builder's own family. A mixed fleet, or a Debian builder feeding Oracle Linux targets, wants both builds:

```yaml
antares_build_solver_os: ["Ubuntu-22.04", "OracleServer-8.10"]
```

A target that finds no tarball for its family in the cache falls back to downloading it from GitHub, so getting this wrong costs time, not a failure.

Three constraints to know:
- The builder must share the target architecture. Building amd64 on arm64 requires QEMU emulation which is slow and defeats the benefit.
- UID is baked into the image (`antarest_add_container_user`), so builder and targets must agree on `antares_uid`.
- The build uses its own podman store (`antares_build_root`, default `/data/antares-build/store`) passed as an option and not written into the builder's `storage.conf`: build machines often lack space on `/`, and nothing changes in the system podman config.

Without a registry, each new version means `N × size` copies with no layer deduplication. For a small fleet this is fine; beyond that adding a `registry:2` instance is easier to maintain.

## Useful tags

```bash
ansible-playbook site.yml --tags antares_web     # redeploy application
ansible-playbook site.yml --tags slurm           # cluster only
ansible-playbook site.yml --tags solver          # (re)install solvers
ansible-playbook site.yml --tags hardening       # firewall, fail2ban, sshd, updates
ansible-playbook site.yml -e antarest_force_rebuild=true   # full rebuild
```

`slurm.conf` is generated from facts of all compute nodes: avoid using `--limit` on a subset of `slurm_compute` unless you have fixed `slurm_node_*` variables in the inventory.

## Differences from the PDF

The reference procedure dates from September 2025; several upstream changes have been made since then.

- Launcher format. The old `launcher.local` / `launcher.slurm` format was replaced by `launcher.launchers`: a list of entries each with `id`, `name` and `type`, and `launcher.default` points to an `id`. The old format is no longer read.
- Version passed to the launcher script. antares-launcher now receives a `major.minor` (`8.8`) version string, not the compact integer (`910`). The generated `case` accepts both forms, so tests like `if [ "$ANTARES_VERSION" = "910" ]` from the PDF no longer match.
- Frontend build image. The PDF's `Dockerfile_build_frontend` installed `requirements.txt` with Python 3.9 and nvm; the project moved to `uv` and `pyproject.toml` (no `requirements.txt`). The playbook builds the frontend in an official Node image pinned to the Node version in `webapp/.nvmrc` (22.13.0 for 2.33.0).
- Account in the image. The PDF edits the project's `Dockerfile` to add `useradd`. The playbook leaves upstream checkout intact and stacks a derived image on top, surviving upstream Dockerfile changes (the env var `ANTARES_CONF` was previously `ANTARES` vs `ANTAREST_CONF` now).
- No compose at all. The PDF relied on `docker-compose` v1 (end of life). The playbook replaces compose with podman + quadlet: each container is a systemd unit, the upstream `docker-compose.yml` is not used anymore. This removes the dependency on compose ≥ 2.24 and its `!override` tags.
- Background tasks. The PDF, like the upstream compose file, runs a `watcher` and a `matrix_gc` container. The playbook runs `celery-beat` and `celery-worker` instead: that is the schema the project now favours, and the only one that also runs the blob, variable-view and task collectors. See "Background maintenance tasks".
- `ControlMachine` / `ControlAddr` replaced by `SlurmctldHost`.
- Accounting persistence. The PDF's compose left MariaDB without a declared volume so accounting would vanish on container recreation. The playbook uses a named volume to keep accounting data persistent.
- Network exposure. The PDF published MariaDB on `0.0.0.0:3306` with root account; the playbook binds it only to `127.0.0.1` because `slurmdbd` runs on the same host. Adminer is disabled by default.
- `archive_dir`. The PDF used `/studies/archives`, a path not provided by the upstream compose, so the playbook adds the corresponding mount in the backend unit.
- Scratch directory. As in the PDF it is placed in the shared `/home`, but the playbook creates `~/scratch/`.
- The "NNI" field. Still present in 2.33.0 but moved from `webapp/src/components/wrappers/LoginWrapper.tsx` line 170 to `webapp/src/routes/login/index.tsx` line 149. The playbook finds it by content and replaces it with the translation key (see above).

## Major database versions

Third-party images are pinned to majors (`postgres:18`, `mariadb:11`, `redis:8`, `nginx:1.30`, `adminer:5`) rather than `latest` to avoid accidental major upgrades. nginx is pinned on a minor because its major is always `1`, and on the stable branch rather than the mainline one, which stops being rebuilt as soon as the next mainline opens.

Since these tags are also the names of the archives `build.yml` produces, changing one invalidates the whole artifact set: re-run `build.yml` before the next `archive` deployment. The target says so explicitly rather than failing later on a missing image.

The `data/db` directory contains a PostgreSQL cluster of a given major version. PostgreSQL refuses to start on data written by a different major without `pg_upgrade`. If you use `latest`, a future major bump in the tag could silently stop your stack on the next playbook run. `archive` mode does not avoid this risk, it only postpones the problem to the next `build.yml`.

Changing major versions is therefore an explicit operation:

```bash
# dump while the old image is still present, then stop everything
podman exec postgresql pg_dumpall -U postgres > antarest-db.sql
systemctl stop antares-web.target

# update antarest_postgres_image, move the old cluster aside, redeploy
mv /var/antares-web/data/db/pgdata /var/antares-web/data/db/pgdata.old
ansible-playbook site.yml --limit <host> --tags antares_web

# the redeploy did not only create an empty cluster: it also ran the schema
# migration in it and started the backend. Empty the schema before restoring,
# with only postgres running.
systemctl stop antares-web.target
systemctl start postgresql.service
podman exec -i postgresql psql -v ON_ERROR_STOP=1 -U postgres \
    -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'

# restore, then bring the stack back up
podman exec -i postgresql psql -v ON_ERROR_STOP=1 -U postgres < antarest-db.sql
systemctl start antares-web.target
```

Do not skip the two steps before the restore, and do not drop `ON_ERROR_STOP`. Restoring into the schema the migration has just created fails in the worst possible way: `pg_dumpall` writes table data in alphabetical order and only recreates the foreign keys at the end, so a `COPY group_metadata` arriving before `COPY groups` is rejected by the constraint that is already there. Without `ON_ERROR_STOP`, `psql` skips it, leaves the table empty, exits 0, and buries the message in the hundreds of "already exists" errors from the `CREATE` statements.

Same idea for MariaDB on the Slurm frontend (use `mariadb-dump` and the `slurmdb-data` volume).

## Known limitations

- Xpansion is not covered: the launcher script derives from `launchAntares_v1.1.2.sh`, which expects an R environment and environment modules that are not provided here.
- The firewall filters the host only, not the `forward` hook the container traffic goes through: a port published by a unit is reachable, whatever the firewall says. See "Hardening" for why, and check the `PublishPort` lines before publishing something new.
- The Antares-Web login jail counts the 401s nginx logs. A brute force that spreads over many addresses, or one aimed at an endpoint other than the login, is not covered.
- Migration from a Docker-based version of this playbook: the `slurm_frontend` role stops and removes the old `slurmdb.service` unit and its `docker-compose.yml` but does not touch the docker volume `slurmdb_data`: it contains accounting history. Reusing a live DB requires a `mariadb-dump` from the old volume and restoration into the podman volume `slurmdb-data`. On the web server, data under `/var/antares-web/data` are bind mounts and are reused as-is.
- The NNI label patch modifies source before the build. The checkout is reset each run (`git force`), so the patch is reapplied every time; a build stamp (`deploy/.frontend-build-stamp`) prevents rebuilding the frontend if nothing changed. Changing `antarest_login_username_label` triggers a rebuild.
- RHEL-compatible support targets the 9 series. Nothing here is specific to Oracle Linux beyond the names of the CRB and EPEL packages, so Rocky, Alma, CentOS Stream and RHEL itself follow the same path, but Oracle Linux 9 is the one the defaults are written for. EL 8 is not covered: its podman is too old for quadlet.
- Slurm on EL 9 comes from OpenHPC, a third-party repository. It is the maintained answer there and what the HPC world runs, but it is one more upstream to follow: a major OpenHPC bump can move Slurm by several versions at once, which the "one distribution per cluster" rule above then applies to.
