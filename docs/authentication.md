# Authentication

Antares-Web knows two kinds of account. Local ones live in its database, admin included, and are managed from its own interface. External ones come from `security.external_auth`: a URL the backend POSTs a username and a password to, expecting the first name, the last name and the groups of that user back. That is all the protocol is, and it is the only hook the application has. It speaks no OIDC, no SAML and no LDAP.

```yaml
antarest_external_auth_url: "http://antares-auth-kc:8870"
antarest_external_auth_default_group_role: 10      # 10 reader ... 40 admin
antarest_external_auth_add_ext_groups: true
```

A user who logs in that way is created in the database on the spot, with the role `antarest_external_auth_default_group_role` in each group the service returned. `antarest_external_auth_add_ext_groups` decides whether groups that do not exist yet are created; with it off, only the groups listed in `antarest_external_auth_group_mapping` are honoured, which is the way to expose two or three of them and ignore the rest.

## The connectors

The bridge between that hook and a real identity provider is a small web service, and the `antares_auth` role holds two of them, in `roles/antares_auth/files/`. `antares_auth_provider` picks one, which is also what points `antarest_external_auth_url` at it:

| Provider | What it does |
|---|---|
| `none` | No connector. Only the local accounts of Antares-Web exist. |
| `keycloak` | `kc-rest`: a direct access grant against Keycloak checks the password, then the client's own service account reads the names and the groups from the admin API. Talks to `keycloak_enabled` by default, to any other Keycloak through `antares_auth_keycloak_url`. |
| `ldap` | `ldap-rest`: a bind as the user checks the password, then a read-only account reads `givenName`, `sn` and the groups carrying their `memberUid`. Everything it needs to find them is in `roles/antares_auth/defaults/main.yml`, and the role refuses to deploy without it. |

Both are Flask applications of about a hundred lines, run under gunicorn in an image the deployment builds from those sources - on the target, or once on the builder like everything else, which is what `antares_auth_provider` has to be set for when `build.yml` runs. Neither publishes a port: the backend reaches them by container name on the podman network, and what they answer is who somebody is.

The key of each entry in the `groups` they return becomes the *id* of the Antares group, which is what `antarest_external_auth_group_mapping` is written against. Both default to the readable one - the Keycloak group name, the LDAP `cn` - rather than a UUID or a gid; `antares_auth_keycloak_group_key` and `antares_auth_ldap_group_key` say otherwise.

Changing provider takes the previous connector down. There is nothing to clean up afterwards: the users it created stay in the Antares-Web database, where they are `UserLdap` rows keyed by their external id.

## Keycloak

`keycloak_enabled` puts a Keycloak next to Antares-Web: one more container on the podman network, published on `127.0.0.1:8082`, served by [the front door](edge-and-tls.md) under `/auth/`, and sharing the PostgreSQL the stack already runs.

It gets a database of its own in that cluster (`keycloak`, with a role of the same name), created by the playbook before the container is ever started. A schema in the Antares-Web database would have worked; a database of its own means a migration on either side has no business meeting the other one's, and a dump of one is not a dump of both.

```yaml
keycloak_enabled: true
keycloak_realm: antares
keycloak_admin_password: "..."      # seeds the master realm admin, once
keycloak_db_password: "..."
keycloak_client_secret: "..."
```

The playbook imports a realm at the first start, and only then: Keycloak skips a realm that already exists, which is what keeps the users and groups created since. That realm holds one client, `antares-auth`, with a direct access grant (to check a password) and a service account carrying `view-users` (to read the groups of the user who just logged in). Nothing here holds a credential of the `master` realm. Users and groups are created afterwards, from the console at `https://<domain>/auth/admin/`.

That realm is also imported with `email`, `firstName` and `lastName` optional, which the profile Keycloak ships is not. Its own makes the three required for the `user` role and enables the `VERIFY_PROFILE` action, so an account created from the console with a username and a password alone is incomplete in its eyes: the direct access grant the connector logs people in with answers `Account is not fully set up`, and that reaches the operator as a refused login, for a user the console shows as enabled, with a valid password and nothing in its required actions. The action is derived from the profile and never written on the account, which is what makes it invisible there. The fields still exist and are still validated when filled; requiring them again is a change in Realm settings > User profile.

Filling the names is worth it anyway. Antares-Web displays `firstName lastName` as the name of the account, and the connector falls back to the username when the first name is missing, so a user created without them shows up under their login.

A realm created before this change keeps Keycloak's profile, and re-running the playbook does not fix it, since the import is skipped: either fill the three fields on the accounts that already exist, drop the `required` keys in Realm settings > User profile, or replay the import below, which replaces the realm wholesale.

To replay a change to `roles/keycloak/templates/realm.json.j2` on a machine whose realm holds nothing worth keeping:

```bash
podman exec keycloak /opt/keycloak/bin/kc.sh import \
    --file /opt/keycloak/data/import/antares-realm.json --override true
```

That overwrites the realm, users and groups included.

`keycloak_admin_password` has the same shape as `antarest_admin_password`: it seeds the first administrator when the database is empty and is ignored ever after. Changing it later is done from the console. The other two secrets are read at every start, and `keycloak_db_password` is reconciled by the playbook, which checks the role can still log in with it and sets it when it cannot.

**The temporary administrator.** The account Keycloak creates from that password is a *temporary* administrator, and its console says so on every page: *You are logged in as a temporary admin user. To harden security, create a permanent admin account and delete the temporary one.* The flag behind the message is an attribute on the user, `is_temporary_admin`, and the admin API refuses to write it: a request that drops it answers 204 and changes nothing. Only what the message asks for works, another administrator and that one deleted.

`keycloak_admin_permanent` does it, at the end of the run that first starts Keycloak, over the admin API on the loopback port:

```yaml
keycloak_admin_permanent: true              # roles/keycloak/defaults/main.yml
keycloak_admin_rotate_user: "{{ keycloak_admin_user }}-rotate"
```

A scratch administrator is created (the configured name is held by the temporary account until it is deleted, and something has to be logged in to delete it), the temporary account goes, `keycloak_admin_user` is created again as a normal user with `keycloak_admin_password`, that login is checked, and the scratch account is deleted. Nothing outside the `master` realm is read or written, and the operator logs in with what the inventory says, as before, without the message.

Re-running costs three GETs: an administrator carrying no attribute is left alone. So is a master realm `keycloak_admin_password` no longer opens, which is what a password changed from the console looks like: the playbook says so and leaves it be. The scratch account carries the same password on purpose, so a run interrupted in the middle leaves an administrator whose credentials are in the inventory rather than a locked-out realm, and the next run picks the work up where it stopped. Set `keycloak_admin_permanent: false` for a `master` realm managed by hand.

Without TLS the Keycloak console is reachable only from a private address: its realms are imported with `sslRequired: none`, but the `master` realm the console lives in keeps the Keycloak default and refuses a plain-http login from anywhere else. Turn TLS on, or tunnel: `ssh -L 8082:127.0.0.1:8082 <machine>`, then `http://127.0.0.1:8082/auth/admin/`.

Turning `keycloak_enabled` back off stops and removes the container. It leaves the database alone: turning it on again finds its realms, its users and its groups where they were.

The CI deploys it on every pull request, in the three shapes and on every distribution it deploys at all: `inventory/ci-*.yml` all carry `keycloak_enabled: true` and `antares_auth_provider: keycloak`, the builder included, since that is what puts the Keycloak image and the connector image in the artefacts. What that covers is the deployment - the database created before the first start, the realm import, the temporary administrator replaced, the two containers up, the route through the front door and the discovery document answering under it - rather than a login, which needs a user somebody created.

