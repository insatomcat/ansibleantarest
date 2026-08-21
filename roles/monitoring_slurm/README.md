# monitoring_slurm

The Slurm exporter, on the front-end: one container in the host network
namespace running the `sinfo`, `squeue`, `sdiag` and `sshare` of its own image
against the `slurmctld` of that machine, and turning their output into metrics.
It is not part of the Slurm daemons and nothing depends on it - a scrape that
fails is a gap in a graph, never a job that does not run.

| Task file | What it does |
|---|---|
| `preflight.yml` | The munge socket, the image, and the version pair below |
| `install.yml` | The `slurm-exporter` quadlet unit |
| `service.yml` | Starts it, waits for `/metrics`, and warns if no `slurm_` metric came back |
| `remove.yml` | Stops and removes it when either switch is off, or when the versions do not allow it |

**The version pair is the whole subtlety of this role.** The image carries its
own `slurm-client`, and Slurm's rule is one-directional: a controller serves
the commands of its own release and of the two before it, never a newer one.
`preflight.yml` therefore reads both versions - the cluster's from
`scontrol --version` on the machine, the image's from `sinfo --version` inside
the image - and when the image is ahead it deploys nothing, says why, and
records the answer in a cached fact that `monitoring_server` reads, so
Prometheus is not given a target that cannot answer either. Neither version is
hardcoded: the distributions ship anything from 23.11 to 25.11 and the image
follows its own base, so a table here would be wrong within a release.
`monitoring_slurm_version_check: false` deploys it anyway.

**Its two mounts carry no `,z`,** unlike every mount of the Antares-Web stack:
relabelling `/etc/slurm` and the munge run directory `container_file_t` would
take them away from `slurmctld` and `munged`, which is to say it would take the
cluster down. The container gets `--security-opt=label=disable` instead. It
also runs as root inside, because the image's own user is in *its* munge group,
whose gid has no reason to match the one this machine gave munge - and on the
RHEL rebuilds that directory is `0750`.

The munge *key* is not mounted, although the image's documentation lists it: a
client does not read it, `munged` signs the credentials, and `munged` is on the
host.

Variables in `defaults/main.yml` and `group_vars/all.yml`, documented in
[Monitoring](../../docs/monitoring.md).
