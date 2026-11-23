"""Align the roles Antares-Web holds with the groups Keycloak holds.

The login hook of Antares-Web (see app.py) only ever *adds*: at each login it
gives every group it has not seen yet for that user the one role of
`default_group_role`, and it never removes a membership, never changes a role
and never notices a disabled account. This job closes those gaps. Run on a
timer, it reads every account of the realm and corrects Antares-Web through its
administration API:

  enabled account   each managed group gets the role the table gives it, and
                    the managed groups the user is no longer in are withdrawn;
  disabled or gone  API tokens revoked, roles withdrawn, studies handed over to
                    the account the job logs in with, then the account deleted,
                    which is the only thing that ends its open session.

The hand-over comes first because Antares-Web cannot delete an account that
still owns a study: `study.owner_id` references the identity with no ON
DELETE, and the delete fails on the constraint. It refuses to change the owner
of an archived study, so a leaver who owns one keeps an account with no role
and no token until the study is restored; the job says which study blocks and
tries again at the next run.

What the job manages:

  - accounts that came from the hook only (table users_ldap). Local accounts,
    the administrator among them, are never touched;
  - the Antares-Web groups the configuration maps a Keycloak group to, and
    with add_ext_groups every group of the realm, whether or not anybody is
    still in it. A role granted by hand in any other group survives every
    run.

The groups come from the list of the realm, not from the memberships alone:
a group emptied of its last member is still managed, so that member's role
in it is withdrawn. A group deleted from Keycloak is gone from that list as
well and the job cannot tell it ever managed it, so a group is emptied, and
one run let go, before it is deleted.

The link between an Antares-Web account and its Keycloak username is the
`external_id` column of users_ldap, which the administration API does not
return: it is read from the database, read only. Everything the job changes
goes through the API, so through the application's own rules and logs.

Nothing is changed unless Keycloak was read in full: a Keycloak that does not
answer must never look like a realm where everybody left.

Configuration, all from the environment, shared with app.py where it overlaps:

  KEYCLOAK_URL, KEYCLOAK_REALM, KEYCLOAK_CLIENT_ID, KEYCLOAK_CLIENT_SECRET,
  KEYCLOAK_GROUP_KEY     as for the connector
  ANTAREST_URL           the backend, http://antarest:5000
  ANTAREST_ADMIN_USER    the local account the job acts as, `admin`
  ANTAREST_ADMIN_PASSWORD
  PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
                         the Antares-Web database, read by libpq itself
  SYNC_GROUP_MAPPING     JSON, security.external_auth.group_mapping
  SYNC_ADD_EXT_GROUPS    true/false, security.external_auth.add_ext_groups
  SYNC_DEFAULT_ROLE      security.external_auth.default_group_role
  SYNC_ROLES             JSON, Antares-Web group id -> role, for the groups
                         whose role is not the default one
  SYNC_MAX_CLOSURES      refuse to close more accounts than this in one run
  SYNC_DRY_RUN           true: log every change, make none

Exit status 0 when every account is aligned, 1 when something could not be
done (the run went on with the other accounts), 2 when the run was refused
before any change.
"""

import json
import logging
import os
import sys

import psycopg
import requests

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080/auth").rstrip("/")
REALM = os.environ.get("KEYCLOAK_REALM", "antares")
CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "antares-auth")
CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET", "")
GROUP_KEY = os.environ.get("KEYCLOAK_GROUP_KEY", "name")

ANTAREST_URL = os.environ.get("ANTAREST_URL", "http://antarest:5000").rstrip("/")
ADMIN_USER = os.environ.get("ANTAREST_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ANTAREST_ADMIN_PASSWORD", "")

TIMEOUT = float(os.environ.get("SYNC_TIMEOUT", "30"))
PAGE = 100

ROLE_VALUES = {"reader": 10, "runner": 20, "writer": 30, "admin": 40}
ROLE_NAMES = {value: name for name, value in ROLE_VALUES.items()}

log = logging.getLogger("kc-sync")


class Refused(Exception):
    """The run stops before changing anything."""


