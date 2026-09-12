# Requirements

- A Debian-family or RHEL-compatible distribution on all target machines (see supported distros below), root access via `sudo`, and Python 3 installed.
- The `antares_web` machine needs Internet access (container images, npm and Python packages, solver binaries).
- The Slurm frontend also downloads solvers from GitHub.
- A free UID/GID that is identical on all machines for the `antares` account: `9000` by default. The playbook will refuse to continue if the UID/GID are already taken.
- Ansible ≥ 2.15 on the control machine, and `ansible.posix` available.

## Supported distributions

Two families are supported: Debian (Debian and Ubuntu, `apt`) and RedHat (Oracle Linux and the other RHEL rebuilds, `dnf`). Every install goes through `ansible.builtin.package`, and everything that actually differs between the two (package names, service names, repositories) is resolved from `ansible_facts['os_family']` in one place per role, so no task exists twice.

```yaml
supported_distros:      # group_vars/all.yml
  - "Debian 13"
  - "Ubuntu 24"
  - "Ubuntu 26"
  - "OracleLinux 9"
  - "OracleLinux 10"
  - "RedHat 9"
  - "RedHat 10"
  - "Rocky 9"
  - "Rocky 10"
  - "CentOS 9"
  - "CentOS 10"
```

That list is a claim, not a wish. Every line but one is deployed on every pull request by the CI, three times over: one machine running Antares-Web on its own, a five-machine cluster, and one machine playing every part at once. RedHat is the exception, on both counts: the CRB repository id and the `epel-release` URL are written for it, but it needs a subscription the CI has not got, so it is listed on the strength of its rebuilds rather than of a run.

Two things are deliberately absent. **Debian 12 and Ubuntu 22.04**, which ship podman 4.3.1 and 3.4.4 where quadlet needs 4.4: the playbook would stop on them a few tasks after the distribution check, so claiming them would be worse than leaving them out. **AlmaLinux**, which nothing here has ever run on; it is the same code path as Rocky Linux, exercised twice per pull request, so adding `"AlmaLinux 9"` yourself is reasonable, it is just not something this repository asserts on your behalf.

The playbook aborts on unsupported distros and prints the variable to extend. A rebuild of a supported major that is not in the list is usually fine to add. Set `distro_check_enabled: false` to disable the check entirely.

Podman comes from the distribution on both families and is recent enough everywhere: quadlet has been part of podman since 4.4, Debian 13 ships 5.x, Ubuntu 24.04 ships 4.9, EL 9 has been on 4.4 or later since 9.2, EL 10 ships 5.x and CentOS Stream 10 is already on 6.x. The playbook checks the version and stops rather than writing units nothing would generate.

4.4 is a floor the units keep honouring and not only a number that gets checked, because quadlet gained keys after it and a unit written with one of those fails to generate on the oldest supported release rather than on the version that introduced the key. That is why the `postgres` network alias goes through `PodmanArgs=--network-alias=postgres` rather than through the `NetworkAlias=` key it deserves: that key landed in podman 5. Both spellings produce the same `podman run` command line, measured on 4.9.3 and on 5.4.2. Ubuntu 24.04 is a CI target for the same reason: it is the release that would notice.

Important cluster note: use one distribution per cluster. Packaged Slurm versions differ (23.11 on Ubuntu 24.04, 24.11 on Debian 13, 25.11 from OpenHPC 3 on EL 9 and 25.05 from OpenHPC 4 on EL 10) and the daemons `slurmctld` / `slurmd` / `slurmdbd` interoperate only across certain major versions. The generated `slurm.conf` works for all of them, but do not mix a front-end on Debian 13 with compute nodes on Oracle Linux 9 in the same cluster. The `antares_web` machine is unaffected: it talks to the Slurm frontend only via SSH, so a Debian web server driving an Oracle Linux cluster is fine.

On the Debian family the dpkg lock is tolerated up to `apt_lock_timeout` seconds (default 300), because Ubuntu images often run `apt-daily` and `unattended-upgrades` on boot. Rather than being passed to every install, this is written to `/etc/apt/apt.conf.d/80-antares-lock-timeout`, so it also covers the apt commands the playbook does not run itself.

