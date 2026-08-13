# Déploiement Ansible d'Antares-Web (+ cluster Slurm optionnel)

Playbook Ansible qui automatise la procédure « Basic Antares-Web and Slurm
deployment » (`antares-slurm-1.3.pdf`), remise à jour pour les versions
actuelles d'[AntaREST](https://github.com/AntaresSimulatorTeam/AntaREST) et
d'[Antares Simulator](https://github.com/AntaresSimulatorTeam/Antares_Simulator).

Trois types de machines :

| Groupe d'inventaire | Rôle |
|---|---|
| `antares_web` | Construit et exécute Antares-Web (podman + quadlet) |
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

- Une distribution de la famille Debian sur toutes les machines (voir
  ci-dessous), accès `root` via `sudo`, Python 3 présent.
- La machine `antares_web` a besoin d'un accès Internet (images de conteneurs,
  paquets npm et Python, binaires du solveur).
- Le front-end Slurm télécharge lui aussi les solveurs depuis GitHub.
- Un UID/GID libre et identique partout pour le compte `antares`, `9000` par
  défaut. Le playbook s'arrête en nommant le compte en place si la paire est
  déjà prise.
- Ansible ≥ 2.15 sur la machine de contrôle, `ansible.posix` installé.

### Distributions supportées

Toutes les installations passent par `apt`, donc le périmètre est la famille
Debian. Les noms de paquets, les noms d'unités systemd et `/etc/slurm` sont
identiques sur les versions listées, et podman vient de la distribution (5.x sur
Debian 13, 4.9 sur Ubuntu 24.04, quadlet étant présent depuis la 4.4), donc rien
n'est à adapter pour passer de l'une à l'autre :

```yaml
supported_distros:      # group_vars/all.yml
  - "Debian 12"
  - "Debian 13"
  - "Ubuntu 22"
  - "Ubuntu 24"
```

Le playbook refuse de démarrer ailleurs, avec un message qui indique la
variable à étendre. `distro_check_enabled: false` désactive complètement le
contrôle.

Un point d'attention en dehors de Debian 13, la cible de la procédure de
référence : **un cluster, une distribution.** La version de Slurm empaquetée
diffère (23.11 sur Ubuntu 24.04, 24.11 sur Debian 13) et les démons
`slurmctld` / `slurmd` / `slurmdbd` ne s'interopèrent que sur quelques versions
majeures. Le `slurm.conf` généré convient aux deux, mais il ne faut pas mélanger
un front-end Debian 13 avec des nœuds de calcul Ubuntu 24.04 dans le même
cluster. La machine `antares_web` n'est pas concernée : elle ne parle au
front-end qu'en SSH.

Le verrou `apt` est attendu jusqu'à `apt_lock_timeout` secondes (300 par
défaut), les images Ubuntu lançant `apt-daily` et `unattended-upgrades` au
démarrage.

### Compte antares : le choix de l'UID/GID

```yaml
antares_uid: 9000       # group_vars/all.yml
antares_gid: 9000
```

La paire doit être **libre et identique sur toutes les machines**, serveur web,
front-end Slurm et nœuds de calcul compris : c'est ce qui rend les études
lisibles de part et d'autre du `/home` partagé en NFS.

Le défaut n'est volontairement pas 1000. `login.defs` distribue les comptes
humains à partir de `UID_MIN` (1000) et séquentiellement, donc 1000 est déjà
pris sur la plupart des images : `ubuntu` sur les images Ubuntu, `debian` ou
`admin` sur les images cloud Debian, le compte créé à l'installation sur une
install manuelle. 9000 est franchement hors de ce chemin d'allocation et très
en dessous de `UID_MAX` (60000).

Le playbook lit `passwd` et `group` avant de créer quoi que ce soit et s'arrête
en nommant le compte en place. Pour valider le choix sur tout un parc sans rien
installer :

```bash
ansible-playbook site.yml --tags common --check
```

Deux réserves :

- Sur des machines jointes à un annuaire central (LDAP, AD via SSSD), faire
  réserver la valeur. `nsswitch` rend visible une collision existante, mais pas
  un futur compte d'annuaire à qui le même UID serait attribué.