def _flag(name, default="false"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _role(value):
    """A role as Antares-Web numbers it, from a name or a number."""
    text = str(value).strip().lower()
    if text in ROLE_VALUES:
        return ROLE_VALUES[text]
    if text.isdigit() and int(text) in ROLE_NAMES:
        return int(text)
    raise Refused(f"unknown role {value!r}, expected one of {', '.join(ROLE_VALUES)}")


class Table:
    """Which Antares-Web group, with which role, each Keycloak group gives.

    Mirrors what the login hook does with the same configuration, so that the
    job never fights it: the external id of a group is looked up in
    group_mapping, kept as it is when add_ext_groups is on, dropped otherwise.
    """

    def __init__(self):
        self.mapping = json.loads(os.environ.get("SYNC_GROUP_MAPPING") or "{}")
        self.add_ext = _flag("SYNC_ADD_EXT_GROUPS")
        self.default = _role(os.environ.get("SYNC_DEFAULT_ROLE", "reader"))
        self.roles = {
            group: _role(role)
            for group, role in json.loads(os.environ.get("SYNC_ROLES") or "{}").items()
        }
        unmapped = set(self.roles) - set(self.mapping.values())
        if unmapped and not self.add_ext:
            raise Refused(
                f"SYNC_ROLES names {sorted(unmapped)}, which no Keycloak group maps to: "
                "add them to the group mapping or remove them"
            )

    def target(self, external_group):
        if external_group in self.mapping:
            return self.mapping[external_group]
        return external_group if self.add_ext else None

    def wanted(self, external_groups):
        """Antares-Web group id -> role, from the external ids of a user's groups."""
        result = {}
        for external in external_groups:
            group = self.target(external)
            if group is None:
                continue
            role = self.roles.get(group, self.default)
            result[group] = max(role, result.get(group, 0))
        return result

    def managed(self, every_external_group):
        groups = set(self.mapping.values()) | set(self.roles)
        if self.add_ext:
            groups |= set(every_external_group)
        return groups


# ---------------------------------------------------------------------------
#  Keycloak, read only
# ---------------------------------------------------------------------------


def _read_groups(headers):
    """Every group of the realm, subgroups included: {external id: name}."""
    found = {}

    def walk(url):
        first = 0
        while True:
            page = requests.get(
                url,
                headers=headers,
                params={"first": first, "max": PAGE, "briefRepresentation": "true"},
                timeout=TIMEOUT,
            )
            page.raise_for_status()
            batch = page.json()
            for group in batch:
                if group.get(GROUP_KEY) and group.get("name"):
                    found[group[GROUP_KEY]] = group["name"]
                # The top level list says how many children a group has and
                # leaves them out; they are listed group by group.
                if group.get("subGroupCount"):
                    walk(f"{KEYCLOAK_URL}/admin/realms/{REALM}/groups/{group['id']}/children")
            if len(batch) < PAGE:
                break
            first += PAGE

    walk(f"{KEYCLOAK_URL}/admin/realms/{REALM}/groups")
    return found


def read_keycloak():
    """The accounts and the groups of the realm.

    accounts: username (lower case) -> {"enabled": bool, "groups": {external id: name}}
    groups:   {external id: name}, every group of the realm, empty ones included
    """
    try:
        token = requests.post(
            f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
            timeout=TIMEOUT,
        )
        token.raise_for_status()
        headers = {"Authorization": f"Bearer {token.json()['access_token']}"}

        users = []
        first = 0
        while True:
            page = requests.get(
                f"{KEYCLOAK_URL}/admin/realms/{REALM}/users",
                headers=headers,
                params={"first": first, "max": PAGE},
                timeout=TIMEOUT,
            )
            page.raise_for_status()
            batch = page.json()
            users.extend(batch)
            if len(batch) < PAGE:
                break
            first += PAGE

        accounts = {}
        for user in users:
            # The service account of the client is a user of the realm too.
            if user.get("serviceAccountClientId"):
                continue
            groups = requests.get(
                f"{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user['id']}/groups",
                headers=headers,
                params={"max": 1000},
                timeout=TIMEOUT,
            )
            groups.raise_for_status()
            accounts[user["username"].lower()] = {
                "enabled": bool(user.get("enabled")),
                "groups": {
                    group[GROUP_KEY]: group["name"]
                    for group in groups.json()
                    if group.get(GROUP_KEY) and group.get("name")
                },
            }

        realm_groups = _read_groups(headers)
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise Refused(f"Keycloak could not be read in full: {exc}") from exc

    if not accounts:
        raise Refused("Keycloak returned no account at all")
    return accounts, realm_groups


# ---------------------------------------------------------------------------
#  Antares-Web
# ---------------------------------------------------------------------------


def read_external_accounts():
    """Antares-Web id -> external id, for the accounts the login hook created."""
    try:
        with psycopg.connect(connect_timeout=int(TIMEOUT)) as conn:
            conn.read_only = True
            rows = conn.execute(
                "SELECT id, external_id FROM users_ldap WHERE external_id IS NOT NULL"
            ).fetchall()
    except psycopg.Error as exc:
        raise Refused(f"the Antares-Web database could not be read: {exc}") from exc
    return {row[0]: row[1] for row in rows}


class AntaresWeb:
    def __init__(self, dry_run):
        self.dry_run = dry_run
        self.changes = 0
        self.session = requests.Session()
        try:
            response = self.session.post(
                f"{ANTAREST_URL}/v1/login",
                json={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise Refused(f"cannot log in to Antares-Web as {ADMIN_USER}: {exc}") from exc
        credentials = response.json()
        self.admin_id = credentials["user"]
        self.session.headers["Authorization"] = f"Bearer {credentials['access_token']}"

    def get(self, path, **params):
        response = self.session.get(f"{ANTAREST_URL}/v1{path}", params=params, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()

    def change(self, method, path, what, **kwargs):
        """One change, logged whether it is made or not."""
        self.changes += 1
        if self.dry_run:
            log.info("dry run, would %s", what)
            return
        response = self.session.request(method, f"{ANTAREST_URL}/v1{path}", timeout=TIMEOUT, **kwargs)
        response.raise_for_status()
        log.info("%s", what)

    def roles_by_user(self):
        return {
            user["id"]: {role["group_id"]: int(role["type"]) for role in user.get("roles", [])}
            for user in self.get("/users", details="true")
        }

    def group_ids(self):
        return {group["id"] for group in self.get("/groups")}


# ---------------------------------------------------------------------------
#  The run
# ---------------------------------------------------------------------------


def align(aw, user_id, label, current, wanted, managed, groups, names):
    """Bring the roles of one enabled account in the managed groups to `wanted`."""
    for group in sorted(managed):
        have, want = current.get(group), wanted.get(group)
        if have == want:
            continue
        if have is not None:
            aw.change(
                "DELETE",
                f"/roles/{group}/{user_id}",
                f"{label}: withdraw {ROLE_NAMES.get(have, have)} in {group}",
            )
        if want is None:
            continue
        if group not in groups:
            aw.change(
                "POST",
                "/groups",
                f"create group {group}",
                json={"id": group, "name": names.get(group, group)},
            )
            groups.add(group)
        aw.change(
            "POST",
            "/roles",
            f"{label}: grant {ROLE_NAMES[want]} in {group}",
            json={"type": want, "group_id": group, "identity_id": user_id},
        )


def close(aw, user_id, label, roles):
    """Close the account of a leaver. True when it is gone."""
    for bot in aw.get("/bots", owner=user_id):
        aw.change("DELETE", f"/bots/{bot['id']}", f"{label}: revoke API token {bot['name']!r}")
    if roles:
        aw.change("DELETE", f"/users/roles/{user_id}", f"{label}: withdraw every role")

    blocked = []
    for uuid, study in aw.get("/studies", users=str(user_id), pageSize=0).items():
        if study.get("archived"):
            blocked.append(f"{study.get('name')} ({uuid})")
            continue
        aw.change(
            "PUT",
            f"/studies/{uuid}/owner/{aw.admin_id}",
            f"{label}: hand study {study.get('name')!r} ({uuid}) over to {ADMIN_USER}",
        )
    if blocked:
        log.error(
            "%s: not deleted, archived studies cannot change owner: %s. "
            "Restore them from the archive, the next run completes the closure",
            label,
            ", ".join(blocked),
        )
        return False

    aw.change("DELETE", f"/users/{user_id}", f"{label}: delete the account")
    return True


def run():
    dry_run = _flag("SYNC_DRY_RUN")
    max_closures = int(os.environ.get("SYNC_MAX_CLOSURES", "10"))
    table = Table()

    keycloak, realm_groups = read_keycloak()
    external = read_external_accounts()
    aw = AntaresWeb(dry_run)
    try:
        roles = aw.roles_by_user()
        groups = aw.group_ids()
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise Refused(f"Antares-Web users and groups could not be read: {exc}") from exc

    # The groups of the realm, empty ones included, so that the last member
    # taken out of a group still has their role there withdrawn.
    every_group = dict(realm_groups)
    for account in keycloak.values():
        every_group.update(account["groups"])
    managed = table.managed({table.target(g) for g in every_group} - {None})
    names = {
        table.target(external_id): name
        for external_id, name in every_group.items()
        if table.target(external_id)
    }

    leavers = {
        user_id: external_id
        for user_id, external_id in external.items()
        if not keycloak.get(external_id.lower(), {}).get("enabled")
    }
    if len(leavers) > max_closures:
        raise Refused(
            f"{len(leavers)} accounts would be closed, more than SYNC_MAX_CLOSURES={max_closures}. "
            "Check the realm, then raise the limit for one run if this is intended"
        )

    errors = closed = checked = changed = 0
    for user_id, external_id in sorted(external.items()):
        label = f"{external_id} (#{user_id})"
        current = roles.get(user_id, {})
        try:
            if user_id in leavers:
                if close(aw, user_id, label, current):
                    closed += 1
                else:
                    errors += 1
            else:
                wanted = table.wanted(keycloak[external_id.lower()]["groups"])
                before = aw.changes
                align(aw, user_id, label, current, wanted, managed, groups, names)
                checked += 1
                changed += aw.changes > before
        except requests.RequestException as exc:
            errors += 1
            log.error("%s: %s", label, exc)

    log.info(
        "%sdone: %d accounts checked, %d realigned, %d closed, %d errors, %d Keycloak accounts read",
        "dry run " if dry_run else "",
        checked,
        changed,
        closed,
        errors,
        len(keycloak),
    )
    return 1 if errors else 0


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(message)s",
    )
    try:
        return run()
    except Refused as exc:
        log.error("run refused, nothing changed: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
