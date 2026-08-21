# Containers: podman and quadlet

There is no Docker daemon or compose file. Each container is defined by a quadlet unit in `/etc/containers/systemd`, which `podman-system-generator` converts to systemd services at each `daemon-reload`. systemd provides scheduling, restart behavior and logs.

**Restart policy.** Every container unit carries `Restart=on-failure` with `RestartSec=10`, and a budget of `StartLimitBurst=5` over `StartLimitIntervalSec=300` in its `[Unit]` section. Quadlet copies both sections into the generated service verbatim, so this is plain systemd. `on-failure` rather than `always` on purpose: a container that keeps dying exhausts the budget in under a minute and the unit stays `failed`, where `systemctl --failed` shows it, instead of restarting forever with nobody the wiser.

**`antares-nginx` is the exception, and it has no budget.** Its ordinary failure is not a broken nginx, it is a backend that is not there yet: `proxy_pass http://antarest:5000/` resolves the upstream name once, when the configuration is parsed, so with the `antarest` container down nginx refuses to start at all (`host not found in upstream "antarest"`). Retrying until the backend is back is the recovery here rather than a loop to cut short. With a budget it was measurably worse than no front end at all: the attempts were spent while the backend crash-looped, the unit landed in `failed`, and from there every later attempt, the backend's own included, was turned away with `Start request repeated too quickly` long after the cause was fixed.

That covers nginx failing. It does not cover nginx being *stopped*, which is what `Requires=antarest.service` does to it when the backend goes down for good: a stop is not a failure, so nothing retries. The other half is on the backend, which declares `Upholds=antares-nginx.service`: while `antarest.service` is active, systemd starts the front end again whenever it finds it inactive or failed. The two together mean a backend outage, however long, ends with the interface coming back on its own, ten seconds after the backend does.

The price is that `systemctl stop antares-nginx` does not hold while the backend runs, the front end is back within seconds. Stop the target, or the backend, to take it down. `Upholds=` is deliberately not on the target and names nginx alone: every other container of the stack keeps its budget and its right to stay `failed` in plain sight.

`antares-edge` is the one container to which none of this applies, and that is what it is for: it proxies to addresses on the loopback rather than to names on the podman network, so it has nothing to resolve at startup and nothing to require. It keeps the ordinary budget: a failure there is a configuration nginx refuses or a port already taken, and neither gets better by retrying.

The retries are there for the transient case, and the boot is one. `Requires=`/`After=postgresql.service` is honoured by systemd, but readiness for a container unit comes from conmon: the unit is "started" when the container process is up, not when postgres accepts connections on 5432. `antarest` can therefore start too early after a host reboot, fail, and be restarted into a working stack ten seconds later. (Making `After=` mean what it looks like would take a `HealthCmd=` on postgresql plus `Notify=healthy`, which is podman 5.0 and later: EL 9 has it, Ubuntu 24.04 ships 4.9. Family-dependent units are what the rest of this playbook avoids, hence the retry.)

Podman runs rootful: this matters because rootless podman remaps container UIDs via `/etc/subuid`. A container running as `antares_uid` would not produce host files owned by `antares_uid` when rootless, breaking UID coherence with the NFS `/home`.

The stack is grouped by a `.target`, replacing `compose up/down`:

```bash
systemctl start   antares-web.target
systemctl stop    antares-web.target
systemctl restart antares-web.target     # propagated to containers via PartOf=
systemctl status  antares-web.target
podman ps
journalctl -u antarest.service -f
```

On the web server the generated services are `antarest`, `antarest-celery-beat`, `antarest-celery-worker`, `postgresql`, `redis`, `antares-nginx`, `antares-edge`, `antares-web-network`, and, when they are enabled, `keycloak` and the authentication connector. On the Slurm frontend, the accounting DB follows the same pattern under `slurmdb.target` (`slurmdb-mariadb`, and `slurmdb-adminer` if enabled).

The monitoring containers are the exception to the grouping, deliberately: `node-exporter` on every machine, `slurm-exporter` on the front-end, `prometheus` and `grafana` on the web server are in no target, depend on no other unit and carry `WantedBy=multi-user.target` of their own. A monitoring stack that stopped with the thing it monitors would be silent exactly when it is needed, see [Monitoring](monitoring.md).

Some container names are significant (they become DNS names on the podman network). Renaming them silently breaks the stack:

| Container | Who depends on it |
|---|---|
| `antarest`   | upstream `nginx.conf` proxies to `http://antarest:5000/` |
| `postgresql` | `config.prod.yaml` points DB to `postgresql:5432` |
| `redis`      | `config.prod.yaml` points cache to `redis` |
| `keycloak`   | the authentication connector resolves it, see `antares_auth_keycloak_url` |
| `antares-auth-*` | the backend posts logins to it, see `antarest_external_auth_url` |

`postgresql` also has the alias `postgres` (the upstream compose container_name). Compose resolved both service and container names; podman resolves only the container name and aliases.

All images are fully qualified (`docker.io/library/postgres:latest`, `localhost/antarest:latest`): Debian/Ubuntu don't set `unqualified-search-registries`, so short names are not resolved by podman and will be rejected.

