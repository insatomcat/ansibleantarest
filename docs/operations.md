# Operating a deployment

## Checking a deployment

`site.yml` asserts a lot while it runs, but only about the machine it is working on. What it cannot check is what exists once every machine is done, and what a machine looks like from somewhere that is not itself. That is `verify.yml`:

```bash
ansible-playbook verify.yml
ansible-playbook verify.yml --tags firewall      # only the rulesets
```

It changes nothing beyond one marker file in the shared `/home`, which the last play removes, so it is safe against a production deployment. Each part skips itself where it does not apply (`slurm_enabled`, `hardening_firewall_enabled`, `hardening_journal_persistent`):

- **Antares-Web.** Every unit of the stack is `active`, the backend answers `/api/health`, nginx serves the built front-end and routes `/api/` to the backend, all of it asked from the controller through the front door, so the answer crosses the firewall and the whole proxy chain rather than a loopback. The other way round, the ports everything behind the front door is published on are checked to be reachable from the machine alone. With Keycloak enabled, its realm answers through the front door, which says at once that it is up, that its database was created and that the realm was imported; the authentication connector, which publishes no port, is asked for its health from inside its own container. When `antarest_data_device` is set, the data directory is checked to really be that volume's mount point and to have its entry in `/etc/fstab`: a stack that answers proves nothing about *where* it is writing, and a volume that did not come back leaves the units on the empty mount point of the boot disk, with an empty database behind a working interface. With the variable empty the state belongs on the boot disk and the check does not apply.
- **The cluster.** `slurmctld` is alive and sees every compute node of the inventory in a healthy state, the cluster is registered in the accounting database, the compute nodes really mount the front-end's `/home` (a marker written on one side and read on the other) and can execute the solvers installed in it, and a job submitted exactly the way the backend submits one - over SSH, with the key generated on the web machine, to the `antares` account of the front-end - runs on a compute node.
- **The journal.** `journalctl --header` is asked which files journald is actually writing to, and they have to be under `/var/log/journal` with nothing left under `/run/log/journal/<this machine's id>`. The id is half the question, and an EL 9 is what says so: its cloud images ship a committed `/etc/machine-id` which cloud-init resets on the first boot, so journald writes for five seconds under the image's id, is restarted under the new one and flushes that one alone. The runtime file of the first id stays in `/run` until the next reboot, OFFLINE, holding those five seconds. Nothing writes to it, no flush can move it - journald only ever flushes its own id - and it is not a journal the machine is losing. That is the location itself rather than the drop-in that asked for it, which is the point: a machine whose journal is in the `/run` tmpfs loses, at the next reboot, the log of everything that led to it, and every other check in this file is read out of that journal.

- **The firewall.** The three rulesets a deployment produces, checked from both sides. Each port that matters is looked at twice: a daemon is really listening on it, and the controller still cannot reach it while the machines that need it can. **Run this from a machine that is not in the inventory**, which the controller normally is not: a machine of the deployment is in every ruleset's trusted set, and from there every "the world cannot reach this" check is a tautology.

The same playbook runs in CI, on five virtual machines booted on one GitHub runner: see the `slurm` job of `.github/workflows/ci.yml` and `inventory/ci-cluster.yml`. It also runs on the single machine of the `standalone-slurm` job, where the cluster half is the machine itself: two of its checks become tautologies there - the shared `/home` is read on the machine that exported it, and the submitted job lands on the node it was submitted from - and everything else, the firewall included, asks exactly what it asks of a cluster.

## Changing the admin password

`antarest_admin_password` seeds the `admin` row when AntaREST creates it and is never read again: setting it on a deployment that already ran, and re-running the play, changes nothing. The password lives as a bcrypt hash in the `users` table, and the interface has no way to change one, so it is an update in the database:

```bash
HASH=$(podman exec antarest python -c \
  "import bcrypt; print(bcrypt.hashpw(b'the new password', bcrypt.gensalt()).decode())")
podman exec -i postgresql psql -U postgres -d postgres -v h="$HASH" \
  -c "UPDATE users SET _pwd = :'h' WHERE id = 1;"
```

It takes effect on the next login, no restart needed. The variable is still worth setting, for the database the next deployment initializes and for the default-secret check of the [hardening](hardening.md) role.

Creating the first user from the interface is the other thing that surprises: AntaREST inserts its admin with an explicit id and so never advances the sequence the other identities are numbered from, which then hands out that same id and is rejected. The deployment recalls that sequence in `roles/antares_web/tasks/migrate.yml`, before the backend starts, so it does not happen here.

## Major database versions

Third-party images are pinned to majors (`postgres:18`, `mariadb:11`, `redis:8`, `nginx:1.30`, `adminer:5`, `keycloak:26.7`) rather than `latest` to avoid accidental major upgrades. nginx is pinned on a minor because its major is always `1`, and on the stable branch rather than the mainline one, which stops being rebuilt as soon as the next mainline opens. Keycloak too: it has published nothing but `26.x` for two years, and it migrates its own schema on the first start of a new version without migrating back.

Since these tags are also the names of the archives `build.yml` produces, changing one invalidates the whole artifact set: re-run `build.yml` before the next `archive` deployment. The target says so explicitly rather than failing later on a missing image.

The `data/db` directory contains a PostgreSQL cluster of a given major version. PostgreSQL refuses to start on data written by a different major without `pg_upgrade`. If you use `latest`, a future major bump in the tag could silently stop your stack on the next playbook run. `archive` mode does not avoid this risk, it only postpones the problem to the next `build.yml`.

Changing major versions is therefore an explicit operation:

```bash
# dump while the old image is still present, then stop everything
podman exec postgresql pg_dumpall -U postgres > antarest-db.sql
systemctl stop antares-web.target

# update antarest_postgres_image, move the old cluster aside, redeploy
mv /var/antares-web/data/db/pgdata /var/antares-web/data/db/pgdata.old
ansible-playbook site.yml --limit <host> --tags antares_web

# the redeploy did not only create an empty cluster: it also ran the schema
# migration in it and started the backend. Empty the schema before restoring,
# with only postgres running.
systemctl stop antares-web.target
systemctl start postgresql.service
podman exec -i postgresql psql -v ON_ERROR_STOP=1 -U postgres \
    -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'

# restore, then bring the stack back up
podman exec -i postgresql psql -v ON_ERROR_STOP=1 -U postgres < antarest-db.sql
systemctl start antares-web.target
```

Do not skip the two steps before the restore, and do not drop `ON_ERROR_STOP`. Restoring into the schema the migration has just created fails in the worst possible way: `pg_dumpall` writes table data in alphabetical order and only recreates the foreign keys at the end, so a `COPY group_metadata` arriving before `COPY groups` is rejected by the constraint that is already there. Without `ON_ERROR_STOP`, `psql` skips it, leaves the table empty, exits 0, and buries the message in the hundreds of "already exists" errors from the `CREATE` statements.

Same idea for MariaDB on the Slurm frontend (use `mariadb-dump` and the `slurmdb-data` volume).