- Changer la valeur sur une machine déjà déployée renumérote le compte
  `antares` et orpheline tout ce qu'il possède : il faut alors un `chown -R`
  assumé sur `/var/antares-web` et sur le `/home` partagé.

L'UID est aussi cuit dans l'image dérivée du backend
(`antarest_add_container_user`), donc une valeur unique sur tout le parc signifie
une seule image à construire.

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
├── deploy/       config.prod.yaml, id_rsa, solveurs
├── image/        contexte de build de l'image dérivée
└── data/         état persistant : études, matrices, base PostgreSQL, logs

/etc/containers/systemd/     unités quadlet des conteneurs
/etc/systemd/system/antares-web.target
```

La configuration et les données vivent hors du dépôt : changer
`antarest_version` puis relancer le playbook met à jour l'application sans
toucher aux données.

## Conteneurs : podman et quadlet

Il n'y a **ni démon docker, ni fichier compose**. Chaque conteneur est décrit par
une unité quadlet dans `/etc/containers/systemd`, que le générateur
`podman-system-generator` transforme en service systemd à chaque
`daemon-reload`. systemd possède donc l'ordonnancement, les redémarrages et les
journaux.

Podman tourne en **rootful**, ce qui n'est pas un détail : en rootless les UID du
conteneur sont remappés à travers `/etc/subuid`, donc un conteneur tournant en
`antares_uid` n'écrirait pas des fichiers appartenant à `antares_uid` sur
l'hôte, et toute la cohérence d'UID avec le `/home` NFS s'effondrerait.

Le stack est groupé par un `.target`, ce qui remplace `compose up/down` :

```bash
systemctl start   antares-web.target
systemctl stop    antares-web.target
systemctl restart antares-web.target     # propagé aux conteneurs via PartOf=
systemctl status  antares-web.target
podman ps
journalctl -u antarest.service -f
```

Les services générés sont `antarest`, `antarest-watcher`,
`antarest-matrix-gc`, `postgresql`, `redis`, `antares-nginx` et
`antares-web-network`. Sur le front-end Slurm, la base de comptabilité suit le
même schéma sous `slurmdb.target` (`slurmdb-mariadb`, plus `slurmdb-adminer` si
activé).

Trois noms de conteneurs sont porteurs, ce sont les noms DNS sur le réseau
podman, et les renommer casse le stack silencieusement :

| Conteneur | Qui en dépend |
|---|---|
| `antarest` | `nginx.conf` amont proxifie vers `http://antarest:5000/` |
| `postgresql` | `config.prod.yaml` pointe la base sur `postgresql:5432` |
| `redis` | `config.prod.yaml` pointe le cache sur `redis` |

`postgresql` porte en plus l'alias réseau `postgres`, qui est le `container_name`
du compose amont. Compose résolvait à la fois le nom de service et le nom de
conteneur ; podman ne résout que le nom du conteneur et ses alias.

Toutes les images sont écrites **pleinement qualifiées**
(`docker.io/library/postgres:latest`, `localhost/antarest:latest`) : Debian et
Ubuntu ne définissent pas `unqualified-search-registries`, donc un nom court
n'est pas résolu et podman refuse plutôt que de deviner un registre.

## Construire une fois, déployer partout

Par défaut (`antarest_image_source: build`) la cible clone, construit le front
avec node et construit l'image. C'est autonome, mais ça demande Internet et
environ 4 Go de tas sur la machine qui fait aussi tourner les études. Sur une
boucle « détruire la VM et rejouer », ou sur plusieurs serveurs, c'est du
gaspillage : le build utilise `npm install` et non `npm ci`, donc deux machines
construites à deux dates ne produisent pas forcément le même front.

```bash
ansible-playbook build.yml                                  # une fois
ansible-playbook site.yml -e antarest_image_source=archive  # autant de fois que voulu
```

`build.yml` tourne sur le groupe d'inventaire `builder` et **réutilise les
tâches de build du déploiement**, donc les artefacts ne peuvent pas être
produits par une recette différente de celle qu'ils remplacent. Il dépose dans
`./artifacts` (gitignoré) :

