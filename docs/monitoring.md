# Monitoring

Off by default. One variable turns it on for the whole fleet:

```yaml
monitoring_enabled: true
monitoring_grafana_admin_password: "something that is not admin"
```

What that deploys, all of it in quadlet units like the rest of the deployment:

| Container | Where | What it reads |
|---|---|---|
| `node-exporter` | every machine of the inventory | the machine itself: CPU, memory, filesystems, network, load, uptime |
| `slurm-exporter` | the Slurm front-end | the cluster as its controller sees it: queue, partitions, node states, scheduler internals |
| `prometheus` | the Antares-Web machine | the two above, on every machine, every `monitoring_scrape_interval` |
| `grafana` | the Antares-Web machine | Prometheus, and it is what the operator opens |

Grafana is served by the front door under `monitoring_grafana_path` (`/grafana`), behind the same certificate as everything else: `https://<domain>/grafana/`, with `monitoring_grafana_admin_user` and the password above.

The rest of the knobs, all in `group_vars/all.yml` because the builder archives the images and the front door routes to Grafana, and neither can read a role default:

```yaml
monitoring_slurm_enabled: "{{ slurm_enabled }}"   # the exporter on the front-end

# Images, pinned like every other third-party image of this deployment
monitoring_node_exporter_image: "docker.io/prom/node-exporter:v1"
monitoring_slurm_exporter_image: "docker.io/sckyzo/slurm-exporter:1.8.4"
monitoring_prometheus_image: "docker.io/prom/prometheus:v3"
monitoring_grafana_image: "docker.io/grafana/grafana:13.1"

# The exporters answer on the machine's own address, Prometheus and Grafana
# on 127.0.0.1 alone
monitoring_node_exporter_port: 9100
monitoring_slurm_exporter_port: 9341
monitoring_prometheus_port: 8084
monitoring_grafana_port: 8083

monitoring_grafana_path: /grafana
monitoring_prometheus_path: /prometheus
monitoring_prometheus_public: false

monitoring_scrape_interval: 30s
monitoring_prometheus_retention: 30d

monitoring_grafana_admin_user: admin
```

Per-role, in `roles/monitoring_*/defaults/main.yml`: `monitoring_node_exporter_bind` and `monitoring_slurm_exporter_bind` (empty, every interface), `monitoring_node_exporter_mount_exclude` and `monitoring_node_exporter_fs_exclude` (what the filesystem collector ignores), `monitoring_slurm_exporter_disabled_collectors`, `monitoring_slurm_exporter_command_timeout`, `monitoring_slurm_exporter_extra_flags` and `monitoring_slurm_version_check`, `monitoring_base_dir` (`/var/antares-monitoring`, where the image archives are staged), `monitoring_server_dir` and `monitoring_server_data_dir`, `monitoring_prometheus_uid` and `monitoring_grafana_uid` (the uids the two images run as, and therefore own their databases), `monitoring_extra_scrape_jobs`, `monitoring_node_address`, `monitoring_grafana_root_url` and `monitoring_grafana_check_updates`. Each is commented where it is defined; the ones worth a paragraph have one below.

## Why it is next to the stack rather than in it

Every container here runs in the **host network namespace** and depends on no other unit. Nothing is on the podman network of Antares-Web, nothing resolves a container name, and no unit declares `Requires=` on the stack.

That is the whole design. The moment the stack is down is the moment its graphs are worth reading, and a Prometheus that needed `antares-web.network` to be up would go down with the incident it exists to explain. It is the same reasoning that makes the front door a container of its own, see [The front door and TLS](edge-and-tls.md).

Two consequences worth knowing. The exporters listen on every interface, because the machine that scrapes them is the web server and not themselves: what keeps them private is the firewall, whose trusted set is exactly the machines of the inventory (see [Hardening](hardening.md)). Prometheus and Grafana are the other way round, bound to `127.0.0.1` like everything else this deployment publishes, and reached through the front door alone. `verify.yml` checks both halves from outside.

## What is scraped

The target list is generated from the inventory, by the address each machine's *facts* report - not `ansible_host`, which may be a name only the controller resolves or a public address in front of a NAT. A machine whose facts are not in the play contributes nothing, which is the one way to end up with a hole in the graphs:

```bash
ansible-playbook site.yml --limit antares_web    # renders prometheus.yml with one target
```

The playbook says so while it runs, and `verify.yml` fails on it. Re-run without `--limit`, or pin the address on the host that needs it:

```yaml
slurm_node_1:
  monitoring_node_address: 10.1.0.13   # the machine is scraped here rather than on its default route
```

Targets carry an `instance` label set to the inventory name rather than to `address:port`, so a graph names a machine the way the operator does and a machine rebuilt at another address keeps its history. `role` says which group it came from, and `job` is `node`, `slurm` or `prometheus`.

Anything else worth scraping next to it goes in `monitoring_extra_scrape_jobs`, in Prometheus' own spelling; the generated jobs cover what this deployment installs and nothing more.

## Grafana

Two dashboards are provisioned, in the `Antares` folder: **Antares fleet** (the machines) and **Antares Slurm cluster** (the queue and the nodes, only where there is a cluster being scraped). They are read from a read-only mount, so Grafana rewrites them from their files at every start: a dashboard improved from the interface has to be saved under another name, which is what keeps the deployment's own reproducible. Improving the shipped ones is a matter of exporting the JSON from the interface and pasting it back into `roles/monitoring_server/files/grafana/dashboards/`.

`monitoring_grafana_admin_password` seeds the administrator and nothing more: Grafana reads it when it creates its database and ignores it ever after, exactly like the Antares-Web and Keycloak passwords. Afterwards it is:

```bash
podman exec -it grafana grafana cli admin reset-admin-password 'the new one'
```

