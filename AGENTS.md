# AGENTS.md

Ansible repository that deploys Antares-Web, with an optional Slurm cluster
next to it. There is no application code here: playbooks, roles, Jinja
templates, one CI workflow and a long README.

Everything is written in English, README included. Keep it that way.

## Where to look, instead of grepping

`README.md` is the reference and is kept in sync with the code. It is long
(~680 lines), so open the section you need rather than the whole file, with
`grep -n '^##' README.md` then `sed -n 'A,Bp'`:

| Question | Section |
|---|---|
| Which distributions are claimed, and why not the others | Supported distributions |
| What a RHEL target gets on top (CRB, EPEL, OpenHPC, SELinux) | What a RHEL-compatible target needs on top |
| Every tunable and its default | Main variables |
| Where files land on the web server | Antares-Web server directory layout |
| Putting the studies and the database on a block device | Putting the state on its own volume |
| Quadlet units, podman version floor | Containers: podman and quadlet |
| celery-beat, celery-worker, the collectors | Background maintenance tasks |
| nftables, fail2ban, sshd, unattended updates, journal | Hardening |
| build once, deploy with `archive` | Build once, deploy everywhere |
| How to re-run only one part | Useful tags |
| What `verify.yml` proves | Checking a deployment |
| One machine that is also its own cluster | The cluster on the web machine itself |
| Where this diverges from the reference PDF | Differences from the PDF |
| Postgres major upgrades | Major database versions |

## Entry points

- `site.yml` - the deployment. Reads the plays in order: facts, common,
  hardening, then the Slurm half, then Antares-Web. Every role is guarded by a
  `when:` on an `*_enabled` flag.
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
- `group_vars/all.yml` - the fleet-wide knobs (587 lines, heavily commented).
  `group_vars/slurm.yml` for the cluster only.

## Roles

| Role | Job |
|---|---|
| `common` | Distribution check, repositories, base packages, the `antares` account (UID/GID guard), `/etc/hosts`, time sync |
| `hardening` | nftables, fail2ban, sshd, unattended updates, persistent journal, firewalld handling |
| `podman` | podman install plus the version floor quadlet needs |
| `antares_web` | The whole web stack: checkout, frontend build, derived image, config, quadlet units, nginx, TLS |
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

`roles/antares_web/tasks/` is split by concern (`data_volume`, `checkout`,
`build_frontend`, `build_image`, `config`, `service`, `nginx`, `tls`,
`certbot`, `migrate`, `ssh_key`, `load_artifacts`, `patch_frontend`). Go
straight to the file whose name matches the question.

## Conventions

- Fully qualified module names everywhere (`ansible.builtin.package`, never
  `package`).
- One distribution split per role, resolved from `ansible_facts['os_family']`.
  No task written twice for Debian and RedHat.
- Comments explain *why*, not what. That is the house style of this repo and
  the reason its diffs are readable. Match the density of the file you touch.
- Defaults go in `roles/*/defaults/main.yml`, computed values in
  `roles/*/vars/main.yml`, fleet-wide knobs in `group_vars/all.yml`.
- **Any new variable is documented in the README's "Main variables" section in
  the same change.** The README is the contract with the operator.
- Preconditions are `assert` tasks with a `fail_msg` that names the variable to
  set. Fail early and by name, rather than later on a missing file.
- Commit subjects: imperative, sentence case, under ~72 chars, no scope prefix.
  `git log --oneline -20` is the style guide.

## Gotchas that cost time

- **Fact cache.** `ansible.cfg` caches facts in `.facts/` for 7200 s. A host
  rebuilt as another distribution keeps its stale facts until a play gathers
  them again. That is why `site.yml` opens with an explicit `setup` play.
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

## CI

`.github/workflows/ci.yml`, six jobs: `syntax`, `targets`, `build`,
`standalone` (one machine per distribution), `slurm` (a five-VM cluster on one
runner) and `standalone-slurm` (that cluster collapsed onto the web machine,
which is the only shape where Xpansion works without a second machine). There
is no linter and no molecule: the CI is real deployments. A change that touches
a role should be reasoned about against the three matrices.
