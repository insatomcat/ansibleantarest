# AGENTS.md

Ansible repository that deploys Antares-Web, with an optional Slurm cluster
next to it. There is no application code here: playbooks, roles, Jinja
templates, one CI workflow and the documentation in `docs/`.

Everything is written in English, documentation included. Keep it that way.

## Where to look, instead of grepping

`README.md` is the entry point (~135 lines: what this deploys, quick start,
example inventories, secrets, tags) and `docs/` holds the reference, one page
per area. Both are kept in sync with the code. Open the page you need rather
than grepping the tree:

| Question | Page |
|---|---|
| Which distributions are claimed and why not the others, what a RHEL target gets on top (CRB, EPEL, OpenHPC, SELinux), the `antares` UID/GID | `docs/requirements.md` |
| Which solver build lands where, Antares-Xpansion and what it costs | `docs/solvers.md` |
| Application settings, where files land on the web server, study workspaces, putting the state on a block device | `docs/antares-web.md` |
| The one container holding the ports of the machine, TLS, certbot, extra routes | `docs/edge-and-tls.md` |
| Keycloak, external accounts, what `external_auth` is | `docs/authentication.md` |
| Quadlet units, restart policy, podman version floor | `docs/containers.md` |
| celery-beat, celery-worker, the collectors | `docs/background-tasks.md` |
| Cluster variables, one machine that is also its own cluster, the launch script | `docs/slurm.md` |
| nftables, fail2ban, sshd, unattended updates, journal | `docs/hardening.md` |
| Node exporters everywhere, the Slurm exporter, Prometheus, Grafana behind the front door | `docs/monitoring.md` |
| Build once, deploy with `archive` | `docs/build-and-deploy.md` |
| What `verify.yml` proves, changing the admin password, Postgres major upgrades | `docs/operations.md` |
| Known limitations, where this diverges from the reference PDF | `docs/limitations.md` |
| How to re-run only one part | `README.md`, "Useful tags" |

A variable is documented on the `docs/` page of its area. What a *role* does,
what it assumes and what it leaves on the machine is in `roles/<role>/README.md`
for the twelve roles that have one: `antares_defaults`, `common`, `hardening`,
`podman`, `antares_web`, `antares_edge`, `antares_auth`, `keycloak`,
`slurm_frontend`, `monitoring_node`, `monitoring_slurm`, `monitoring_server`.
The others are small enough to read, and their `defaults/main.yml` is
commented.

## Entry points

- `site.yml` - the deployment. Reads the plays in order: facts, common,
  hardening, the node exporter of every machine, then the Slurm half, then
  Antares-Web. Every play that is not aimed at a group targets `all:!builder`:
  a builder is not a machine of the deployment, `build.yml` sets it up itself,
  and the same difference is taken in the firewall's peer set, in the
  Prometheus targets and in `verify.yml`. Every role is guarded by a `when:`
  on an `*_enabled` flag, except the ones that also know how to remove
  themselves (`keycloak`, `antares_auth`, the three `monitoring_*`), which run
  either way.
- `build.yml` - builds the artefacts once on a `builder` host and pulls them
  into `artifacts/` on the controller. Reuses the very task files of
  `antares_web`, so artefacts cannot be built by a different recipe than the
  one they replace.
- `verify.yml` - read-only end-to-end checks after a deployment (cluster
  health, NFS both ways, a real job submitted the way the backend submits one,
  and the three firewall rulesets from both sides). Run it from a machine that
  is not in the inventory.
- `inventory/hosts.yml` - the example inventory, and the documentation of the
  three host groups. `inventory/ci-*.yml` are what the CI runs, including
  `ci-standalone-slurm.yml`, one host listed in the three groups at once.
- There is no `group_vars/` next to the playbooks. Every default is in the
  code: `roles/<role>/defaults/main.yml` for what one role owns,
  `roles/antares_defaults/defaults/main/` for what several roles share, one
  heavily commented file per area. An inventory overrides any of it, at host
  or at group level, because role defaults are the lowest precedence there is.
