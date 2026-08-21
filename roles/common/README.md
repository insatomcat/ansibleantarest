# common

The first role of `site.yml`, on every machine. It makes a blank VM into a
machine the rest of the playbook can assume things about, and nothing here is
specific to Antares-Web.

| Task file | What it does |
|---|---|
| `preflight.yml` | Refuses a distribution that is not in `supported_distros`, by name, before anything is installed |
| `packages.yml` | Prepares the package manager: the dpkg lock timeout on the Debian family, CRB and EPEL on the RedHat one |
| `main.yml` | Base packages, the `antares` account, the hostname, `/etc/hosts` for the cluster, time synchronisation |

**The account is the contract.** `antares_uid` / `antares_gid` have to be free
and identical on every machine, because the same files are read across the
NFS-shared `/home` and the UID is baked into the backend image. The role reads
`/etc/passwd` and `/etc/group` first and stops on a collision rather than
creating an account with whatever id the system hands out, then reads the
account back to check it really holds the pair it asked for.

`/etc/hosts` is written from the facts of the machines in the `slurm` group, so
the cluster resolves without a DNS zone. That makes this role, like
`slurm_common`, sensitive to `--limit`: a run that gathers a subset writes a
subset.

Variables live in `defaults/main.yml`, the shared ones in
`roles/antares_defaults/`. What the two families need on top is documented in
[Requirements](../../docs/requirements.md).
