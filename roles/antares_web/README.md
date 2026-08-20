# antares_web

The web stack: the checkout, the front-end build, the derived image, the
configuration and the quadlet units that run it. It is the biggest role of the
repository, and `tasks/` is split by concern rather than by order.

| Task file | What it does |
|---|---|
| `data_volume.yml` | Puts `antarest_data_dir` on its own block device, before anything creates it. Refuses a device that is not blank |
| `checkout.yml` | Clones AntaREST at `antarest_version`, reset at every run |
| `load_artifacts.yml` | `archive` mode: loads the images and unpacks the web application produced by `build.yml` |
| `patch_frontend.yml` | Replaces the hard-coded "NNI" login label, located by content rather than by path |
| `build_frontend.yml` | Builds the web application in a Node image pinned to `webapp/.nvmrc` |
| `build_image.yml` | Stacks a derived image on the upstream one, adding the `antares` account so the UID matches the shared `/home` |
| `ssh_key.yml` | The key Antares-Web submits jobs with, authorised on the front-end by `antares_ssh_access` |
| `config.yml` | Renders `config.prod.yaml`, and the workspace directories it declares |
| `service.yml` | Writes the quadlet units and `antares-web.target`, removes the stale ones |
| `migrate.yml` | `alembic upgrade head` between postgresql and the backend, which the upstream entrypoint never runs, and the identity sequence AntaREST leaves behind its own admin row |
| `nginx.yml` | The Antares-Web nginx, which serves the built front-end and proxies `/api/` |

The role also pulls in `antares_solver` for the local launcher binaries.

**It publishes nothing on the machine.** Everything is bound to
`antarest_nginx_bind` (`127.0.0.1`), and the ports of the machine belong to
`antares_edge`, which runs after it. That separation is what keeps an identity
provider up while the backend is down, see
[The front door and TLS](../../docs/edge-and-tls.md).

**What is a variable and what is not.** The container paths in
`templates/config.prod.yaml.j2` are the other half of the mounts in
`vars/main.yml`, and `root_path: api` is the other half of the `location /api/`
of the nginx configuration: changing either alone breaks the stack, so neither
is exposed. Everything else is in `defaults/main.yml`.

`vars/main.yml` also holds `antarest_quadlet_all_units`, the list of every unit
this role has ever written. Units it no longer writes are stopped and removed
from it, which is how a deployment made before the celery pair loses its
`antarest-watcher` and `antarest-matrix-gc` containers.

Documented in [Antares-Web](../../docs/antares-web.md),
[Containers: podman and quadlet](../../docs/containers.md) and
[Background maintenance tasks](../../docs/background-tasks.md).