- `inventory/group_vars/slurm.yml` - the per-node hardware description.
  Deliberately an *inventory* variable: `slurm.conf` and `/etc/hosts` are
  rendered from every other node's `hostvars`, and a role default is invisible
  through `hostvars[other]`. Adjacent to the inventory files, so any
  `-i inventory/*.yml` picks it up.

## Roles

| Role | Job |
|---|---|
| `antares_defaults` | No tasks, defaults only: everything read by more than one role, or by a playbook outside any role. First entry of every play's `roles:` (or of its `pre_tasks:`) |
| `common` | Distribution check, repositories, base packages, the `antares` account (UID/GID guard), `/etc/hosts`, time sync |
| `hardening` | nftables, fail2ban, sshd, unattended updates, persistent journal, firewalld handling |
| `podman` | podman install plus the version floor quadlet needs |
| `antares_web` | The whole web stack: checkout, frontend build, derived image, config, quadlet units, nginx |
| `antares_auth` | The two connectors for the `external_auth` hook (`files/kc-rest`, `files/ldap-rest`): image built from the sources here, one container, picked by `antares_auth_provider` |
| `keycloak` | Keycloak next to Antares-Web: its database in the stack's PostgreSQL, its realm, its unit. Removes itself when `keycloak_enabled` is off |
| `antares_edge` | The front door: the one container holding the ports of the machine, TLS, certbot, and the routing to everything published on the loopback |
| `antares_build` | Runs only on the builder: turns what `antares_web` built into archives |
| `antares_solver` | Installs solver tarballs. Called twice, with `antares_solver_dest` set by the caller |
| `antares_xpansion` | Package in the shared `/home`, MPI runtime on every node |
| `antares_ssh_access` | Authorises the web machine's key on the front-end's `antares` account |
| `nfs_server` / `nfs_client` | Shared `/home`, exported by the front-end |
| `munge` | The shared Slurm authentication key |
| `slurm_common` | Packages and `slurm.conf`, common to every node |
| `slurm_frontend` | slurmctld, slurmdbd, `sacctmgr` registration |
| `slurm_compute` | slurmd |
| `slurm_launch_script` | `launchAntares.sh` in the shared `/home` |
| `monitoring_node` | The node exporter, on every machine of the inventory. Also owns the shared `load_artifacts.yml` the other two monitoring roles include |
| `monitoring_slurm` | The Slurm exporter, on the front-end, next to the controller it reads. Refuses to deploy one whose Slurm client is ahead of that controller |
| `monitoring_server` | Prometheus and Grafana, on the web machine, in the host network namespace and behind the front door |

`roles/antares_web/tasks/` is split by concern (`data_volume`, `checkout`,
`build_frontend`, `build_image`, `config`, `service`, `nginx`, `migrate`,
`ssh_key`, `load_artifacts`, `patch_frontend`). Go straight to the file whose
name matches the question. TLS and certbot are not there any more: they moved
to `roles/antares_edge/` with the front door.

## Conventions

- Fully qualified module names everywhere (`ansible.builtin.package`, never
  `package`).
- One distribution split per role, resolved from `ansible_facts['os_family']`.
  No task written twice for Debian and RedHat.
- Comments explain *why*, not what. That is the house style of this repo and
  the reason its diffs are readable. Match the density of the file you touch.
- Defaults go in `roles/*/defaults/main.yml`, computed values in
  `roles/*/vars/main.yml`. A default read by more than one role, or by a
  playbook outside any role, goes in `roles/antares_defaults/` instead - see
  the gotcha below.
- **Any new variable is documented on the `docs/` page of its area in the same
  change**, next to the prose that explains it. That documentation is the
  contract with the operator. Do not restate a default in two places: a role
  README says what the role does, not what its knobs are worth.
- Preconditions are `assert` tasks with a `fail_msg` that names the variable to
  set. Fail early and by name, rather than later on a missing file.