| Fichier | Contenu |
|---|---|
| `antarest-image.tar.gz` | l'image du backend, UID cuit dedans |
| `thirdparty-*.tar.gz` | postgres, redis, nginx |
| `webapp-dist.tar.gz` | l'application web construite |
| `antares-*.tar.gz` | les tarballs des solveurs |
| `manifest.yml` | version, commit, UID, date |

En mode `archive`, la cible charge les images (idempotent : rien n'est
retransféré ni rechargé si l'image est déjà là), déplie le front dans le
checkout où nginx le bind-monte, et prend les solveurs dans le cache local au
lieu de GitHub. Les archives voyagent en `rsync`, pas avec le module `copy`, qui
est inadapté à des centaines de mégaoctets.

Trois contraintes à connaître :

- **Le builder doit avoir l'architecture des cibles.** Construire de l'amd64
  depuis une machine arm64 passe par de l'émulation QEMU, assez lente pour
  annuler tout le bénéfice.
- **L'UID est cuit dans l'image** (`antarest_add_container_user`), donc le
  builder et les cibles doivent s'accorder sur `antares_uid`. C'est justement ce
  qu'une valeur unique sur tout le parc garantit.
- **Le build a son propre store podman** (`antares_build_root`, par défaut
  `/data/antares-build/store`), passé en option et non écrit dans le
  `storage.conf` du builder : une machine de build manque souvent de place sur
  `/`, et rien de sa configuration podman n'est modifié.

Sans registre, c'est `N × la taille` à chaque nouvelle version, sans dédup de
couches. À une poignée de machines c'est confortable ; au-delà, un `registry:2`
sur une des machines coûte moins cher à maintenir que cette mécanique.

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
- **Pas de compose du tout.** Le PDF s'appuie sur `docker-compose` v1, en fin de
  vie. Le playbook ne remplace pas cela par compose v2 mais par podman et
  quadlet : chaque conteneur est une unité systemd, et le `docker-compose.yml`
  amont n'est plus utilisé (voir la section podman plus haut). Cela supprime au
  passage la dépendance à compose ≥ 2.24 dont les tags `!override` avaient
  besoin, puisque plus rien n'est fusionné : chaque montage est écrit
  explicitement dans son unité.
- **`ControlMachine` / `ControlAddr`** sont remplacés par `SlurmctldHost`.
- **Persistance de la base de comptabilité.** Le `docker-compose.yml` du PDF
  ne déclare aucun volume pour MariaDB : la comptabilité disparaît à la
  moindre recréation du conteneur. Ici un volume nommé la conserve.
- **Exposition réseau.** Le PDF publie MariaDB sur `0.0.0.0:3306` avec le
  compte `root`. Le playbook la publie sur `127.0.0.1` uniquement, slurmdbd
  tournant sur la même machine. Idem pour adminer, désactivé par défaut.
- **`archive_dir`.** La configuration pointe sur `/studies/archives`, chemin
  qu'aucun montage du `docker-compose.yml` amont ne fournit. Le playbook ajoute
  le montage correspondant dans l'unité du backend.
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
- **Migration depuis une version docker de ce playbook.** Le rôle
  `slurm_frontend` arrête et supprime l'ancienne unité `slurmdb.service` et son
  `docker-compose.yml`, mais **ne touche pas au volume docker `slurmdb_data`** :
  il contient l'historique de comptabilité. Reprendre une base vivante demande
  un `mariadb-dump` depuis l'ancien volume puis une restauration dans le volume
  podman `slurmdb-data`. Sur le serveur web, les données sous
  `/var/antares-web/data` sont des bind mounts et sont reprises telles quelles.
- Le patch du libellé « NNI » modifie le source avant build. Le checkout étant
  réinitialisé à chaque exécution (`git force`), le patch est réappliqué à
  chaque fois ; c'est une empreinte de build
  (`deploy/.frontend-build-stamp`) qui évite de reconstruire le front pour
  autant. Changer `antarest_login_username_label` déclenche bien une
  reconstruction.
