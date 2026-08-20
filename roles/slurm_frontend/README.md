# slurm_frontend

The controller half of the cluster: `slurmctld`, the accounting database and
the registration of the cluster in it. It runs after `munge` and
`slurm_common`, which have already installed `slurm.conf` and the shared
authentication key on every node.

| Task file | What it does |
|---|---|
| `slurmdbd.yml` | The accounting database: MariaDB in a quadlet unit under `slurmdb.target`, `slurmdbd.conf`, and the daemon |
| `load_artifacts.yml` | `archive` mode: loads the accounting images `build.yml` produced |
| `sacctmgr.yml` | Registers the cluster, once the daemon answers |

`slurmctld` is restarted when `slurm.conf` changed, and not otherwise.

**The accounting database is a container, and its state is a named volume.**
`slurmdb-data` outlives the container, which is what the reference procedure
lost by declaring no volume at all. MariaDB is published on `127.0.0.1` only,
since `slurmdbd` runs on the same host, and adminer is off by default and bound
the same way, reachable through `ssh -L`.

This role is the reason the front-end pulls in the `podman` role, and the
reason `build.yml` archives a second set of images: without them an `archive`
deployment stopped halfway, the web stack running with no registry in reach
while the front-end still pulled MariaDB from Docker Hub on its first boot.

The NFS export of the shared `/home` is `nfs_server`, not this role, and it
uses `no_root_squash`: on a network you do not control, turn the firewall on.

Variables in `defaults/main.yml` and `group_vars/slurm.yml`, documented in
[The Slurm cluster](../../docs/slurm.md).
