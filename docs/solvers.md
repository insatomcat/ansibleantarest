# Solvers and Antares-Xpansion

Both are installed on the web machine (the local launcher) and in the shared `/home` (the Slurm launcher). Xpansion needs a cluster, see [the Slurm cluster](slurm.md).

## Solvers

```yaml
# Ubuntu-22.04 on the Debian family, OracleServer-8.10 on the RedHat one
antares_solver_os: "{{ 'OracleServer-8.10' if ansible_facts['os_family'] == 'RedHat' else 'Ubuntu-22.04' }}"
antares_solvers:
  - version: "8.8.17"      # Antares_Simulator release tag
    study_version: "8.8"   # major.minor string used by Antares-Web
    bin: "antares-8.8-solver"
  - version: "9.2.0"
    study_version: "9.2"
    bin: "antares-solver"
```

Executable names changed across generations: `antares-<X>.<Y>-solver` for the 8.x line and `antares-solver` from 9.x onward. Each entry in this list is installed on both the web machine (local launcher) and in the shared `/home` (Slurm launcher), and populates the binaries table in `config.prod.yaml` and the `case` in `launchAntares.sh`.

`antares_solver_os` selects which build of each release is downloaded, and it is not cosmetic: the Ubuntu 22.04 build needs glibc 2.35 and does not start on EL 9, which has 2.34, while the project's Oracle Linux 8 build (glibc 2.28) runs on every rebuild. The default follows the family of each target, so a Debian web server driving an Oracle Linux cluster installs the right binary on both sides.

## Antares-Xpansion

Investment optimisation, off by default. A release weighs about 250 MB and pulls an MPI runtime onto every compute node, which a cluster that only runs simulations has no use for. It needs a cluster: Antares-Web's local launcher ignores the Xpansion mode, so this is deployed on the `slurm` group and nowhere else (see [Limitations](limitations.md)). A single machine can be that cluster, which is the point of [the cluster on the web machine itself](slurm.md#the-cluster-on-the-web-machine-itself).

```yaml
antares_xpansion_enabled: true
antares_xpansions:
  - version: "1.3.0"           # antares-xpansion release tag
    study_version: "8.8"       # major.minor of the solver *it bundles*
    bin: "antares-8.8-solver"  # name of that bundled solver, 8.x naming
    archive: "antaresXpansion-1.3.0-xpress-ubuntu-20.04.tar.gz"
  - version: "1.4.0"
    study_version: "9.2"
```

`study_version` is the key point. An Xpansion release ships the `antares-solver` it was built against and runs the study with that one, not with the solvers installed next to it, so the entry must carry the version of the bundled binary rather than a version of your choice. From `antares-version.json` of each tag:

| Xpansion | bundled Antares | | Xpansion | bundled Antares |
|---|---|---|---|---|
| 1.3.0 | 8.8.3 | | 1.6.0 | 9.3.1 |
| 1.4.0 | 9.2.1 | | 1.8.0 | 9.3.6 |
| 1.5.0 | 9.3.0 | | 1.9.0 | 10.1.1 |

The default carries one release per study version of `antares_solvers` above, so both entries of the launch dialog work with the Xpansion box ticked. Two optional keys cover the releases that break the pattern, and 1.3.0 needs both: `archive` when the asset is not named `antaresXpansion-<version>-<os>.tar.gz` (1.3.0 carries an extra `-xpress-`, ships an Ubuntu 20.04 build and an Oracle Linux 8.9 one rather than 8.10 - the shipped value is a Jinja expression picking by family), and `bin` when the bundled solver is not called `antares-solver`, which is the case of the whole 8.x line.

Dropping an entry is a legitimate way to save the download: a cluster whose studies are all in 9.2 has no use for the 8.8 package.

The package is unpacked once into the shared `/home` (`slurm_xpansion_dir`, next to the solvers), and the MPI runtime `benders` is linked against is installed on every machine of the `slurm` group. `ansible-playbook site.yml --tags xpansion` redeploys just that.

What arrives on the cluster is decided by Antares-Web: `antares-launcher` sends the mode as the third argument of the launch script, and `launchAntares.sh` answers all four of them. `ANTARES` runs the solver as before, `ANTARES_XPANSION_CPP` runs `antares-xpansion-launcher --step full`, and the two others - the historical R implementation and the trajectory mode, which run several studies at once - fail with a message naming what is missing. They fail on purpose: running an ordinary simulation in their place returns a green study for an investment optimisation that never ran.

Benders runs on a single MPI rank by default (`slurm_xpansion_mpi_procs`). Raising it is not just a number: the launch script asks for one task on one node, Open MPI counts its slots from that allocation, and inside an allocation `mpirun` goes back through Slurm, which needs the PMIx support the distribution packages do not always carry. For the same reason the Xpansion launcher is the one step of the script that is *not* wrapped in `srun`: an MPI binary started inside an `srun` step is a direct launch as far as Open MPI is concerned, and it aborts in `MPI_Init` without Slurm's PMI (`OPAL ERROR: Unreachable in ext3x_client.c`).

Measured on the five-machine lab (Ubuntu 24.04, one rank, one CPU per task): the `SmallTestFiveCandidates` example converges in 22 Benders iterations, 42 seconds wall clock and 1.1 GB of RSS on the compute node, and the results (`expansion/out.json`) come back inside the simulator output archive of the zip Antares-Web collects. **Size the compute nodes accordingly**: that is a five-candidate example, and it is already four times what a plain simulation of the same study needs.

Both families are covered, and the only distribution-specific thing is where Open MPI puts itself. The Debian family installs `openmpi-bin` and finds `libmpi.so.40` in the default search path; EL installs `openmpi` from AppStream, which keeps its files under `/usr/lib64/openmpi`, so the launch script prepends `antares_xpansion_mpi_bin_dir` and `antares_xpansion_mpi_lib_dir` to `PATH` and `LD_LIBRARY_PATH`. Both are computed from the family and can be overridden.

The supported distributions were qualified one by one, running the example study to convergence with the release each family gets:

| Distribution | Open MPI | Xpansion 1.3.0 (8.8) | Xpansion 1.4.0 (9.2) |
|---|---|---|---|
| Debian 13 | `openmpi-bin` 5.0 | converged | converged |
| Ubuntu 24.04 | `openmpi-bin` 4.1.6 | converged, on the cluster | converged, on the cluster |
| Ubuntu 26.04 | `openmpi-bin` 5.0 | converged | converged |
| Oracle Linux 9 | `openmpi` 4.1.1 | converged | converged |
| Oracle Linux 10 | `openmpi` 5.0.2 | converged | converged |
| Rocky Linux 9 / 10 | `openmpi` 4.1.1 / 5.0.9 | package checked | package checked |
| CentOS Stream 9 / 10 | `openmpi` 4.1.1 / 5.0.2 | package checked | package checked |

Open MPI 5.0 kept the `libmpi.so.40` soname of the 4.x line, which is why the same `benders` binary loads on an EL 10 and on an EL 9. The rebuilds are marked "package checked" the way the rest of this table works: same family, same code path, same package from the same AppStream, and the CI deploys a cluster on each of them.

Ubuntu 24.04, Oracle Linux 9 and Oracle Linux 10 carry the deployment on every pull request, which is one target per thing that can break a binary the playbook only unpacks: the oldest glibc of each family, and the two Open MPI majors. What CI checks is the deployment rather than a converged optimisation, since 1.1 GB of RSS does not fit in the 768 MB compute nodes of a runner: `verify.yml` asks each launcher for the version of the solver it bundles, which both proves the binary starts there and confirms the `study_version` of the entry.

