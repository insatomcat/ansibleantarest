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

## The password in front of the password

Optional and off by default: the front door can ask for a login and a password of its own before it proxies anything. It is HTTP basic authentication, in front of the application's own login form rather than in place of it - a first door, whose key is not the key to anything else.

```yaml
antares_edge_basic_auth_users:            # the web application
  - name: alice
    hash: "$6$rXk...$5vN..."
  - name: bob
    hash: "$apr1$9kd...$Hs..."

antares_edge_basic_auth_admin_users:      # the consoles next to it
  - name: ops
    hash: "$6$dQ2...$Zt..."
```

Two lists, because the people who use a deployment are not the people who operate it. The first guards the web application; the second guards the administration interfaces the same front door serves - the Keycloak console under `/auth/`, Grafana under `/grafana/`, Prometheus when it is published. An account in one is not an account in the other, and both are separate again from the accounts of Antares-Web itself and from those of Keycloak.

There is no `_enabled` flag: a list with one account in it is a tier that is on, an empty one is a tier that is off. Emptying a list removes the password file with it. Extra routes can join either tier with `auth: app` or `auth: admin`, and a route that names neither is served to whoever reaches the door.

### Why bother, in front of a login form that already exists

- **The application stops being exposed.** Everything an attacker could aim at - the login form, the API, the study paths, the version of AntaREST in a page footer, whatever CVE the next release fixes - is behind a door that answers `401` and nothing else. A vulnerability in the application is only reachable by someone who already holds one of these accounts, which is most of what a web application firewall in front of it would have bought, at none of the cost. Scanners and crawlers see one status code.
- **With TLS on, there is nothing left to learn from the outside.** Someone listening on the wire sees the domain in the TLS handshake and the size of a few responses; the paths, the study names in the API URLs and the payloads all stay inside the session. Someone probing from the outside sees `401` on every path they try. Between the two, an attacker has no URL to aim at, and not even a way to confirm which application is behind the name.
- **The brute-force surface moves outward.** A password sprayer against the Antares-Web login form now has to get through this first, and the fail2ban jail of the [hardening](hardening.md) role still counts the `401`s that reach `/api/v1/login`.
- **It is a door, not a directory.** That is the point and the limit: it says who may knock, not who anybody is. Nothing downstream sees these accounts, Antares-Web still authenticates its own users, and the audit trail is still theirs. A list of half a dozen entries shared by a team is the shape this fits; one entry per user of the deployment, kept in step with the accounts inside it, is not.

### The hashes

The lists hold a login and a *hash*. No password is ever written in the inventory, which is what makes these lists safe to keep in a repository next to everything else, and what makes them safe to hand to somebody who is going to hold a copy of the inventory.

```bash
openssl passwd -6                  # SHA-512, prompts twice
htpasswd -n alice                  # $apr1$, prompts twice, prints "alice:$apr1$..."
```

Either format works: nginx understands `$apr1$` itself and hands everything else to `crypt(3)` in the container, which reads `$5$` and `$6$`. `htpasswd -B` (bcrypt) depends on the C library of the image and is not worth the surprise. The deployment refuses a `hash` that does not look like one, so a password pasted where a hash belonged fails the play rather than the login.

Changing somebody's password is a new hash in the inventory and a run of `--tags edge`; taking somebody out is one entry removed and the same run. Nothing is stored on the machine but the two files, `/etc/antares-web/edge/htpasswd/{app,admin}`, which hold the hashes and are readable by the nginx worker that reads them at every request.

### What is never asked for a password

Two exceptions, both deliberate.

**The machine itself.** `antares_edge_basic_auth_trusted` is the list of addresses the front door never challenges, the loopback by default. It is not a hole to be closed: everything behind the front door is published on that same loopback, so a password asked there would protect nothing that is not already reachable without it, and it would break the health checks the deployment makes through its own front door to test the routing. Add a network to it - a VPN, an office range, the Ansible controller - and clients on it are served without being asked, which is also what gives `verify.yml` back the checks it makes from the outside (see [Operating a deployment](operations.md#checking-a-deployment)).

**The API of the web application, when the caller carries a token.** The browser application authenticates every API call with a bearer token, in the `Authorization` header - the very header basic authentication uses. A browser cannot send both, so a password asked under `/api/` would not make the deployment more private, it would make it unusable. Requests carrying a bearer token, and websocket handshakes, which a browser cannot put a header on at all, are therefore passed under `/api/` to the backend, which asks them for the token they claim to have.

That exception is worth being precise about, because it is the one place where the door is not absolute: anyone who sends an `Authorization: Bearer` header reaches the API's own unauthenticated surface - its health endpoint, its login endpoint - and is refused by the backend everywhere else. The interface itself, every static file, every other route and both consoles stay behind the password with no header that gets past them. If that trade is not the right one for a deployment, drop `token_path` from the Antares-Web route in `roles/antares_edge/vars/main.yml`: the door becomes absolute, and the web interface stops working in a browser.

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

