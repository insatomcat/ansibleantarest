# podman

Installs podman and proves the machine can run the units the rest of the
deployment writes. Pulled in by the `antares_web` play, and by the Slurm
front-end when it runs the accounting database.

It does three things beyond the install:

- **Enforces the 4.4 floor.** Quadlet landed there, and it is a floor the units
  themselves keep honouring: a key added after 4.4 fails to generate on the
  oldest supported release rather than on the version that introduced it. See
  the note in
  `roles/antares_web/templates/quadlet/postgresql.container.j2`, the one place
  where that price has been paid.
- **Checks container name resolution.** The whole stack resolves containers by
  name on the podman network, and a missing `aardvark-dns` degrades silently,
  so podman is asked where it expects the binary rather than the path being
  guessed per distribution.
- **Qualifies image names.** Debian and Ubuntu set no
  `unqualified-search-registries`, so short names are rejected; every image in
  this repository is fully qualified and the template makes that explicit.

`firewalld.yml` is the RedHat-family half: with firewalld kept by the operator
(`hardening_manage_firewalld: false`), the `podman*` bridges go into the
`trusted` zone, without which aardvark-dns and `PublishPort` are dropped.

Variables in `defaults/main.yml`. The quadlet mechanics are documented in
[Containers: podman and quadlet](../../docs/containers.md).