## What a RHEL-compatible target needs on top

Everything below is done by the playbook. It is listed because it changes the machine in ways worth knowing about.

| Topic | What happens |
|---|---|
| **Repositories** | The `common` role installs `dnf-plugins-core` (EL 10 is still dnf 4, 4.20 on Oracle Linux 10.1), enables **CRB** (`ol9_codeready_builder` / `ol10_codeready_builder` on Oracle Linux, `crb` on the other rebuilds) and **EPEL** (which Oracle's release package ships disabled, `epel` on the other rebuilds). Both are needed: `htop`, `fail2ban` and `certbot` come from EPEL, which is built against CRB. `common_epel_repo` is a pattern matched against `dnf repolist --all` rather than an id, because Oracle's carries the update level from EL 10 on (`ol9_developer_EPEL`, but `ol10_u1_developer_EPEL` on Oracle Linux 10.1). The run stops if it matches nothing: enabling a repository that does not exist is not an error for dnf, and the packages would go missing much later. |
| **Slurm** | No EL repository ships Slurm, neither the base repositories nor EPEL. It comes from **OpenHPC** instead (`slurm_repo: openhpc`, release rpm in `slurm_openhpc_release`). Package names carry an `-ohpc` suffix; `/etc/slurm`, the systemd units and the `slurm` account are where they are everywhere else. Set `slurm_repo: distro` if you install Slurm yourself. **One OpenHPC series per major**, because upstream publishes no tree twice: **OpenHPC 3 for EL 9** (Slurm 25.11), **OpenHPC 4 for EL 10** (Slurm 25.05, so the newer major gets the older Slurm). The major of the machine picks the release rpm, and a major OpenHPC publishes nothing for is refused by name rather than left to fail on a missing package. |
| **The `epel-release` dependency** | The OpenHPC release rpm requires the `epel-release` capability. `oracle-epel-release-el9` provides it, `oracle-epel-release-el10` does not, and Oracle's EPEL 10 mirror does not carry Fedora's `epel-release` either, so on **Oracle Linux 10** `dnf` refuses the release rpm with `nothing provides epel-release` although EPEL is installed and enabled. The playbook asks whether anything on the machine or in its repositories provides that capability, and installs the release rpm with `rpm -Uvh --nodeps` when nothing does. The dependency is nominal there: on EL 10 the whole Slurm set resolves from OpenHPC plus `baseos` and `appstream`, `munge` and `freeipmi` included, and nothing comes from EPEL. The day Oracle puts the `Provides` back, the run goes back to `dnf` on its own. |
| **Solver binaries** | The Ubuntu 22.04 build of Antares Simulator is linked against glibc 2.35 and does not start on EL 9, which has 2.34. `antares_solver_os` therefore follows the family and picks the project's **Oracle Linux 8** build there, which runs on EL 9 and EL 10 alike. |
| **SELinux** | Left enforcing. Container bind mounts carry the `z` relabelling flag (`container_volume_opts`), the booleans `nfs_export_all_rw` and `use_nfs_home_dirs` are set on the NFS server and the clients, and the Let's Encrypt tree gets a `semanage fcontext` entry so that a renewal does not silently produce a certificate the front door cannot read. |
| **firewalld** | Enabled out of the box on the RHEL rebuilds, SSH only. The default is no host firewall (the cloud security group is enough), so the role masks it. Turn `hardening_firewall_enabled` on for the nftables table instead. Set `hardening_manage_firewalld: false` to leave firewalld alone; the podman role then puts the `podman*` bridges in `trusted`, without which aardvark-dns and `PublishPort` are dropped. That covers what the containers publish and nothing else: the host services the machines use between themselves (NFS 2049, Slurm 6817-6819) are then yours to open in firewalld. |
| **Unattended updates** | `dnf-automatic` with `upgrade_type = security` instead of `unattended-upgrades`, with the same policy: security updates only, no automatic reboot. |

## The antares account: choosing UID/GID

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