The datasource is provisioned too, `editable: false`, with the fixed uid `antares-prometheus` the dashboards name.

## Prometheus

Not published by default: its expression browser is an unauthenticated read of every metric of the fleet, and Grafana is what this deployment gives people to look at. Reach it with a tunnel:

```bash
ssh -L 8084:127.0.0.1:8084 <the web machine>    # then http://127.0.0.1:8084
```

Or publish it behind the front door, where it lands under `monitoring_prometheus_path`:

```yaml
monitoring_prometheus_public: true
```

That also sets `--web.external-url`, without which Prometheus builds its links at the root and answers 404 on its own static files. Note that it puts an unauthenticated endpoint on the internet on a machine reachable from it: nginx is where a `auth_basic` belongs if that is not wanted.

`monitoring_prometheus_retention` (30 days) is what decides the size of the database, and it lives under `antarest_data_dir` - on the block device when there is one, see [Antares-Web](antares-web.md). A dozen machines at a 30 second interval cost a couple of gigabytes a month.

## The Slurm exporter

It is the one container of this deployment whose *version* has to agree with something outside it. The image carries its own `slurm-client`, which it runs against the `slurmctld` of the front-end, and Slurm's rule is one-directional: a controller serves the commands of its own release and of the two before it, never a newer one. A client that is ahead gets `Zero Bytes were transmitted or received`, and the exporter then answers `/metrics` with its Go runtime metrics and nothing under `slurm_`.

**The playbook checks the pair rather than trusting it.** Before deploying anything it reads the cluster's version from the machine (`scontrol --version`) and the client's from the image itself (`sinfo --version` inside it), and when the image is ahead it deploys no exporter at all, says why, and does not declare it to Prometheus either. Nothing is left broken and no target goes red; the machines are still monitored, the queue is not.

Where that lands today, with an image whose client is Slurm 25.11:

| Cluster | Slurm | The shipped image |
|---|---|---|
| Ubuntu 26.04 | 25.11 | works |
| EL 9, OpenHPC 3 (Oracle, Rocky, CentOS Stream) | 25.11 | works |
| EL 10, OpenHPC 4 | 25.05 | skipped, client ahead |
| Debian 13 | 24.11 | skipped, client ahead |
| Ubuntu 24.04 | 23.11 | skipped, client ahead |

Neither half of that table is hardcoded anywhere: both versions are read at deploy time, so the day OpenHPC 4 moves or the image is repinned, the answer follows without a line changing here.

The way out is an image whose client matches the cluster:

```yaml
# the publisher tags per release; a client of the cluster's own major is what
# this needs
monitoring_slurm_exporter_image: "docker.io/sckyzo/slurm-exporter:1.8.4"

# their `-minimal` variants carry no slurm-client at all and run the host's
# own binaries instead, which then have to be mounted and pointed at
monitoring_slurm_exporter_volumes: ...          # plus /usr/bin and the libs
monitoring_slurm_exporter_extra_flags: ["--slurm.bin-path=/usr/bin"]

# monitoring_slurm_version_check: false          # deploy it whatever the pair
# monitoring_slurm_enabled: false                # or do without it entirely
```

With the check off, or with an image the check cannot read, the exporter is deployed anyway; the role then warns after the first start if `/metrics` comes back with no `slurm_` metric in it, and `verify.yml` fails on the same thing.

What the exporter needs from the machine is `/etc/slurm` and the munge socket, both mounted read-only. Two deliberate departures from the habits of the rest of this repository, both in `roles/monitoring_slurm/vars/main.yml`:

- those mounts carry **no `,z`**, unlike every mount of the Antares-Web stack. That flag relabels the host directory `container_file_t`, and relabelling `/etc/slurm` and `/var/run/munge` would take them away from `slurmctld` and `munged` - it would take the cluster down. The container is given `--security-opt=label=disable` instead, which is the trade the node exporter makes for the same reason with its read-only mount of `/`.
- it runs as **root inside the container**. The image's own user is in *its* munge group, whose gid comes from the base image it was built on; on the RHEL rebuilds the munge run directory is `0750`, so a gid that does not match is a permission denied at the first scrape.

The munge *key* is not mounted, although the image's documentation lists it: a client does not read it, `munged` signs the credentials and `munged` is on the host.

## Operating it

The units are independent of each other and of everything else on the machine, which is what makes them worth trusting during an incident. There is no target grouping them:

```bash
systemctl status node-exporter.service      # on any machine
systemctl status slurm-exporter.service     # on the front-end
systemctl status prometheus.service grafana.service
journalctl -u prometheus.service -f
```

Where things are on the web machine: `/etc/antares-web/monitoring` for the rendered configuration (the scrape targets, the Grafana provisioning, the dashboards) and `{{ antarest_data_dir }}/monitoring` for the two databases. On every machine, `/var/antares-monitoring/artifacts` holds the image archives in `archive` mode, and nothing else.

Turning `monitoring_enabled` back off is a supported operation and not a matter of forgetting it: the roles run either way, so the next `ansible-playbook site.yml` stops every container and removes every unit. The databases are left where they are - dropping a month of samples is a decision for an operator with an `rm`, not for a variable.

## In `archive` mode

The images travel in the artefact set like the others, under a prefix of their own (`monitoring-thirdparty-*`), and each machine loads by name the one or two it runs: a compute node receives a node exporter and not Grafana. As with Keycloak, the switches have to be set where the *builder* sees them, since `build.yml` only archives what it is told about:

```bash
ansible-playbook build.yml -e monitoring_enabled=true
```

A target that turns monitoring on against an artefact set built without it fails by name, before anything is started. See [Build once, deploy everywhere](build-and-deploy.md).
