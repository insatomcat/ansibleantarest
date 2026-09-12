# antares_edge

The front door: the one container that holds the ports of the machine, and the
only place TLS is terminated. It runs last in the `antares_web` play, because
the ACME challenge that gets its certificate is answered through it and there
has to be something behind it worth serving.

| Task file | What it does |
|---|---|
| `tls.yml` | The certificate material: generated, copied, or the directory certbot will fill |
| `nginx.yml` | The configuration: the routes to Antares-Web, to Keycloak, and to `antares_edge_extra_routes` |
| `service.yml` | The `antares-edge` quadlet unit |
| `certbot.yml` | Obtains the Let's Encrypt certificate through the running front door, and installs the reload hook |

**It proxies to addresses, never to names, and runs in the host network
namespace.** That is the whole design: nginx resolves an upstream name when it
parses its configuration, so a front door on the podman network would be down
for as long as any container it names is, which for an identity provider is the
wrong failure. Here, what is down answers 502 and the rest keeps serving.

Two consequences worth knowing: `antarest_http_port` is the port its nginx
literally listens on, and `$remote_addr` is the real client address with no
DNAT in between, which is what the fail2ban jail on the login form reads.

The TLS variables keep the `antarest_` prefix they were deployed under when the
Antares-Web nginx still terminated TLS: renaming them would have turned TLS
off, silently, on every inventory that sets them. They live in
`defaults/main.yml` and are documented in
[The front door and TLS](../../docs/edge-and-tls.md).