- Commit subjects: imperative, sentence case, under ~72 chars, no scope prefix.
  `git log --oneline -20` is the style guide.

## Gotchas that cost time

- **A shared default has to be a role default, and that role has to be in
  the play.** Ansible has exactly two tiers below the inventory: role defaults
  and inventory group vars. A playbook `vars:` block is *above* the inventory,
  so putting a default there would stop the inventory overriding it - which is
  why `antares_defaults` is a role and not a `vars_files`. Its defaults reach
  every role listed after it in the same play, and the play's own `tasks:`,
  but **nothing crosses a play boundary**: a new play that reads any shared
  variable must list `antares_defaults` first, like every play of `site.yml`
  and `verify.yml` already does. The one play with `pre_tasks:` imports it
  there instead, since pre_tasks run before `roles:` - see `build.yml`. A `when:` on a role entry sees it too, which is what keeps
  the `*_enabled` guards of `site.yml` working.
- **Fact cache.** `ansible.cfg` caches facts in `.facts/` for 7200 s. A host
  rebuilt as another distribution keeps its stale facts until a play gathers
  them again. That is why `site.yml` opens with an explicit `setup` play.
- **A Slurm node must answer to the name the configuration gives it.** Every
  daemon compares its own `gethostname()` with `DbdHost`, `SlurmctldHost` or
  its `NodeName` and refuses to run otherwise, and all of those come from
  `slurm_node_name`, which defaults to the *inventory* name.
  `roles/slurm_common/tasks/preflight.yml` reads the machine's name live -
  not from the facts, which `manage_hostname` may have made stale earlier in
  the same run - and stops before installing anything. It is what turns a
  two-minute timeout on port 6819 into a sentence naming both names.
- **`--limit` and `slurm.conf`.** It is generated from the facts of every host
  in `slurm_compute`. Limiting to a subset silently shrinks the cluster unless
  `slurm_node_cpus` / `slurm_node_real_memory` are pinned in the inventory.
- **podman 4.4 is the floor**, and it is honoured, not just checked. Keys added
  after 4.4 fail to generate on the oldest supported release. Hence
  `PodmanArgs=--network-alias=` rather than `NetworkAlias=`.
- **One distribution per cluster.** Packaged Slurm majors differ per distro and
  the daemons only interoperate across some of them. The web machine is exempt
  as long as it only talks SSH, which stops being true in the
  `standalone-slurm` shape, where it is a Slurm node like any other.
- **`artifacts/` and `.facts/` are gitignored.** Hundreds of megabytes,
  rebuildable. Never commit them.
- Third-party images are pinned to majors on purpose. Changing a tag
  invalidates the whole artefact set and needs a fresh `build.yml`.
- **The Slurm exporter is version-coupled to the cluster.** Its image ships
  its own `slurm-client`, and slurmctld serves commands of its own release and
  of the two before it, never a newer one. `roles/monitoring_slurm/tasks/
  preflight.yml` reads both versions (from `scontrol --version` and from
  `sinfo --version` inside the image) and deploys nothing when the image is
  ahead, so the shipped image works on EL 9 and Ubuntu 26.04 and is skipped on
  Debian 13, Ubuntu 24.04 and EL 10. Do not turn that into a table of
  distributions: both halves move.
- **The monitoring containers are in the host network namespace**, on no
  podman network, in no target and with no `Requires=` on anything. That is
  not an oversight to tidy up: a monitoring stack that goes down with the
  stack it watches is silent exactly when it is needed. Their mounts of `/`,
  `/etc/slurm` and the munge socket carry no `,z` for the same kind of reason,
  see `docs/monitoring.md`.

## CI

`.github/workflows/ci.yml`, six jobs: `syntax`, `targets`, `build`,
`standalone` (one machine per distribution), `slurm` (a five-VM cluster on one
runner) and `standalone-slurm` (that cluster collapsed onto the web machine,
which is the only shape where Xpansion works without a second machine). There
is no linter and no molecule: the CI is real deployments. A change that touches
a role should be reasoned about against the three matrices.
