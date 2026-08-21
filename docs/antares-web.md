# Antares-Web

The application itself: what is configurable, where it writes, and what it
exposes. The ports of the machine belong to [the front door](edge-and-tls.md),
and the units that run all this to [containers](containers.md).

## Configuration

```yaml
antarest_version: "v2.34.0"   # tag, branch or commit of the AntaREST repo
antarest_http_port: 80
antarest_force_rebuild: false # force rebuild of frontend + image
```

The rest of `config.prod.yaml` is written from the defaults of the role, `roles/antares_web/defaults/main.yml`:

```yaml
antarest_log_level: INFO           # every antarest process reads this file
antarest_worker_threadpool_size: 12
antarest_gunicorn_workers: 4
antarest_external_auth_url: ""     # empty: only the local accounts exist
antarest_external_auth_default_group_role: 10      # 10 reader ... 40 admin
antarest_external_auth_add_ext_groups: false
antarest_external_auth_group_mapping: {}
antarest_local_launcher_nb_cores_detection: true
```

What stays written in the template is what is coupled to something else on the machine: the container paths are the other half of the mounts in `roles/antares_web/vars/main.yml`, and `root_path: api` is the other half of the `location /api/` of the nginx configuration. Changing either alone breaks the stack, so neither is a variable.

The local launcher reads the cores of the machine as long as `antarest_local_launcher_nb_cores_detection` is on, and *overwrites* whatever `antarest_local_launcher_nb_cores` says. Turn detection off and the map is used, which is worth doing on a shared machine: the upstream fallback offers 22 cores out of 24 whatever the machine really has.

## Server directory layout

```
/var/antares-web/
├── AntaREST/     git checkout, disposable: nothing generated is written here
├── deploy/       config.prod.yaml, id_rsa, solvers
├── image/        derived image build context
└── data/         persistent state: studies, matrices, PostgreSQL, logs
                  a block device of its own when antarest_data_device is set

/etc/containers/systemd/     quadlet container units
/etc/systemd/system/antares-web.target

/etc/antares-web/edge/       front door configuration
/etc/antares-web/keycloak/   realm imported at the first start of Keycloak
/etc/antares-web/tls/        self-signed or hand-copied certificate
/etc/letsencrypt/            certbot state, when that provider is used
/var/www/certbot/            ACME challenge webroot, served by the front door
```

