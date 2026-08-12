# Déploiement Ansible d'Antares-Web (+ cluster Slurm optionnel)

Playbook Ansible qui automatise la procédure « Basic Antares-Web and Slurm
deployment » (`antares-slurm-1.3.pdf`), remise à jour pour les versions
actuelles d'[AntaREST](https://github.com/AntaresSimulatorTeam/AntaREST) et
d'[Antares Simulator](https://github.com/AntaresSimulatorTeam/Antares_Simulator).

Trois types de machines :

| Groupe d'inventaire | Rôle |
|---|---|
| `antares_web` | Construit et exécute Antares-Web (Docker Compose) |
| `slurm_frontend` | Contrôleur Slurm, base de comptabilité, serveur NFS du `/home` |
| `slurm_compute` | Nœuds de calcul, montent le `/home` partagé en NFS |

Slurm est **optionnel** : avec `slurm_enabled: false` seul Antares-Web est
déployé et les études tournent avec le solveur local, sur la machine web.
Quand Slurm est activé, les deux lanceurs sont exposés dans l'interface et
`antarest_default_launcher` choisit celui proposé par défaut.

## Démarrage rapide

```bash
ansible-galaxy collection install -r requirements.yml

# adapter l'inventaire et les variables
$EDITOR inventory/hosts.yml
$EDITOR group_vars/all.yml      # au minimum les secrets, voir plus bas

ansible-playbook site.yml
```

L'interface répond ensuite sur `http://<antares_web>/` (identifiants par
défaut : `admin` / `admin`).

Sans cluster :

```bash
ansible-playbook site.yml -e slurm_enabled=false
```

L'inventaire ne contient alors que le groupe `antares_web`.

## Prérequis

- Debian 12 (bookworm) ou 13 sur toutes les machines, accès `root` via
  `sudo`, Python 3 présent.
- La machine `antares_web` a besoin d'un accès Internet (images Docker,
  paquets npm et Python, binaires du solveur).
- Le front-end Slurm télécharge lui aussi les solveurs depuis GitHub.
- L'UID/GID 1000 doit être libre sur toutes les machines : le playbook y crée
  le compte `antares` et s'arrête avec un message explicite si un autre compte
  l'occupe déjà.
- Ansible ≥ 2.15 sur la machine de contrôle, `ansible.posix` installé.

## À changer avant la mise en production

Dans `group_vars/all.yml` (ou dans un fichier chiffré avec `ansible-vault`) :

| Variable | Défaut | Remarque |
|---|---|---|
| `antarest_jwt_key` | `secretkeytochange` | clé de signature des jetons |
| `antarest_admin_password` | `admin` | mot de passe du compte admin |
| `antarest_db_password` | `somepass` | mot de passe PostgreSQL |
| `slurmdbd_db_password` | `changeme-slurm-acct` | mot de passe MariaDB de la compta Slurm |

Le mot de passe PostgreSQL n'est lu qu'à la première initialisation du volume :
le changer ensuite impose de vider `/var/antares-web/data/db`.

## Variables principales

### Solveurs

```yaml
antares_solver_os: "Ubuntu-22.04"
antares_solvers:
  - version: "8.8.17"      # version de la release Antares_Simulator
    study_version: "8.8"   # clé « major.minor » utilisée par Antares-Web
    bin: "antares-8.8-solver"
  - version: "9.2.0"
    study_version: "9.2"
    bin: "antares-solver"
```

Le nom de l'exécutable change selon la génération : `antares-<X>.<Y>-solver`
jusqu'à la 8.x, `antares-solver` à partir de la 9.x. Chaque entrée de cette
liste est installée à la fois sur la machine web (lanceur local) et dans le
`/home` partagé (lanceur Slurm), et alimente automatiquement la table des
binaires de `config.prod.yaml` ainsi que le `case` de `launchAntares.sh`.

### Antares-Web

```yaml
antarest_version: "v2.33.0"   # tag, branche ou commit du dépôt AntaREST
antarest_http_port: 80
antarest_force_rebuild: false # force la reconstruction front + image
```

### Libellé du champ de connexion

Le formulaire de connexion intitule son champ identifiant `NNI`, le numéro
d'identification interne RTE, codé en dur dans le source. Le playbook le
remplace avant de construire le front :

```yaml
antarest_patch_login_label: true
antarest_login_username_label: '{t("global.username")}'
```

La valeur par défaut réutilise la clé de traduction du projet, donc le champ
s'affiche « Username » ou « Nom » selon la langue du navigateur, au lieu de
figer une chaîne. Pour un libellé fixe, mettre un littéral entre guillemets :
`'"Identifiant"'`.

Le fichier concerné a changé de place entre les versions
(`webapp/src/components/wrappers/LoginWrapper.tsx` jusqu'à la 2.19,
`webapp/src/routes/login/index.tsx` en 2.33), il est donc localisé par son
contenu et non par son chemin. Si une version future supprime le libellé, la
tâche le signale et ne fait rien.

### Slurm

```yaml
slurm_cluster_name: antares
slurm_partition: antares
slurm_select_type: "select/cons_tres"   # select/linear pour des nœuds exclusifs
slurmdbd_innodb_buffer_pool_size: "1G"
```

