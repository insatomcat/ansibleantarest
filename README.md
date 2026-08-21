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

A machine may be in several of those groups. Listing the front-end in `slurm_compute` as well gives a cluster where the controller also runs jobs, which is what a two-machine or a small deployment looks like; the shared `/home` is simply local there, and nothing else changes. The number of compute nodes is whatever the inventory says: `slurm.conf` is generated from the group.

Monitoring is optional too and off by default: `monitoring_enabled: true` puts a node exporter on every machine of the inventory, a Slurm exporter next to the controller, and Prometheus and Grafana on the web server, with Grafana served by the front door under `/grafana/`. See [Monitoring](docs/monitoring.md).

## Quick start

```bash
ansible-galaxy collection install -r requirements.yml

# edit the inventory: hosts, and every variable this deployment sets
$EDITOR inventory/hosts.yml     # at least set the secrets (see below)

ansible-playbook site.yml
```

The interface will then be available at `http://<antares_web>/` (default credentials: `admin` / `admin`), or `https://` once TLS is on (see [TLS](docs/edge-and-tls.md#tls)). The machines are firewalled, fail2banned and their sshd hardened along the way, see [Hardening](docs/hardening.md).

Without a cluster:

```bash
ansible-playbook site.yml -e slurm_enabled=false
```

The inventory should then contain only the `antares_web` group.

On one machine, cluster included: list that machine in the three groups. It then runs Antares-Web *and* the cluster it submits to, which is what buys Antares-Xpansion on a single-machine site. See [the cluster on the web machine itself](docs/slurm.md#the-cluster-on-the-web-machine-itself).

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

The builder and the targets must agree on `antares_uid`/`antares_gid` (baked into the image) and share the same CPU architecture. See [Build once, deploy everywhere](docs/build-and-deploy.md).

There is no `group_vars/` next to the playbooks: every default lives in the code, in `roles/<role>/defaults/`, and the inventory is the only place a deployment describes itself. Role defaults are the lowest precedence Ansible has, so anything the inventory sets wins - under a host, or in a `vars:` block on a group, both work. The examples put per-deployment settings on the host because that is usually where they belong, not because a group would be ignored.

The knobs several roles share (and the ones `build.yml` and `verify.yml` read without running a role) live in `roles/antares_defaults/`, one file per area. Nothing there needs editing to deploy: override in the inventory instead.

The one exception is `inventory/group_vars/slurm.yml`, the per-node hardware description `slurm.conf` is generated from. It has to be an inventory variable rather than a role default, because every node reads it from *every other* node's `hostvars`, where a role default is not visible. It is picked up by any `-i inventory/*.yml`.

## Before production

Set secrets in your inventory (or in an ansible-vault encrypted file):

| Variable | Default | Notes |
|---|---:|---|
| `antarest_jwt_key` | `secretkeytochange` | JWT signing key |
| `antarest_admin_password` | `admin` | admin user password |
| `antarest_db_password` | `somepass` | PostgreSQL password |
| `slurmdbd_db_password` | `changeme-slurm-acct` | MariaDB password for Slurm accounting |
| `monitoring_grafana_admin_password` | `admin` | Grafana administrator, when `monitoring_enabled` is on |

The PostgreSQL password is read only at the first initialization of the data volume; changing it later requires clearing `/var/antares-web/data/db`.

`antarest_admin_password` has the same shape: AntaREST writes it when it creates the `admin` row and never again, so it seeds an empty database and nothing more. Changing it on a deployment that already ran is an update in the database, see [Operating a deployment](docs/operations.md#changing-the-admin-password).

The `hardening` role stops the deployment on any of these still holding the shipped value, naming them. That is `hardening_fail_on_default_secrets`, on by default; set it to false on a throwaway machine. On anything reachable from the internet, also turn TLS on and read [Hardening](docs/hardening.md).

## The playbooks

| Playbook | What it does |
|---|---|
| `site.yml` | The deployment. Facts, `common`, `hardening`, the Slurm half, then Antares-Web. Every role is guarded by a `when:` on an `*_enabled` flag. |
| `build.yml` | Builds the artefacts once on a `builder` host and pulls them into `artifacts/` on the controller, with the very task files the deployment uses. See [Build once, deploy everywhere](docs/build-and-deploy.md). |
| `verify.yml` | Read-only end-to-end checks after a deployment. Run it from a machine that is not in the inventory, see [Operating a deployment](docs/operations.md). |

Every role carries the variables it owns in `roles/<role>/defaults/main.yml`, and the knobs shared between roles are in `roles/antares_defaults/defaults/main/`, one commented file per area. The roles with a surface worth describing have a `README.md` of their own: `antares_defaults`, `antares_web`, `antares_edge`, `antares_auth`, `keycloak`, `podman`, `hardening`, `common`, `slurm_frontend`, `monitoring_node`, `monitoring_slurm` and `monitoring_server`.

## Documentation

| Question | Page |
|---|---|
| Which distributions are claimed, what a RHEL target gets on top, choosing the `antares` UID/GID | [Requirements](docs/requirements.md) |
| Which solver builds are installed, and Antares-Xpansion | [Solvers and Antares-Xpansion](docs/solvers.md) |
| Application settings, directory layout, study workspaces, putting the state on its own volume | [Antares-Web](docs/antares-web.md) |
| The one container holding the ports of the machine, TLS and certbot, extra routes | [The front door and TLS](docs/edge-and-tls.md) |
| Keycloak, external accounts, what `external_auth` is | [Authentication](docs/authentication.md) |
| Quadlet units, restart policy, the podman version floor | [Containers: podman and quadlet](docs/containers.md) |
| celery-beat, celery-worker, the collectors and their dry run | [Background maintenance tasks](docs/background-tasks.md) |
| Cluster variables, one machine that is also its own cluster, the launch script | [The Slurm cluster](docs/slurm.md) |
| nftables, fail2ban, sshd, unattended updates, the journal | [Hardening](docs/hardening.md) |
| Build once on a builder, deploy with `archive` | [Build once, deploy everywhere](docs/build-and-deploy.md) |
| Node exporters, Prometheus, Grafana behind the front door | [Monitoring](docs/monitoring.md) |
| What `verify.yml` proves, changing the admin password, PostgreSQL major upgrades | [Operating a deployment](docs/operations.md) |
| What this does not cover, and where it diverges from the reference PDF | [Limitations](docs/limitations.md) |

## Useful tags

```bash
ansible-playbook site.yml --tags antares_web     # redeploy application
ansible-playbook site.yml --tags edge            # front door only: TLS, routes
ansible-playbook site.yml --tags keycloak        # Keycloak only
ansible-playbook site.yml --tags auth            # the authentication connector
ansible-playbook site.yml --tags slurm           # cluster only
ansible-playbook site.yml --tags solver          # (re)install solvers
ansible-playbook site.yml --tags xpansion        # (re)install Antares-Xpansion (needs antares_xpansion_enabled)
ansible-playbook site.yml --tags monitoring      # the exporters, Prometheus and Grafana
ansible-playbook site.yml --tags hardening       # firewall, fail2ban, sshd, updates
ansible-playbook site.yml -e antarest_force_rebuild=true   # full rebuild
```

`slurm.conf` is generated from facts of all compute nodes: avoid using `--limit` on a subset of `slurm_compute` unless you have fixed `slurm_node_*` variables in the inventory.

