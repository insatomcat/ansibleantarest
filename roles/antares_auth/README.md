# antares_auth

The bridge between `security.external_auth`, the one authentication hook
Antares-Web has, and a real identity provider. The hook is a URL the backend
POSTs a username and a password to, expecting a name and a list of groups back:
that is all the protocol is, and it speaks no OIDC, no SAML and no LDAP.

The connectors that answer it are in `files/`, and are the sources this role
builds an image from:

| `antares_auth_provider` | Connector | How it checks a password |
|---|---|---|
| `none` | none | Only the local accounts of Antares-Web exist |
| `keycloak` | `files/kc-rest` | A direct access grant, then the client's service account reads the names and groups from the admin API |
| `ldap` | `files/ldap-rest` | A bind as the user, then a read-only account reads `givenName`, `sn` and the groups carrying their `memberUid` |

| Task file | What it does |
|---|---|
| `stale.yml` | Takes down the connectors this deployment does not use. First, so that switching provider never leaves two side by side |
| `build_images.yml` | Builds the connector image from `files/<connector>` |
| `load_image.yml` | `archive` mode: loads the image `build.yml` produced |
| `install.yml` | The image, the configuration and the unit |
| `service.yml` | The `antares-auth-*` quadlet unit |

**The container publishes no port.** The backend reaches it by container name
on the podman network, which is what `antarest_external_auth_url` points at, so
what it answers never leaves the machine.

The key of each group it returns becomes the *id* of the Antares group, which
is what `antarest_external_auth_group_mapping` is written against. Both
connectors default to the readable one (the Keycloak group name, the LDAP `cn`)
rather than a UUID or a gid.

The role asserts its provider is one it knows, and the LDAP connector refuses
to deploy without the settings it needs, by name. Variables in
`defaults/main.yml`, documented in
[Authentication](../../docs/authentication.md).
