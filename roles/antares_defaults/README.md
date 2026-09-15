# antares_defaults

No tasks. Nothing but `defaults/main/`, one file per area, mirroring the pages
of `docs/`.

## Why it exists

This repository has no `group_vars/` next to the playbooks. Every default is in
the code, and the inventory of a deployment is the only place that deployment
describes itself.

That only works because of where Ansible puts role defaults. Its precedence has
exactly two tiers *below* the inventory: role defaults, and the inventory's own
group vars. A `vars:` block on a play sits well *above* the inventory, so a
default written there could not be overridden at all - which is why this is a
role and not a `vars_files:`.

A role default is scoped to its role, though, and plenty of values here are read
by several roles (`antares_user`, `container_registry`, the ports the web stack
publishes and the front door routes to), or by a playbook that runs no role at
all - `verify.yml` reads about forty of them from outside the inventory, and
`build.yml` reads the switches of a deployment on a builder that runs none of
the roles they belong to. Those cannot live in the role that happens to use
them.

So they live here, and every play loads this role first. Its defaults then reach
every role listed after it and the play's own `tasks:`.

## What goes here, and what does not

- Read by one role only -> that role's `defaults/main.yml`. A variable that
  ends up here because it shared a comment block with a shared one is a bug:
  the test is who reads it, not where it was written.
- Read by more than one role, or by `site.yml`, `build.yml` or `verify.yml`
  outside a role -> here.
- Read through `hostvars[some_other_host]` -> **neither**. A role default is
  invisible there, whatever the play does. `slurm.conf` and `/etc/hosts` are
  rendered from every node's view of the others, which is why the per-node
  hardware description is an inventory variable, in
  `inventory/group_vars/slurm.yml`.

## Using it in a new play

Nothing crosses a play boundary. A play that reads any variable from here lists
it first:

```yaml
- name: Something new
  hosts: antares_web
  roles:
    - antares_defaults
    - the_role_you_wanted
```

A `when:` on a role entry sees these defaults too, which is what keeps the
`*_enabled` guards of `site.yml` working. In a play with `pre_tasks:`, import it
there instead: pre_tasks run before `roles:`. See `build.yml`.

Every variable is documented on the `docs/` page of its area, and commented
where it is defined.
