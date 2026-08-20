# keycloak

Keycloak next to Antares-Web: one more container on the podman network,
published on the loopback, served by the front door under `/auth/`, sharing the
PostgreSQL the stack already runs.

It runs whatever `keycloak_enabled` says, and that is deliberate: turning it
back off takes the container down instead of leaving an orphan unit running
next to a deployment that no longer knows about it. It runs after
`antares_web`, which is what starts PostgreSQL.

| Task file | What it does |
|---|---|
| `database.yml` | Creates the `keycloak` database and role in the stack's PostgreSQL, before the container is ever started, and reconciles the password |
| `realm.yml` | Renders the realm and imports it at the first start, and only then |
| `install.yml` | Image, configuration, and the pieces above |
| `service.yml` | The `keycloak` quadlet unit |
| `admin.yml` | Replaces the *temporary* administrator Keycloak bootstraps with a permanent one |
| `remove.yml` | Stops and removes the container when the flag is off, leaving the database alone |

**A database of its own, not a schema.** A schema in the Antares-Web database
would have worked; a database of its own means a migration on either side has
no business meeting the other one's, and a dump of one is not a dump of both.

**The import happens once.** Keycloak skips a realm that already exists, which
is what keeps the users and groups created since. A change to
`templates/realm.json.j2` therefore reaches an existing machine only through a
deliberate `kc.sh import --override true`, which replaces the realm wholesale.

**The temporary administrator.** The account bootstrapped from
`keycloak_admin_password` carries an `is_temporary_admin` attribute the admin
API refuses to write, so the only way out is the one the console asks for:
another administrator, and that one deleted. `admin.yml` does exactly that,
over the loopback port, and touches nothing outside the `master` realm. A run
interrupted in the middle leaves an administrator whose credentials are in the
inventory, and the next run picks the work up where it stopped.

Variables in `defaults/main.yml`, documented in
[Authentication](../../docs/authentication.md).
