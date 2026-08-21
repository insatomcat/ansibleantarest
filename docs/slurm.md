# The Slurm cluster

Optional: with `slurm_enabled: false` studies run with the local launcher on
the web machine. What the cluster buys is a queue, the return code of a run,
and [Antares-Xpansion](solvers.md#antares-xpansion).

## Main variables

```yaml
slurm_cluster_name: antares
slurm_partition: antares
slurm_select_type: "select/cons_tres"   # use select/linear for exclusive nodes
slurmdbd_innodb_buffer_pool_size: "1G"
slurmdbd_mariadb_image: "docker.io/library/mariadb:11"
slurmdbd_adminer_image: "docker.io/library/adminer:5"
slurmdbd_enable_adminer: false          # published on 127.0.0.1 only
slurm_launcher_ssh_port: 22             # how Antares-Web reaches the front-end
slurm_launcher_default_wait_time: 900   # seconds
slurm_launcher_default_time_limit: 172800
```

`slurmdbd_thirdparty_images` is the list those two image pins produce, and the accounting database's counterpart of `antarest_thirdparty_images`: `build.yml` archives exactly that list and the front-end checks exactly that list is loaded before starting anything, so the two cannot drift. It lives in `roles/antares_defaults/` rather than in `slurm_frontend` because the builder reads it and never runs that role, and so does `slurmdbd_enable_adminer`, which it is built from.

Compute node characteristics (`CPUs`, `SocketsPerBoard`, `CoresPerSocket`, `ThreadsPerCore`, `RealMemory`) are derived from Ansible facts and can be overridden per-host in the inventory using `slurm_node_cpus`, `slurm_node_sockets`, `slurm_node_cores_per_socket`, `slurm_node_threads_per_core` and `slurm_node_real_memory`.

The maximum cores selectable in the job submission UI is capped to the smallest compute node, otherwise jobs requesting more cores than any node has will remain pending forever.

On a RHEL-compatible cluster, Slurm comes from OpenHPC because no EL repository ships it. Which OpenHPC follows the major of the machine, since upstream publishes one tree per series:

```yaml
slurm_repo: openhpc          # `distro` on the Debian family

# slurm_openhpc_release is picked from the major of the machine:
#   EL 9  -> http://repos.openhpc.community/OpenHPC/3/EL_9/x86_64/ohpc-release-3-1.el9.x86_64.rpm
#   EL 10 -> http://repos.openhpc.community/OpenHPC/4/EL_10/x86_64/ohpc-release-4-1.el10.x86_64.rpm
# Set it to a full URL to pin another version or a local mirror.
```

The release rpm is installed with the GPG check disabled, since it is what brings in the key its own repositories are signed with; everything pulled from them afterwards is verified normally. On a machine where nothing provides the `epel-release` capability the release rpm requires, Oracle Linux 10 being the case today, it is installed with `rpm -Uvh --nodeps` instead, see the table in [what a RHEL-compatible target needs on top](requirements.md#what-a-rhel-compatible-target-needs-on-top). Package names then carry an `-ohpc` suffix (`slurm-ohpc`, `slurm-slurmctld-ohpc`, `slurm-slurmd-ohpc`, `slurm-slurmdbd-ohpc`) and nothing else moves: the daemons, `/etc/slurm`, the `slurm` account and the generated `slurm.conf` are the same as on Debian. Set `slurm_repo: distro` to install Slurm yourself and only let the playbook configure it.

## The name a machine answers to

Every name the generated configuration carries - `DbdHost`, `SlurmctldHost`, `AccountingStorageHost`, `NodeName` - comes from `slurm_node_name`, which defaults to the inventory name:

```yaml
slurm_node_name: "{{ inventory_hostname.split('.')[0] }}"   # inventory/group_vars/slurm.yml
```

That is right whenever the inventory names machines the way they name themselves, and wrong on a machine whose hostname was decided by someone else: a cloud image, an installer, a corporate naming scheme. It matters more than it looks, because **every Slurm daemon compares its own `gethostname()` with what the configuration names it and refuses to run on a mismatch**: `slurmdbd` and `slurmctld` exit with `This host not configured to run SlurmDBD ((web-1 or web-1) != antares-solo)`, and `slurmd` simply never registers, leaving the node down in `sinfo`.

`slurm_common` therefore reads the machine's own name before anything is installed and stops there, naming both names and the three ways out. Without it the run gets much further and dies in "Wait for slurmdbd to listen", on a two-minute timeout for a port, with nothing in the message about a name.

Two ways to make the two agree, and one to say you know better:

```yaml
# the usual one: keep the inventory name, tell Slurm the machine's own
slurm_node_name: antares-web-1

# or the other way round: rename the machine after the inventory. Applied
# immediately, but a reboot is what makes everything already running agree
manage_hostname: true

# or deploy anyway, for a cluster whose daemons are told their name elsewhere
slurm_hostname_check: false
```

`slurm_node_ip` follows the same idea for the address, which is read from the facts of the default route and overridden per host when that points at the wrong interface.

## The cluster on the web machine itself

One machine can play every part: the web application, the Slurm controller, the accounting database, the NFS export and the single compute node that runs the studies. It is one inventory away, and nothing in the roles is specific to it - each of them decides what it installs from the groups the host is in rather than from the play it sits in, so a host listed three times gets the union of the three behaviours.

```yaml
all:
  hosts:
    antares1:
      ansible_host: 203.0.113.20

  children:
    antares_web:
      hosts:
        antares1:
    slurm:
      children:
        slurm_frontend:
          hosts:
            antares1:
        slurm_compute:
          hosts:
            antares1:
```

**Why bother, when a single machine already runs studies with the local launcher.** Because the local launcher ignores the Xpansion mode: a study launched with the box ticked runs an ordinary simulation and comes back green, see [Limitations](limitations.md). Xpansion is the Slurm launcher's only, and this is the smallest deployment that has one. Two other things come with it: a queue, so a second study waits instead of competing for the same cores, and the return code of the run, which `launchAntares.sh` turns into a failed job rather than a green study over nothing.

What it costs, in the order the costs actually bite:

- **The machine has to be shared, and Slurm does not know that.** `slurm_node_real_memory` defaults to 95 % of the machine's memory, which is right for a compute node that does nothing else and wrong here: Postgres, Redis, the backend, nginx and MariaDB live on the same kernel, and a Benders run peaking at 1.1 GB in an allocation that was granted everything ends with the OOM killer choosing among them. Pin the two knobs in the inventory, on that host: `slurm_node_real_memory` to what is left once the web stack has its share, and `slurm_node_cpus` to the cores you are willing to hand out. `slurm_launcher_nb_cores_max` follows the second one, since it is capped to the smallest compute node.
- **Size it for Xpansion, not for the interface.** Measured on the five-machine lab: 1.4 GB for the web stack, 499 MB for the front-end daemons, 271 MB for slurmd, and 1.1 GB more for the `SmallTestFiveCandidates` example - which is a five-candidate toy. That is the floor of a machine that only has to prove it works.
- **The web machine stops being exempt from "one distribution per cluster".** It is exempt today because it only talks SSH; here it is a Slurm node, and on EL that means the OpenHPC repository and its packages land on the machine that faces the internet.
- **Two copies of the solvers.** One under `antarest_base_dir` for the local launcher, one in the shared `/home` for the Slurm one, plus about 250 MB per Xpansion release. And the scratch directories and the zipped results of every run land in `/home/antares`, which [putting the state on its own volume](antares-web.md#putting-the-state-on-its-own-volume) does not cover: that section is about `/var/antares-web`.

The CI deploys this shape on every distribution that can carry a Slurm node, on every pull request: see the `standalone-slurm` job of `.github/workflows/ci.yml` and `inventory/ci-standalone-slurm.yml`. `verify.yml` runs on it whole, the firewall included, which is where the one thing that is genuinely new gets checked - a single ruleset that is the union of the three a cluster spreads over three machines.

## The launch script and what a failed run looks like

`launchAntares.sh` is rendered on the front-end from `roles/slurm_launch_script/templates/launchAntares.sh.j2` and is the script Antares-Web names in `slurm_script_path`. It is derived from `launchAntares_v1.1.2.sh` of antares-launcher, which is a template with site-specific holes in it (`/path/to/...`, `module load xpress|ampl|R`), not a runnable program.

One difference is worth knowing about, because it changes what you see in the interface: **the script exits on the return code of the run**. Upstream does not, and the consequence is not theoretical. A solver killed by the kernel's OOM killer, or one that rejects an option, leaves a script that keeps going, zips the partial study, and returns 0 - so Slurm records the job as `COMPLETED` and Antares-Web shows the study green even though nothing was computed. Here the code of the solver, or of the Xpansion launcher, is captured, written into the job's `_job_data_<id>.txt` log, and used as the exit code of the script.

Everything after the run still happens before that exit: the post-processing, the final zip and the cleanup of the scratch directory. That matters, and it is what makes this safe rather than a way to lose results. A job in `FAILED` state maps to `finished_with_error` in antares-launcher, which still downloads the final zip and the logs, and `_handle_failure` on the Antares-Web side still imports whatever output it finds before marking the job failed. So a failed run comes back red, with its logs, and with its partial results when there are any.