Configuration and data live outside the git checkout: changing `antarest_version` and re-running the playbook updates the application without touching the data. `data/` is the one directory worth putting on a volume of its own, see [Putting the state on its own volume](#putting-the-state-on-its-own-volume).

## Putting the state on its own volume

Everything the deployment has to keep lives under `antarest_data_dir`, that is `/var/antares-web/data`: the studies, the matrix store, the archives, the logs and the PostgreSQL cluster. By default that sits on the boot disk. On a cloud instance it is usually worth giving it a volume of its own, which can be resized, snapshotted and re-attached to another machine without going through the image.

```yaml
antarest_data_device: /dev/oracleoci/oraclevdb  # empty: stay on the boot disk
antarest_data_fstype: xfs                       # or ext4
antarest_data_mount_opts: "defaults,nofail"
```

Set the device per host rather than on a group, since the name is a property of one machine. The play formats it, writes it into `/etc/fstab` by UUID and mounts it on `/var/antares-web/data`, before the directory tree is created.

It is mounted on that path rather than somewhere else that `antarest_data_dir` would then point at, and that is deliberate: a workspace path is what its studies are recorded with in the database, so it has to read the same whether the state sits on a volume or on the boot disk. Adding or removing the volume then stays a decision about hardware alone.

The device is formatted whole, with no partition table. Growing it afterwards is the volume in the cloud console followed by `xfs_growfs /var/antares-web/data`, online, with no partition to extend first.

**A device that is not blank is refused.** A partition table, a filesystem other than `antarest_data_fstype`, or a mount anywhere but `/var/antares-web/data`: all three stop the play with what `lsblk` reported. There is no force flag, because no run of this playbook legitimately reformats a disk that holds something.

**`nofail`, and what makes it safe.** Without it, a volume that failed to attach leaves a cloud machine in emergency mode with no way in. With it alone, the machine boots, the containers start on the empty mount point and PostgreSQL initialises a fresh cluster: the interface comes back up with no studies in it while the real state sits hidden on the boot disk. So the four units that write under the data directory, `postgresql`, `antarest`, `antarest-celery-beat` and `antarest-celery-worker`, carry `RequiresMountsFor=/var/antares-web/data` as soon as `antarest_data_device` is set. A volume that did not come back is then a failed unit in `systemctl --failed`, which is the visible failure the mount option gave up.

On OCI, attach the volume as **paravirtualized**: the device is there at boot as `/dev/oracleoci/oraclevdb` with nothing to run first. An iSCSI attachment is logged into by `oci-utils` once the network is up, so it needs `_netdev` added to `antarest_data_mount_opts`.

**On a machine that already holds studies**, the play refuses to mount over a non-empty `/var/antares-web/data`: mounting hides a tree, it does not move it. Moving it is a one-off, done once with the stack stopped:

```bash
systemctl stop antares-web.target
mkfs.xfs /dev/oracleoci/oraclevdb
mount /dev/oracleoci/oraclevdb /mnt
rsync -aHAX --numeric-ids /var/antares-web/data/ /mnt/
umount /mnt
mv /var/antares-web/data /var/antares-web/data.bak
```

Then set `antarest_data_device` and run the play again: it finds the filesystem already there, mounts it and brings the stack back up. Keep `data.bak` until the interface has shown its studies, then remove it.

## Study workspaces

The directories the application exposes, one entry per workspace:

```yaml
antarest_workspaces:                 # roles/antares_web/defaults/main.yml
  default:
    dir: internal_studies
  tmp:
    dir: studies
  etudes:                            # an added one
    dir: etudes
    filter_in: ["^study-.*"]         # what the scan takes in
    filter_out: ["^_.*"]             #             and leaves out
    groups: ["etudes"]               # who sees what is found there
```

`default` is required and is not a workspace like the others: it holds the managed studies, the ones the interface creates itself, and it is the only one the watcher never scans. Its studies are named after their id, which is why the folder tree of the interface shows nothing under the managed studies and answers "no folder found" while the studies themselves are listed. Every other entry is a workspace of studies "on disk": a directory the watcher walks, whose sub-directories appear in the interface under the name of the workspace, `tmp` being the one the upstream reference configuration declares.

Each entry becomes `{{ antarest_data_dir }}/workspaces/<dir>` on the host, created by the play, and `/workspaces/<dir>` in the containers. `dir` defaults to the name of the workspace and the two differ for the workspaces above for historical reasons. That path is what the studies are recorded with in the database, so changing the directory of a workspace that already holds studies leaves those rows pointing at a path that no longer exists; taking a workspace out of the variable removes neither the directory nor its studies.

To expose a tree that already exists elsewhere, an NFS study directory for instance, mount it on `{{ antarest_data_dir }}/workspaces/<dir>` on the host and declare the workspace. The mount has to be in place before the containers start: `/workspaces` is bind-mounted into them, and a filesystem mounted underneath it afterwards stays invisible inside a running container.

Two workspaces may not share a directory, and `dir` has to be a plain directory name rather than a path, so that one cannot nest inside another. The application refuses such a configuration while reading it (`ValueError: Overlapping workspace paths found`), which means the backend never boots: it crash-loops until it exhausts its start budget, and `antares-nginx`, which requires it, goes down with it and does not come back by itself once the file is fixed (`systemctl start antares-web.target`, or another run of the play). The play checks for it before writing the file rather than leaving that to be discovered in a journal.

A directory holding a file named `AW_NO_SCAN` is skipped by the scan, and a study only reaches the interface once the watcher has run for real, see [Background maintenance tasks](background-tasks.md).

## Login label for the username field

The login form labels its identifier field "NNI" (the internal RTE identifier) hard-coded in upstream sources. The playbook replaces that label before building the frontend:

```yaml
antarest_patch_login_label: true
antarest_login_username_label: '{t("global.username")}'
```

The default reuses the project's translation key so the field displays "Username" or the localized equivalent according to the browser language, instead of a fixed string. For a fixed literal label put a quoted string: `"'Login ID'"`.

The target file changed location between releases (`webapp/src/components/wrappers/LoginWrapper.tsx` up to 2.19, `webapp/src/routes/login/index.tsx` from 2.33 on), so the task locates it by content rather than a fixed path. If a future version removes the label the task reports it and does nothing.

