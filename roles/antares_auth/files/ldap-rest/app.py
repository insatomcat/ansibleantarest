"""LDAP connector for the `security.external_auth` hook of Antares-Web.

Same contract as the Keycloak connector next door, and the same reasons behind
the shape of the answer - see the docstring of kc-rest/app.py.

The exchange with the directory is two binds: one as the user, which is what
authenticates them, and one as the read-only account, for the attributes and
the groups. The user bind is not reused for the second half on purpose: a
directory where users cannot read the group tree would then answer that nobody
is in any group.
"""

import logging
import os

import ldap3
from flask import Flask, jsonify, request

LDAP_HOST = os.environ.get("LDAP_HOST", "openldap")
LDAP_PORT = int(os.environ.get("LDAP_PORT", "389"))
LDAP_USE_SSL = os.environ.get("LDAP_USE_SSL", "false").lower() in ("1", "true", "yes")
LDAP_BASE_DN = os.environ.get("LDAP_BASE_DN", "dc=antares,dc=local")
LDAP_USER_OU = os.environ.get("LDAP_USER_OU", "ou=users")
LDAP_GROUP_OU = os.environ.get("LDAP_GROUP_OU", "ou=groups")
LDAP_USER_ATTR = os.environ.get("LDAP_USER_ATTR", "uid")
LDAP_BIND_DN = os.environ.get("LDAP_BIND_DN", f"cn=admin,{LDAP_BASE_DN}")
LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD", "")

# Which attribute of a group becomes the id of the Antares group: `cn`
# (analysts) or `gidNumber` (5001). `cn` by default, because that id is what an
# operator writes in antarest_external_auth_group_mapping.
LDAP_GROUP_KEY = os.environ.get("LDAP_GROUP_KEY", "cn")

# Seconds. Short on purpose: this call sits in the middle of a login.
LDAP_TIMEOUT = float(os.environ.get("LDAP_TIMEOUT", "10"))

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)

app = Flask(__name__)


def _server():
    return ldap3.Server(
        LDAP_HOST, port=LDAP_PORT, use_ssl=LDAP_USE_SSL, connect_timeout=LDAP_TIMEOUT
    )


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.post("/auth")
def auth():
    payload = request.get_json(silent=True) or {}
    username = payload.get("user")
    password = payload.get("password")

    if not username or not password:
        return jsonify(error="user and password required"), 400

    user_dn = f"{LDAP_USER_ATTR}={username},{LDAP_USER_OU},{LDAP_BASE_DN}"
    server = _server()

    try:
        # An empty password is a *successful* anonymous bind in LDAP, which
        # would let anyone in as anybody. It is rejected above, and this is the
        # second half of that: ldap3 raises rather than binding anonymously.
        user_conn = ldap3.Connection(
            server, user=user_dn, password=password, raise_exceptions=False
        )
        if not user_conn.bind():
            app.logger.info("rejected %s (%s)", username, user_dn)
            return jsonify(error="invalid credentials"), 401
        user_conn.unbind()

        reader = ldap3.Connection(
            server, user=LDAP_BIND_DN, password=LDAP_BIND_PASSWORD, auto_bind=True
        )
    except ldap3.core.exceptions.LDAPException as exc:
        app.logger.error("the directory is not answering: %s", exc)
        return jsonify(error="directory unavailable"), 502

    try:
        reader.search(
            search_base=f"{LDAP_USER_OU},{LDAP_BASE_DN}",
            search_filter=f"({LDAP_USER_ATTR}={username})",
            attributes=["givenName", "sn"],
        )
        first_name, last_name = None, None
        if reader.entries:
            entry = reader.entries[0]
            first_name = entry.givenName.value if "givenName" in entry else None
            last_name = entry.sn.value if "sn" in entry else None

        reader.search(
            search_base=f"{LDAP_GROUP_OU},{LDAP_BASE_DN}",
            search_filter=f"(memberUid={username})",
            attributes=["cn", LDAP_GROUP_KEY],
        )
        groups = {}
        for entry in reader.entries:
            key = entry[LDAP_GROUP_KEY].value if LDAP_GROUP_KEY in entry else None
            name = entry.cn.value if "cn" in entry else None
            if key is not None and name is not None:
                groups[str(key)] = name
    finally:
        reader.unbind()

    result = {
        "user": username,
        # Never absent and never null: Antares-Web reads both keys without a
        # default and concatenates them into the name it displays.
        "firstName": first_name or username,
        "lastName": last_name or "",
        "groups": groups,
    }
    app.logger.info("%s authenticated, groups %s", username, list(groups))
    return jsonify(result), 200


if __name__ == "__main__":
    # Development only. The image runs gunicorn, see the Dockerfile.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8870)))
