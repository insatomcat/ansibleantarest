# Build once, deploy everywhere

By default (`antarest_image_source: build`) the target clones, builds the frontend with node and produces the image. This is standalone but requires Internet and about 4 GB of heap on the build machine. For repeated destroy/recreate cycles or multiple servers this is wasteful because the build uses `npm install` (not `npm ci`) so builds at different times may produce different artifacts.

```bash
ansible-playbook build.yml                                  # once
ansible-playbook site.yml -e antarest_image_source=archive  # many times
```

`build.yml` runs on the `builder` inventory group (see `inventory/build.example.yml`) and reuses the deployment build tasks, so artifacts are produced exactly by the same recipe that the deployment uses. A builder needs nothing installed beforehand: the play pulls in the same `podman` role the deployment uses. It never starts the stack, so a builder is not an Antares-Web server, and `site.yml` skips the `builder` group entirely: no base packages, no `antares` account, no nftables, no fail2ban and no node exporter on a machine that exists for the length of a build. `build.yml` installs on it exactly what a build needs, gathering its own facts and running the `common` preflight itself, so it stands alone whichever playbook you run first. It drops artifacts into `./artifacts` (gitignored):

| File | Content |
|---|---|
| `antarest-image.tar.gz` | backend image, UID baked in |
| `antares-auth-image.tar.gz` | the authentication connector, when `antares_auth_provider` names one |
| `thirdparty-*.tar.gz` | postgres, redis, nginx, and adminer and Keycloak if enabled |
| `slurm-thirdparty-*.tar.gz` | the accounting database images (MariaDB, and adminer if `slurmdbd_enable_adminer`), when there is a cluster |
| `monitoring-thirdparty-*.tar.gz` | the exporters, Prometheus and Grafana, when `monitoring_enabled` is on |
| `webapp-dist.tar.gz` | built web application |
| `antares-*.tar.gz` | solver tarballs |
| `antaresXpansion-*.tar.gz` | Xpansion releases, when `antares_xpansion_enabled` is on |
| `manifest.yml` | version, commit, UID, date, connector |

What goes in there is decided by the same switches as the deployment, so `antarest_enable_adminer`, `keycloak_enabled`, `antares_auth_provider`, `monitoring_enabled` and, for the cluster half, `slurm_enabled` and `slurmdbd_enabled` have to be set where the builder sees them - in the inventory, or left at their default in `roles/antares_defaults/` - and not only on the host that runs the thing. An image nobody deploys is otherwise hundreds of megabytes on the wire to every target, since a whole artefact directory travels.

Both halves of the fleet are covered, and each target only receives its own: the web machine gets the images it runs, the Slurm front-end gets nothing but `slurm-thirdparty-*`, and each machine of the fleet takes its `monitoring-thirdparty-*` by name. The solver and Xpansion tarballs stay on the controller: this directory is also the cache `antares_solver_cache_dir` and `antares_xpansion_cache_dir` read, and those two roles push what a machine needs into the shared `/home` themselves. Without that second set, `archive` mode stopped halfway - the web stack started with no registry in reach while the front-end still pulled MariaDB from Docker Hub on its first boot, quadlet units carrying podman's default pull policy. On a cluster that is genuinely offline, or behind a proxy that does not let `docker.io` through, the run would then die in the wait for MariaDB, with an error that never mentions an image.

In `archive` mode the target loads images idempotently (no retransfer if present), unpacks the frontend in the checked-out tree where nginx bind-mounts it, and takes solvers from the local cache instead of GitHub. Archives are transported with `rsync`, not the `copy` module, which is unsuitable for hundreds of megabytes.

The solver tarballs are cached for the builder's own family. A mixed fleet, or a Debian builder feeding Oracle Linux targets, wants both builds:

```yaml
antares_build_solver_os: ["Ubuntu-22.04", "OracleServer-8.10"]
```

A target that finds no tarball for its family in the cache falls back to downloading it from GitHub, so getting this wrong costs time, not a failure.

Five constraints to know:
- The builder must share the target architecture. Building amd64 on arm64 requires QEMU emulation which is slow and defeats the benefit.
- UID is baked into the image (`antarest_add_container_user`), so builder and targets must agree on `antares_uid`.
- The monitoring images are archived only when the builder sees `monitoring_enabled` (`antares_build_monitoring_images`, which is the `monitoring_images` list of `roles/antares_defaults/`). Unlike the two sets above they are not shipped wholesale to one machine: every machine of the inventory takes the one or two archives it runs, by name, so a compute node receives a node exporter and not Grafana. See [Monitoring](monitoring.md).
- The Slurm front-end's images are archived only when the builder sees `slurm_enabled` and `slurmdbd_enabled` (`antares_build_slurm_images`, which is `slurmdbd_thirdparty_images` under those two conditions). A deployment with no cluster produces no `slurm-thirdparty-*` at all.
- The build uses its own podman store (`antares_build_root`, default `/data/antares-build/store`) passed as an option and not written into the builder's `storage.conf`: build machines often lack space on `/`, and nothing changes in the system podman config.

Without a registry, each new version means `N × size` copies with no layer deduplication. For a small fleet this is fine; beyond that adding a `registry:2` instance is easier to maintain.

