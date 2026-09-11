"""Keycloak connector for the `security.external_auth` hook of Antares-Web.

Antares-Web speaks no OIDC. What it has is one URL it POSTs a username and a
password to, expecting the names and the groups of that user back:

    POST /auth  {"user": "...", "password": "..."}
    200         {"user": "...", "firstName": "...", "lastName": "...",
                 "groups": {"<id>": "<name>", ...}}
    401         wrong credentials

See antarest/login/ldap.py upstream, which is what calls this. Two things it
does that shape the answer below: it reads `firstName` and `lastName` without a
default, so a missing key is a 500 at login rather than a user without a name,
and it uses the *keys* of `groups` as the ids of the groups it creates.

The exchange with Keycloak is three calls:

  1. a direct access grant with the user's password, which is what actually
     authenticates them,
  2. a client_credentials grant, which gets the token of this client's own
     service account,
  3. the admin API, read with that token, for the names and the groups.

One confidential client does all three, and its service account holds
`view-users` alone. Nothing here has a credential of the `master` realm.
"""

import logging
import os

import requests
from flask import Flask, jsonify, request

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080/auth").rstrip("/")
REALM = os.environ.get("KEYCLOAK_REALM", "antares")
CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "antares-auth")
CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET", "")

# Which field of a Keycloak group becomes the id of the Antares group: `name`
# (analysts), `path` (/analysts) or `id` (a UUID). `name` by default, because
# that id is what an operator writes in antarest_external_auth_group_mapping.
GROUP_KEY = os.environ.get("KEYCLOAK_GROUP_KEY", "name")

# Seconds. Deliberately short: this call sits in the middle of a login, and a
# Keycloak that does not answer must fail rather than hold the request open.
TIMEOUT = float(os.environ.get("KEYCLOAK_TIMEOUT", "10"))

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)

app = Flask(__name__)


def _token(data):
    """A token from the realm's token endpoint, or None."""
    data = dict(data, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    try:
        response = requests.post(
            f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
            data=data,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        app.logger.error("Keycloak is not answering: %s", exc)
        return None
    if response.status_code != 200:
        app.logger.debug("token endpoint answered %s", response.status_code)
        return None
    return response.json().get("access_token")


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

    if not _token(
        {"grant_type": "password", "username": username, "password": password}
    ):
        app.logger.info("rejected %s", username)
        return jsonify(error="invalid credentials"), 401

    admin_token = _token({"grant_type": "client_credentials"})
    if not admin_token:
        app.logger.error(
            "%s authenticated but the service account of %s could not get a "
            "token: check its client secret and that service accounts are "
            "enabled on the client",
            username,
            CLIENT_ID,
        )
        return jsonify(error="service account token retrieval failed"), 500

    headers = {"Authorization": f"Bearer {admin_token}"}
    try:
        # exact=true, and not a courtesy: the endpoint searches by prefix
        # across several fields, so `bob` also matches `bobby` and the first
        # entry of the answer is not necessarily the user who just proved a
        # password.
        users = requests.get(
            f"{KEYCLOAK_URL}/admin/realms/{REALM}/users",
            headers=headers,
            params={"username": username, "exact": "true"},
            timeout=TIMEOUT,
        )
        users.raise_for_status()
        found = users.json()
        if not found:
            app.logger.error("%s authenticated but was not found by the admin API", username)
            return jsonify(error="user not found"), 404

        user = found[0]
        groups = requests.get(
            f"{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user['id']}/groups",
            headers=headers,
            timeout=TIMEOUT,
        )
        groups.raise_for_status()
    except requests.RequestException as exc:
        app.logger.error("reading %s from the admin API failed: %s", username, exc)
        return jsonify(error="user lookup failed"), 502

    # Never absent and never null: Antares-Web reads both keys without a
    # default and concatenates them into the name it displays.
    first_name = user.get("firstName") or username
    last_name = user.get("lastName") or ""

    result = {
        "user": username,
        "firstName": first_name,
        "lastName": last_name,
        "groups": {
            group[GROUP_KEY]: group["name"]
            for group in groups.json()
            if group.get(GROUP_KEY) and group.get("name")
        },
    }
    app.logger.info("%s authenticated, groups %s", username, list(result["groups"]))
    return jsonify(result), 200


if __name__ == "__main__":
    # Development only. The image runs gunicorn, see the Dockerfile.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8870)))
