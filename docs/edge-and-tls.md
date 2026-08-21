# The front door and TLS

## The front door

One nginx holds the ports of the machine and proxies to everything the deployment publishes on the loopback. It is the `antares_edge` role, and it is a separate container from the one that serves Antares-Web on purpose.

```yaml
antarest_http_port: 80        # what the front door listens on
antarest_https_port: 443
antarest_nginx_bind: 127.0.0.1  # where Antares-Web is published for it
antarest_nginx_port: 8081
antares_edge_image: "docker.io/library/nginx:1.30"
```

The Antares-Web nginx cannot be that front door. It declares `Requires=antarest.service` and resolves `antarest` on the podman network when its configuration is parsed, so it is down for exactly as long as the backend is, by design (see [Containers: podman and quadlet](containers.md)). Anything else served from it would be down with it, which for an identity provider is the wrong failure. The front door only ever proxies to addresses, never to names, so nothing it forwards to has to exist for it to start: what is down answers 502 and the rest keeps serving.

That is also why it runs in the host network namespace rather than on the podman network. On the network it would proxy to container names, nginx would resolve them at parse time, and the dependency it exists to break would be back. Two consequences worth knowing: `antarest_http_port` is the port its nginx literally listens on, and `$remote_addr` is the real client address, with no DNAT in between, which is what the fail2ban jail on the login form reads.

Everything else on the machine is published on `127.0.0.1` alone, so a port opened by mistake in a security group exposes nothing. `verify.yml` checks that from the outside.

What the deployment installs is already routed: the web application at `/`,
Keycloak under `keycloak_relative_path` when it is enabled, and Grafana under
`monitoring_grafana_path` when the fleet is monitored (see
[Monitoring](monitoring.md)). To put something else behind the same
certificate:

```yaml
antares_edge_extra_routes:
  - path: /reports/
    upstream: 127.0.0.1:8090
    name: Reports
```

Longest prefix wins, whatever the order. `antares_edge_client_max_body_size` (1G, the value the Antares-Web nginx uses for study imports) and `antares_edge_proxy_read_timeout` (1200 s) apply to every route; the rest of the plumbing is in `roles/antares_edge/defaults/main.yml`.

## TLS

TLS is terminated by the front door, the one container that holds a port of the machine (see [The front door](#the-front-door)). Switching it on makes it listen on `antarest_https_port` as well and, by default, redirect http to it. Everything it proxies to is served over https without having to know about it.

```yaml
antarest_tls_enabled: true
antarest_tls_domain: "antares.example.org"
antarest_tls_provider: letsencrypt   # letsencrypt | selfsigned | manual
antarest_tls_email: "ops@example.org"
```

| Provider | What happens |
|---|---|
| `letsencrypt` | certbot obtains the certificate over http-01, answered by the front door itself (webroot method). Renewal needs no downtime and the `certbot.timer` shipped with the package handles it. |
| `selfsigned`  | A certificate generated on the machine, valid ten years. Encrypts the traffic and makes every browser complain. For an internal network, or to test the plumbing without burning ACME rate limits. |
| `manual`      | A certificate you put on the machine yourself, for instance one issued by a company CA. Point `antarest_tls_certificate` and `antarest_tls_certificate_key` at the full chain and the private key. |

Let's Encrypt needs `antarest_tls_domain` to resolve to this machine and port 80 to be reachable from the internet, since that is where the challenge is fetched (the http-01 challenge has no port to negotiate, hence the playbook refusing to try if `antarest_http_port` is not 80). The first run brings the front door up on plain http, obtains the certificate through it and reloads it with TLS on; nothing has to be run twice. Use `antarest_tls_staging: true` while debugging, then remove the certificate (or `certbot renew --force-renewal`) to get a real one, because the playbook only asks for a certificate when there is none.

The TLS settings keep the `antarest_` prefix they were deployed under when the Antares-Web nginx still terminated TLS. They describe the TLS of the deployment rather than of one container, and renaming them would have turned TLS off, silently, on every inventory that sets them. They live in `roles/antares_edge/defaults/main.yml`.

