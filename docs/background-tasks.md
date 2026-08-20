# Background maintenance tasks

Everything periodic runs in two containers, `antarest-celery-beat` (the scheduler) and `antarest-celery-worker` (which executes). The API process starts no background service: `server.services` is left unset in `config.prod.yaml`, which is what the application defaults to anyway.

This is not what the upstream `docker-compose.yml` does. That file still declares a `watcher` and a `matrix_gc` container, which are `IService` singletons, the mechanism the project documents as the fallback for non-Celery environments (the desktop build). Celery is the deployment schema the project favours, [stated on PR #3360](https://github.com/AntaresSimulatorTeam/AntaREST/pull/3360), and the compose file is explicitly not a production reference any more. It also covers two of the nine periodic tasks, where the celery pair covers all nine:

| Task | Default interval | Reclaims |
|---|---|---|
| `watcher_scan` | 15 min | nothing (registers studies found in the workspaces) |
| `matrices_cleaner` | 1 h | orphaned matrices |
| `blobs_cleaner` | 24 h | unreferenced blobs |
| `variable_view_cleaner` | 1 h | `output_variables_views` rows, which pin matrices |
| `tasks_cleaner` | 24 h | task rows older than 30 days |
| `auto_archiver` | cron, nightly | archives studies untouched for 60 days |
| `disk_usage` | cron, hourly | nothing (reporting) |
| `disk_space_analyzer` | cron, nightly | nothing (reporting) |
| `cache_launcher_load` | 30 s | nothing (stores the load of each launcher in the database) |

The broker is Redis, on database 1 (the event bus uses 0). The application derives the broker and result-backend URLs from the `redis` section of `config.prod.yaml`, so there is no separate broker to configure.

`cache_launcher_load` arrived with 2.34 and is the one task that talks to something outside the machine: it reads the load of every launcher that supports caching, which today means the Slurm one, and reading it is an ssh connection to the front-end. The worker therefore gets the same `/id_rsa` the backend has, mounted only when `slurm_enabled`. The local launcher reports its load live and is never cached. Should the connection fail, the API still answers `/v1/launcher/load` by querying the cluster itself, so the visible symptom is an error in the worker journal every 30 seconds rather than a broken page.

That every-30-seconds behaviour is also why `site.yml` authorises the key on the front-end *before* it starts the stack rather than at the end of the run: a worker that comes up while its key is not authorised yet spends the rest of the deployment failing to authenticate against the front-end's sshd, and an sshd is entitled to answer a stream of failed authentications by refusing the next connections from that address.

Upgrading a deployment made before this change takes the `antarest-watcher` and `antarest-matrix-gc` containers down: they stay listed in `antarest_quadlet_all_units`, which is the list of units the role stops and removes once it no longer writes them. Never run both mechanisms at once, two watchers scan the workspaces twice.

**The collectors start in dry run.** Upstream is of two minds about this: `core/config.py` defaults every one of them to destructive, while the reference `resources/deploy/config.prod.yaml` shields exactly one, the matrix collector, with `matrix_gc_dry_run: true`. This deployment applies that same protection to the other four, which matters because an instance deployed from the compose file has never reclaimed anything and the first real run has a lot of catching up to do.

```yaml
antarest_matrix_gc_dry_run: true         # roles/antares_web/defaults/main.yml
antarest_blob_gc_dry_run: true
antarest_variable_view_gc_dry_run: true
antarest_tasks_gc_dry_run: true
antarest_auto_archive_dry_run: true
antarest_watcher_scan_dry_run: false
```

The last one is the odd member of the set and is the one left at the upstream value. Dry run for the watcher scan holds no deletion back: the scan still walks the workspaces and logs how many studies it found, but `sync_studies_on_disk` is never called, so a study dropped in a workspace never reaches the interface. Setting it to `true` is a way to ask what the scan sees without letting it write, not a safety measure to relax later.

`tasks_gc` is the mildest of the four collectors: it deletes rows of the task table older than `tasks_gc_retention_days` (30 days), which is history rather than reclaimed space, since nothing but the task list of the interface reads them. It is also the one switch that needs `antarest_version` to be 2.34.0 or later to have any effect. That release rewrote the configuration loader with pydantic, where every declared field is read; the hand-written `StorageConfig.from_dict` it replaced looked up every neighbouring key but not this one, so on 2.33 and earlier the collector deletes whatever the file says.

```bash
journalctl -u antarest-celery-worker -f    # what the tasks did, or would have done
journalctl -u antarest-celery-beat -f      # what was scheduled
```

Read a few cycles before switching one off. `auto_archive` is the one to be careful with: it is not a collector, it moves studies users can see into the archive directory.

Each switch, `blob_gc` excepted, goes with the threshold that decides what is old enough to be taken. The dry run decides *that* something is deleted, these decide *which*, so they are written out next to it rather than left implicit at the upstream value:

```yaml
antarest_matrix_gc_retention_time: 3600        # seconds, not days
antarest_variable_view_gc_retention_days: 30
antarest_tasks_gc_retention_days: 30
antarest_auto_archive_threshold_days: 60
```

Intervals are the one part left implicit: every `*_sleeping_time` and `*_cron` of the upstream `docs/configuration.md` keeps its default, and `auto_archive_sleeping_time` and `auto_archive_cron` are mutually exclusive, setting both makes the application refuse to start.

Order matters between two of them. Every `output_variables_views` row pins its matrix, so `matrices_cleaner` reclaims almost nothing until `variable_view_cleaner` has run for real.

The worker runs celery's `solo` pool, one task at a time. That is not a conservative default but the correct one: the worker builds its SQLAlchemy engine in the `worker_init` signal, before `prefork` would fork its children, and the children would inherit the same database sockets. `antarest_celery_pool` and `antarest_celery_concurrency` are there for whoever has a reason to change it.

The beat container is the one oddity in the stack. It keeps its "last run" state in a shelve file whose default name is relative to the working directory, which in this image is `/`, not writable by a container running as `antares_uid`. Its unit therefore carries `PodmanArgs=--workdir=/celerybeat --entrypoint=/scripts/start.sh`: the working directory moves onto a bind mount under `data/celerybeat`, and the entrypoint has to be given absolutely because the image declares it as the relative path `./scripts/start.sh`. Both go through `PodmanArgs=` because the `WorkingDir=` and `Entrypoint=` quadlet keys only exist from podman 5.0 and Ubuntu 24.04 ships 4.9.

Intervals are not exposed as Ansible variables. Every `*_sleeping_time` and `*_cron` of the upstream `docs/configuration.md` can be added to `roles/antares_web/templates/config.prod.yaml.j2` under `storage:`. One trap: `auto_archive_sleeping_time` and `auto_archive_cron` are mutually exclusive, setting both makes the application refuse to start.

