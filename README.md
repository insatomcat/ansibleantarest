# Ansible deployment of Antares-Web (optional Slurm cluster)

This Ansible playbook automates the "Basic Antares-Web and Slurm deployment" procedure (see `antares-slurm-1.3.pdf`), updated for current releases of
[AntaREST](https://github.com/AntaresSimulatorTeam/AntaREST) and
[Antares Simulator](https://github.com/AntaresSimulatorTeam/Antares_Simulator).

Three types of machines are used:

| Inventory group     | Role |
|---|---|
| `antares_web`       | Builds and runs Antares-Web (podman + quadlet) |
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

The interface will then be available at `http://<antares_web>/` (default credentials: `admin` / `admin`).

Without a cluster:

```bash
ansible-playbook site.yml -e slurm_enabled=false
```

The inventory should then contain only the `antares_web` group.

## Requirements

- A Debian-family distribution on all target machines (see supported distros below), root access via `sudo`, and Python 3 installed.
- The `antares_web` machine needs Internet access (container images, npm and Python packages, solver binaries).
- The Slurm frontend also downloads solvers from GitHub.
- A free UID/GID that is identical on all machines for the `antares` account: `9000` by default. The playbook will refuse to continue if the UID/GID are already taken.
- Ansible ≥ 2.15 on the control machine, and `ansible.posix` available.

### Supported distributions

All installs use `apt`, so supported systems are Debian/Ubuntu family. Package names, systemd unit names and `/etc/slurm` layout are the same across the supported releases below; podman is provided by the distribution (Debian 13 ships podman 5.x, Ubuntu 24.04 ships 4.9, quadlet is present since 4.4), so no special adaptation is required:

```yaml
supported_distros:      # group_vars/all.yml
  - "Debian 12"
  - "Debian 13"
  - "Ubuntu 22"
  - "Ubuntu 24"
```

The playbook aborts on unsupported distros and prints the variable to extend. Set `distro_check_enabled: false` to disable the check entirely.

Important cluster note: use one distribution per cluster. Packaged Slurm versions differ (e.g., 23.11 on Ubuntu 24.04 vs 24.11 on Debian 13) and the daemons `slurmctld` / `slurmd` / `slurmdbd` interoperate only across certain major versions. The generated `slurm.conf` works for both, but do not mix a front-end on Debian 13 with compute nodes on Ubuntu 24.04 in the same cluster. The `antares_web` machine is unaffected: it talks to the Slurm frontend only via SSH.

The apt lock is tolerated up to `apt_lock_timeout` seconds (default 300) because Ubuntu images often run `apt-daily` and `unattended-upgrades` on boot.

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

## Main variables

### Solvers

```yaml
antares_solver_os: "Ubuntu-22.04"
antares_solvers:
  - version: "8.8.17"      # Antares_Simulator release tag
    study_version: "8.8"   # major.minor string used by Antares-Web
    bin: "antares-8.8-solver"
  - version: "9.2.0"
    study_version: "9.2"
    bin: "antares-solver"
```

Executable names changed across generations: `antares-<X>.<Y>-solver` for the 8.x line and `antares-solver` from 9.x onward. Each entry in this list is installed on both the web machine (local launcher) and in the shared `/home` (Slurm launcher), and populates the binaries table in `config.prod.yaml` and the `case` in `launchAntares.sh`.

### Antares-Web

```yaml
antarest_version: "v2.33.0"   # tag, branch or commit of the AntaREST repo
antarest_http_port: 80
antarest_force_rebuild: false # force rebuild of frontend + image
```

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

## Antares-Web server directory layout

```
/var/antares-web/
├── AntaREST/     git checkout, disposable: nothing generated is written here
├── deploy/       config.prod.yaml, id_rsa, solvers
├── image/        derived image build context
└── data/         persistent state: studies, matrices, PostgreSQL, logs

/etc/containers/systemd/     quadlet container units
/etc/systemd/system/antares-web.target
```

Configuration and data live outside the git checkout: changing `antarest_version` and re-running the playbook updates the application without touching the data.

## Containers: podman and quadlet

There is no Docker daemon or compose file. Each container is defined by a quadlet unit in `/etc/containers/systemd`, which `podman-system-generator` converts to systemd services at each `daemon-reload`. systemd provides scheduling, restart behavior and logs.

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

On the web server the generated services are `antarest`, `antarest-watcher`, `antarest-matrix-gc`, `postgresql`, `redis`, `antares-nginx` and `antares-web-network`. On the Slurm frontend, the accounting DB follows the same pattern under `slurmdb.target` (`slurmdb-mariadb`, and `slurmdb-adminer` if enabled).

Three container names are significant (they become DNS names on the podman network). Renaming them silently breaks the stack:

| Container | Who depends on it |
|---|---|
| `antarest`   | upstream `nginx.conf` proxies to `http://antarest:5000/` |
| `postgresql` | `config.prod.yaml` points DB to `postgresql:5432` |
| `redis`      | `config.prod.yaml` points cache to `redis` |

`postgresql` also has the alias `postgres` (the upstream compose container_name). Compose resolved both service and container names; podman resolves only the container name and aliases.

All images are fully qualified (`docker.io/library/postgres:latest`, `localhost/antarest:latest`): Debian/Ubuntu don't set `unqualified-search-registries`, so short names are not resolved by podman and will be rejected.

## Build once, deploy everywhere

By default (`antarest_image_source: build`) the target clones, builds the frontend with node and produces the image. This is standalone but requires Internet and about 4 GB of heap on the build machine. For repeated destroy/recreate cycles or multiple servers this is wasteful because the build uses `npm install` (not `npm ci`) so builds at different times may produce different artifacts.

```bash
ansible-playbook build.yml                                  # once
ansible-playbook site.yml -e antarest_image_source=archive  # many times
```

`build.yml` runs on the `builder` inventory group and reuses the deployment build tasks, so artifacts are produced exactly by the same recipe that the deployment uses. It drops artifacts into `./artifacts` (gitignored):

| File | Content |
|---|---|
| `antarest-image.tar.gz` | backend image, UID baked in |
| `thirdparty-*.tar.gz` | postgres, redis, nginx, and adminer if enabled |
| `webapp-dist.tar.gz` | built web application |
| `antares-*.tar.gz` | solver tarballs |
| `manifest.yml` | version, commit, UID, date |

In `archive` mode the target loads images idempotently (no retransfer if present), unpacks the frontend in the checked-out tree where nginx bind-mounts it, and takes solvers from the local cache instead of GitHub. Archives are transported with `rsync`, not the `copy` module, which is unsuitable for hundreds of megabytes.

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
- No firewall is configured. Machines are assumed to be on a trusted network, as in the reference procedure.
- No TLS in front of the web UI. Put a reverse proxy with TLS if you expose the interface beyond your internal network.
- Migration from a Docker-based version of this playbook: the `slurm_frontend` role stops and removes the old `slurmdb.service` unit and its `docker-compose.yml` but does not touch the docker volume `slurmdb_data`: it contains accounting history. Reusing a live DB requires a `mariadb-dump` from the old volume and restoration into the podman volume `slurmdb-data`. On the web server, data under `/var/antares-web/data` are bind mounts and are reused as-is.
- The NNI label patch modifies source before the build. The checkout is reset each run (`git force`), so the patch is reapplied every time; a build stamp (`deploy/.frontend-build-stamp`) prevents rebuilding the frontend if nothing changed. Changing `antarest_login_username_label` triggers a rebuild.