Les caractéristiques des nœuds de calcul (`CPUs`, `SocketsPerBoard`,
`CoresPerSocket`, `ThreadsPerCore`, `RealMemory`) sont déduites des facts
Ansible. Elles se surchargent par hôte dans l'inventaire avec
`slurm_node_cpus`, `slurm_node_sockets`, `slurm_node_cores_per_socket`,
`slurm_node_threads_per_core` et `slurm_node_real_memory`.

Le nombre maximum de cœurs proposé dans la fenêtre de lancement est plafonné
au plus petit nœud de calcul, sinon un job demandant plus de cœurs qu'aucun
nœud n'en possède reste en attente indéfiniment.

## Arborescence sur le serveur Antares-Web

```
/var/antares-web/
├── AntaREST/     dépôt git, jetable : rien de généré n'y est écrit
├── deploy/       config.prod.yaml, docker-compose.override.yml, id_rsa, solveurs
└── data/         état persistant : études, matrices, base PostgreSQL, logs
```

La configuration et les données vivent hors du dépôt : changer
`antarest_version` puis relancer le playbook met à jour l'application sans
toucher aux données.

## Tags utiles

```bash
ansible-playbook site.yml --tags antares_web     # redéployer l'application
ansible-playbook site.yml --tags slurm           # cluster seulement
ansible-playbook site.yml --tags solver          # (re)poser les solveurs
ansible-playbook site.yml -e antarest_force_rebuild=true   # rebuild complet
```

`slurm.conf` est généré à partir des facts de **tous** les nœuds de calcul :
éviter `--limit` sur un sous-ensemble de `slurm_compute` sans avoir figé les
variables `slurm_node_*` dans l'inventaire.

## Écarts par rapport au PDF

La procédure de référence date de septembre 2025 ; plusieurs points ont changé
en amont depuis.

- **Format des lanceurs.** `launcher.local` / `launcher.slurm` a été remplacé
  par une liste `launcher.launchers`, chaque entrée portant ses propres `id`,
  `name` et `type`, `launcher.default` désignant un `id`. L'ancien format n'est
  plus lu du tout.
- **Version passée au script de lancement.** antares-launcher transmet
  désormais la version au format `major.minor` (`8.8`) et non plus au format
  compact (`910`). Le `case` généré accepte les deux formes, donc le test
  `if [ "$ANTARES_VERSION" = "910" ]` du PDF ne matcherait plus rien
  aujourd'hui.
- **Image de build du front.** Le `Dockerfile_build_frontend` du PDF installe
  `requirements.txt` avec Python 3.9 et nvm ; le projet est passé à `uv` et
  `pyproject.toml`, `requirements.txt` n'existe plus. Le playbook construit le
  front dans une image `node` officielle, à la version épinglée par
  `webapp/.nvmrc` (22.13.0 pour la 2.33.0).
- **Compte dans l'image.** Le PDF édite le `Dockerfile` du projet pour y
  ajouter `useradd`. Le playbook laisse le dépôt intact et empile une image
  dérivée, ce qui survit aux évolutions du `Dockerfile` amont (la ligne
  `ENV ANTARES_CONF` visée par le PDF s'appelle maintenant `ENV ANTAREST_CONF`).
- **`docker-compose` v1** est en fin de vie : le playbook installe le dépôt
  Docker officiel et le plugin `docker compose` v2 (≥ 2.24 pour les tags
  `!override`). `docker_use_upstream_repo: false` repasse aux paquets Debian,
  il faut alors ajuster `docker_compose_cmd`.
- **`ControlMachine` / `ControlAddr`** sont remplacés par `SlurmctldHost`.
- **Persistance de la base de comptabilité.** Le `docker-compose.yml` du PDF
  ne déclare aucun volume pour MariaDB : la comptabilité disparaît à la
  moindre recréation du conteneur. Ici un volume nommé la conserve.
- **Exposition réseau.** Le PDF publie MariaDB sur `0.0.0.0:3306` avec le
  compte `root`. Le playbook la publie sur `127.0.0.1` uniquement, slurmdbd
  tournant sur la même machine. Idem pour adminer, désactivé par défaut.
- **`archive_dir`.** La configuration pointe sur `/studies/archives`, chemin
  qu'aucun montage du `docker-compose.yml` amont ne fournit. Le playbook ajoute
  le montage correspondant.
- **Répertoire de scratch.** Comme dans le PDF il est placé dans le `/home`
  partagé, mais sous `~/scratch/` créé par le playbook.
- **Champ « NNI ».** Toujours présent en 2.33.0, mais déplacé de
  `webapp/src/components/wrappers/LoginWrapper.tsx` ligne 170 vers
  `webapp/src/routes/login/index.tsx` ligne 149. Le playbook le repère par son
  contenu et le remplace par la clé de traduction du projet (voir plus haut).

## Limites connues

- Xpansion n'est pas couvert : le script de lancement dérive du modèle
  `launchAntares_v1.1.2.sh`, qui attend un environnement R et des
  *environment modules* absents ici.
- Aucun pare-feu n'est configuré. Les machines sont supposées être sur un
  réseau de confiance, comme dans la procédure de référence.
- Pas de TLS devant l'interface web. Placer un reverse proxy devant si
  l'exposition dépasse le réseau interne.
- Le patch du libellé « NNI » modifie le source avant build. Le checkout étant
  réinitialisé à chaque exécution (`git force`), le patch est réappliqué à
  chaque fois ; c'est une empreinte de build
  (`deploy/.frontend-build-stamp`) qui évite de reconstruire le front pour
  autant. Changer `antarest_login_username_label` déclenche bien une
  reconstruction.
