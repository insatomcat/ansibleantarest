# Authentication

Antares-Web knows two kinds of account. Local ones live in its database, admin included, and are managed from its own interface. External ones come from `security.external_auth`: a URL the backend POSTs a username and a password to, expecting the first name, the last name and the groups of that user back. That is all the protocol is, and it is the only hook the application has. It speaks no OIDC, no SAML and no LDAP.

```yaml
antarest_external_auth_url: "http://antares-auth-kc:8870"
antarest_external_auth_default_group_role: 10      # 10 reader ... 40 admin
antarest_external_auth_add_ext_groups: true
```

A user who logs in that way is created in the database on the spot, with the role `antarest_external_auth_default_group_role` in each group the service returned. `antarest_external_auth_add_ext_groups` decides whether every group it returned is honoured or only those `antarest_external_auth_group_mapping` names, which is the way to expose two or three of them and ignore the rest. The mapping is read in both cases: it turns the id the connector sends into the id of the local group, and a group that is honoured is created when it does not exist yet - a group that already exists keeps its own name, the one the connector sends only names the new ones.

None of this is what [the password in front of the password](edge-and-tls.md#the-password-in-front-of-the-password) is. That one is a list of logins and hashes held by the front door, in front of the login form rather than in place of it: it decides who may reach the application at all, and says nothing about who anybody is. Everything below still happens afterwards, unchanged.

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

`keycloak_enabled` puts a Keycloak next to Antares-Web: one more container on the podman network, published on `127.0.0.1:8082`, served by [the front door](edge-and-tls.md) under `/auth/`, and sharing the PostgreSQL the stack already runs. Its console is one of the interfaces `antares_edge_basic_auth_admin_users` guards, and of everything a deployment publishes it is the one most worth a second password.

It gets a database of its own in that cluster (`keycloak`, with a role of the same name), created by the playbook before the container is ever started. A schema in the Antares-Web database would have worked; a database of its own means a migration on either side has no business meeting the other one's, and a dump of one is not a dump of both.

```yaml
keycloak_enabled: true
keycloak_realm: antares
keycloak_admin_password: "..."      # seeds the master realm admin, once
keycloak_db_password: "..."
keycloak_client_secret: "..."
```

The playbook imports a realm at the first start, and only then: Keycloak skips a realm that already exists, which is what keeps the users and groups created since. That realm holds one client, `antares-auth`, with a direct access grant (to check a password) and a service account carrying `view-users` (to read the groups of the user who just logged in). Nothing here holds a credential of the `master` realm. Users and groups are created afterwards, from the console at `https://<domain>/auth/admin/`.

From Keycloak 26.8.2 on, the admin API also checks the audience of the tokens it receives: a token has to carry the built-in `kc-admin-api` client scope, which the upgrade gives to `admin-cli` and to the console only. Without it the connector's service account is refused with a 401 when it reads the groups, after the password check has already succeeded, and every external login fails as if the password were wrong. The role puts the scope on `antares-auth` over the admin API on every run (`roles/keycloak/tasks/client_scope.yml`), since a realm imported by an older Keycloak is never imported again.

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


## The account pages and the realm settings

**The account pages.** Antares-Web has no page where a user sets or changes a password, and its login form cannot answer a required action: an account created with a temporary password, or with `UPDATE_PASSWORD` among its required actions, is refused there (`Bad username or password`) until the password is set. Keycloak's account pages are where that happens, at `https://<domain>/auth/realms/<realm>/account/`. With `keycloak_account_public` (on by default) the front door serves them, with the login pages around them and Keycloak's static files (`/auth/resources/`), behind the password tier of the application, so that the people who use it reach them with the credential they already have. Everything else under `/auth` stays in the administration tier: the console, the `master` realm, the other realms.

So a new account goes like this: an administrator creates it in the console with a temporary password, the user opens the account page, logs in with it, is made to choose a password that meets the policy, and logs in to Antares-Web with that one. Changing it later is the same page.

**The realm settings.** The realm file is imported at the first start only, so what has to hold on a realm that already exists is applied by `roles/keycloak/tasks/realm_settings.yml` over the admin API on every run, written only when it differs:

| Setting | Variable | Default |
|---|---|---|
| Password policy, in Keycloak's syntax | `keycloak_password_policy` | `length(12) and maxLength(128) and notUsername and notEmail and passwordHistory(3)`. Length over complexity and no periodic expiry, after NIST SP 800-63B |
| Temporary lockout after repeated failed logins | `keycloak_brute_force_enabled`, `keycloak_brute_force_failures`, `_wait`, `_max_wait`, `_reset` | On; after 10 failures, 60 s doubling up to 15 min, forgotten after 12 h. Never permanent, which would let anyone who knows a username lock its owner out |
| Event log: logins, failures, password changes, console changes | `keycloak_events_enabled`, `keycloak_events_retention` | On, 365 days |
| Mail relay and the "Forgot password?" link | `keycloak_smtp_*`, `keycloak_reset_password_allowed` | Off, on when `keycloak_smtp_host` is set |
| Fields of their account a user may change on the account page | `keycloak_profile_user_editable` | None of username, e-mail, first and last name: a user who changes the address takes the password reset of the account with it, one who changes the names appears under someone else's in Antares-Web. They still see them, and change their password |
| Theme of the realm: a link to Antares-Web at the end of a mailed link, a console without the tabs nobody uses | `keycloak_login_theme`, `keycloak_app_url`, `keycloak_app_link_label`, `keycloak_admin_hidden_tabs` | `antares`, `/`, `Open Antares Web`; hidden tabs Role mapping, Consents, Identity provider links, Sessions, Workflows. Empty theme name, Keycloak's own |
| Required actions the realm keeps | `keycloak_required_actions` | `UPDATE_PASSWORD` alone; every other one is turned off. Empty, left as the realm has them |
| How long a mailed link stays valid | `keycloak_action_token_lifespan` | 1800 s. Keycloak's own 300 s expires before many users have read the mail |
| Groups that must exist | `keycloak_realm_groups` | The Keycloak side of `antarest_external_auth_group_mapping`. Only adds; groups created from the console stay |
| Groups whose members administer the accounts of the realm | `keycloak_realm_admin_groups`, `keycloak_realm_admin_roles` | None. Each group listed is created if missing and given `manage-users`, `view-users`, `query-users` and `query-groups` of the `realm-management` client. Only adds |

**Administering the accounts without the master realm.** The people who create and close the accounts of a deployment are rarely the people who operate it. A group in `keycloak_realm_admin_groups` gives its members the console of the realm alone, at `https://<domain>/auth/admin/<realm>/console/`, logging in with their own account of that realm: they create, edit, disable and delete accounts, place them in groups and send them the set-password mail, and they do not see the settings of the realm, its clients or the `master` realm. The console is still under `/auth/admin/`, so the front door asks them the administration credential first; `antares_edge_redirects` can give that address a short one (see [the front door](edge-and-tls.md#the-front-door)). Being in such a group is a Keycloak right only; what the same group gives in Antares-Web is the mapping below.

**Mail and the password reset link.** With `keycloak_smtp_host` set, the role gives the realm a mail relay (`keycloak_smtp_port`, `keycloak_smtp_from`, `keycloak_smtp_from_display_name`, `keycloak_smtp_user`, `keycloak_smtp_password`; authenticated, STARTTLS) and turns on the "Forgot password?" link of the login page (`keycloak_reset_password_allowed`, which follows the relay). A user who has forgotten their password asks for the link on the account page, gets a mail, follows it to the same pages behind the application tier, and chooses a new password under the policy. A user without an e-mail address in Keycloak gets nothing, and the page says the same either way, so that it cannot be used to find out which usernames exist. The console's "send email" actions (set a password, verify an e-mail address) use the same relay. Keycloak answers the relay password masked, so the role compares the other settings and sends the password with them when one differs: changing the password alone takes `-e keycloak_smtp_host=` for one run, then the normal one, or the console.

**The link back to Antares-Web.** Antares-Web does not speak OIDC, so Keycloak has no application to send a user back to. A member who follows a link mailed from the console ("Credential reset", "Send email") ends on "Your account has been updated" with no link at all, because the console passes no `redirect_uri`; elsewhere Keycloak's "Back to Application" leads to the base URL of a Keycloak client, which is a Keycloak login page. The role installs a login theme of one page (`roles/keycloak/files/theme/info.ftl`, on top of `keycloak.v2`) that shows "Open Antares Web" in place of those links, pointing at `keycloak_app_url`: the root of the name Keycloak is served under, which is where Antares-Web is. "Click here to proceed", which finishes an action still under way, is kept. The theme is mounted read-only into the container, so a change restarts Keycloak, and the realm is pointed at it by the realm settings above. Upgrading Keycloak: compare the file with `theme/base/login/info.ftl` of the new version.

**A console with what the account administrators need.** The administrators of the realm (`keycloak_realm_admin_groups`) create accounts, put them in groups and send the set-password mail; Keycloak's console offers them much more, and some of it does harm here. Two settings take it away:

- `keycloak_required_actions` turns off every required action but `UPDATE_PASSWORD`. Those are the actions Keycloak can ask of a user, and the list the console offers under Credential Reset and Required user actions. Antares-Web logs people in through the connector with a direct grant and a password alone, so a member who sets up a one-time code (Configure OTP) is refused by Antares-Web from then on; the passkeys, the profile and e-mail checks and the identity provider links have nothing to act on. Turned off, they also leave the account page of the members.
- the admin part of the theme hides the tabs of an account listed in `keycloak_admin_hidden_tabs`, by the `data-testid` Keycloak gives them, with a stylesheet. It is the theme of the realm's console only: the console of the `master` realm, which the operator uses, keeps every tab. What an administrator may do still comes from their roles. Those names are the ones Keycloak gives its tabs for its own tests, and a new version may rename one, which brings the tab back into view: `verify.yml` looks for each of them in the console of the Keycloak installed, and fails naming the one it no longer finds.

The lockout is per account and counts failures from every address, which the per-address banning in front of the login form (see [Hardening](hardening.md)) cannot see. Keycloak sees the connector's address rather than the user's, since every login goes through it. To lift a lockout before it expires: Users > the user > the banner, or `kcadm.sh delete attack-detection/brute-force/users/<id> -r <realm>`.

## Keeping roles aligned with Keycloak

The login hook only ever adds. At each login it gives every group it has not seen yet for that user the one role `antarest_external_auth_default_group_role`, and that is all it does: a user meant to be writer arrives as reader, a group the user left in Keycloak stays in Antares-Web, and an account disabled in Keycloak cannot log in again but keeps its open session (the refresh token lives 30 days) and its API tokens.

With the Keycloak connector, `antares_auth_sync_enabled` (on by default) deploys a job that corrects this on a timer, `antares_auth_sync_schedule`, hourly by default. It runs the connector's image as a oneshot unit, `antares-auth-sync.service`, started by `antares-auth-sync.timer`. Each run reads every account of the realm with the connector's service account, then for each account the login hook created:

- **enabled in Keycloak:** in each managed group, the role the table gives is granted, a wrong role is replaced, and the groups the user left are withdrawn;
- **disabled or deleted in Keycloak:** its API tokens are revoked, its roles withdrawn, its studies handed over to the `admin` account, then the account is deleted, which is what ends its session.

The table is two variables. `antarest_external_auth_group_mapping`, which the login hook already reads, says which Keycloak group gives which Antares-Web group. `antares_auth_sync_roles` says with which role, for the groups whose role is not the default one:

```yaml
antarest_external_auth_group_mapping:
  secretariat-admins: admin
  modelling-team: modelling
  tc-ess: tc-ess
antares_auth_sync_roles:
  admin: admin          # any role in the group `admin` makes an application administrator
  modelling: writer
```

A managed group is one the mapping points to, or with `antarest_external_auth_add_ext_groups` any group of the realm. The job reads the list of the realm's groups for that, so a group emptied of its last member stays managed and that member's role in it is withdrawn. A group deleted from Keycloak leaves the list too, and the job can no longer tell that it managed it: empty a group and let one run go before deleting it. A role granted by hand in any other group is never touched, nor are local accounts, the administrator among them.

The studies change owner before the account goes because Antares-Web cannot do otherwise: `study.owner_id` references the identity with no `ON DELETE`, so deleting an account that owns a study fails on the constraint. The new owner is `admin`; the studies keep their groups and their permissions. Antares-Web refuses to change the owner of an archived study, so a leaver who owns one keeps an account with no role and no token: the run logs which study blocks, ends in error, and completes the closure at the first run after the study is restored.

Safeguards:

- nothing is changed unless Keycloak, the database and the Antares-Web users were all read in full, and a realm that returns no account at all counts as unreadable;
- a run that would close more than `antares_auth_sync_max_closures` accounts (10) is refused;
- `antares_auth_sync_dry_run: true` logs every change and makes none: deploy with it, `systemctl start antares-auth-sync`, read `journalctl -u antares-auth-sync`;
- the link between an Antares-Web account and its Keycloak username, `users_ldap.external_id`, is not in the administration API, so the job reads it from the database with an account of its own, `antares_auth_sync_db_user`, which can `SELECT` that table and nothing else. Its password is `antares_auth_sync_db_password`, which the hardening role refuses to leave at the shipped value. Every change goes through the API.

The unit ends `failed` when a run was refused (exit 2) or when some account could not be handled (exit 1), so a failed-unit check is enough to be told. Its configuration, secrets included, is in `/etc/antares-web/antares-auth-sync.env`, root only.

A new user's first login gives the default role in every group: a writer is a reader until the next run. Keep `antarest_external_auth_default_group_role` at reader so that this window errs on the restrictive side.
