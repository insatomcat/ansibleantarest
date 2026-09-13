# monitoring_node

The Prometheus node exporter, on **every** machine of the inventory: the web
server, the Slurm front-end and every compute node. One container in the host
network namespace, reading the machine through a read-only mount of `/`.

It runs whatever `monitoring_enabled` says, and that is deliberate: turning it
back off is what takes the exporters down, rather than leaving one behind on
every machine of a fleet that no longer collects them. It is also the first
thing site.yml deploys after the hardening, so that whatever happens during
the rest of the run happens under a machine that is already being watched.

| Task file | What it does |
|---|---|
| `load_artifacts.yml` | Loads a list of monitoring images from the artefact set, in `archive` mode |
| `install.yml` | The image, the `node-exporter` quadlet unit, and the pieces below |
| `service.yml` | Validates the generated unit, starts it and waits for `/metrics` |
| `remove.yml` | Stops the container, removes the unit and the staged archives |

**`load_artifacts.yml` is shared, and lives here on purpose.** It is written
for any list of images rather than for the node exporter alone, and
`monitoring_server` and `monitoring_slurm` include it with a list of their own
(`include_role: tasks_from: load_artifacts`). This is the role every machine
runs, so the file sits on the shortest path from "a machine of the fleet" to
"the image it has to load". Each machine ships only the archives it needs, by
name: a compute node receives a node exporter and not Grafana.

**The mount of `/` carries no `,z`,** unlike every other bind mount of this
deployment. That flag relabels the host directory `container_file_t`, and the
host directory here is the root filesystem of the machine; relabelling it is
not a mount option, it is an incident. The container is given
`--security-opt=label=disable` instead, bounded by the mount being read-only.
`--pid=host` goes with it, so that the exporter reads the real `/proc` rather
than the two processes of a namespace of its own.

**It listens on every interface**, which is what makes it reachable from the
machine that scrapes it. What keeps it private is the firewall: `hardening`
trusts the addresses of the inventory and drops everyone else, and `verify.yml`
probes both halves from outside. `monitoring_node_exporter_bind` pins it to one
address on a machine whose interfaces are not all equal.

Variables in `defaults/main.yml` and `group_vars/all.yml`, documented in
[Monitoring](../../docs/monitoring.md).
