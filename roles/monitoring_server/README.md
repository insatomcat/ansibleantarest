# monitoring_server

Prometheus and Grafana, on the Antares-Web machine. Both in the host network
namespace, both bound to `127.0.0.1`, and Grafana served by the front door
under `monitoring_grafana_path`.

Next to the stack rather than in it, and that is the whole design: neither
container is on the podman network, neither resolves a container name and
neither declares `Requires=` on anything. The moment the stack is down is the
moment its graphs are worth reading. It runs whatever `monitoring_enabled`
says, so turning it off takes both containers down.

| Task file | What it does |
|---|---|
| `config.yml` | `prometheus.yml` from the inventory, the Grafana provisioning, the two dashboards |
| `install.yml` | The directories, the images, the two quadlet units |
| `service.yml` | Validates the units, starts them, waits for `/-/ready` and `/api/health` |
| `remove.yml` | Stops both containers and removes the units, leaving the databases alone |

**The scrape targets come from the facts, not from `ansible_host`.** The same
rule as the trusted set of the firewall, and for the same reason: `ansible_host`
may be a name only the controller resolves or a public address in front of a
NAT. A machine whose facts are not in the play is therefore not scraped, which
is what a `--limit` run does. The role warns about it by name, and `verify.yml`
fails on it.

**The two databases live under `antarest_data_dir`,** so they land on the block
device when the deployment has one, and each directory is owned by the uid of
its image - a Prometheus data directory owned by root is a container that
starts and dies on its first write.

**Grafana is provisioned, not configured by hand.** The datasource carries a
fixed uid (`antares-prometheus`) because the dashboards name it, and the
dashboards are mounted read-only: Grafana rewrites a provisioned dashboard from
its file at every start, so what an operator changes in the interface has to be
saved under another name. They are plain JSON rather than templates - a Grafana
dashboard is full of `{{ label }}` legends, which is Jinja's own syntax, and
this way the file is exactly what the interface exports.

Variables in `defaults/main.yml` and `roles/antares_defaults/`, documented in
[Monitoring](../../docs/monitoring.md).
