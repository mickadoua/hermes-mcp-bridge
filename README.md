# hermes-mcp-bridge

Pont MCP en **Streamable HTTP** entre un agent [Hermes](https://github.com/mickadoua) auto-hébergé et un client MCP distant (Claude sur le web ou mobile, ou tout autre client compatible), derrière **Cloudflare Access**.

Deux contraintes le définissent, et elles tirent dans des directions opposées : ne rien ouvrir sur Internet, et ne donner à aucun process automatisé les droits qu'il faudrait pour faire des dégâts.

> Le récit complet de la mise en service, avec les cinq murs pris en chemin :
> [Brancher un agent self-hosted sur Claude sans lui donner les clés de la maison](https://dm-consulting.tech/fr/blog/brancher-agent-self-hosted-sur-claude).

## Ce qu'il fait

Sept outils, tous en passant par **l'API REST du dashboard** d'Hermes — pas par le socket Docker, pas par ses bases SQLite :

| Outil | Rôle |
|---|---|
| `kanban_board` | état du kanban, colonne par colonne |
| `kanban_task` | détail d'une carte : corps, statut, commentaires, résultat |
| `kanban_create` | dépose une carte **en `triage`, sans assignée** |
| `kanban_comment` | commente une carte sans la valider |
| `vault_list` | liste les fichiers produits par l'agent |
| `vault_read` | lit un de ces fichiers |
| `ask` | question ponctuelle via la gateway compatible OpenAI |

Ce choix de passer par l'API publique paie trois fois : le pont n'a besoin d'aucun privilège particulier, il ne dépend d'aucun détail interne (donc il survit aux mises à jour d'Hermes), et sa surface est exactement celle d'une API déjà pensée pour être appelée.

## Ce qu'il ne fera jamais

**Approuver une carte.**

L'agent a le droit de préparer un mail de démarchage. Il n'a pas le droit de l'envoyer. Entre les deux il y a une colonne du kanban : la carte s'arrête en attente de validation, et c'est un humain qui la fait passer en « fait ». Ce geste *est* le garde-fou.

Exposer cette transition l'aurait vidée de son sens : un agent capable d'approuver son propre travail n'est plus sous supervision, il a juste une étape de plus à franchir. Il n'y a donc pas de code pour ça dans ce dépôt, et [un test](tests/test_hermes.py) échoue si quelqu'un en ajoute.

Même logique à la création : une carte déposée par le pont naît en `triage`, sans assignée, donc gelée. L'agent distant peut **proposer** du travail, pas en **lancer**.

## Démarrage rapide

```bash
git clone https://github.com/mickadoua/hermes-mcp-bridge.git
cd hermes-mcp-bridge
cp .env.example .env      # puis renseigner HERMES_API_URL, ACCESS_AUD, PUBLIC_HOSTNAMES
pip install -e ".[dev]"
python -m hermes_mcp_bridge
```

En conteneur, avec le connecteur du tunnel à côté :

```bash
docker compose up -d --build
```

Aucun port n'est publié sur l'hôte : le tunnel sort, rien n'entre.

## Configuration

Tout passe par l'environnement ; voir [`.env.example`](.env.example) pour la liste commentée. Les quatre valeurs qui comptent :

| Variable | Pourquoi elle compte |
|---|---|
| `HERMES_API_URL` | l'URL interne du dashboard, telle que le conteneur du pont la joint |
| `ACCESS_TEAM_DOMAIN` | l'émetteur attendu du JWT (`https://<équipe>.cloudflareaccess.com`) |
| `ACCESS_AUD` | le tag d'audience **de cette application** — sans lui, un jeton émis pour une autre app du même compte passerait |
| `PUBLIC_HOSTNAMES` | les noms d'hôte publics servis par le tunnel ; non renseignés, le SDK rejette tout en 421 (voir plus bas) |

Les chemins REST du dashboard sont regroupés en haut de [`hermes_mcp_bridge/hermes.py`](hermes_mcp_bridge/hermes.py). Si votre version d'Hermes les expose ailleurs, c'est le seul endroit à modifier.

## Sécurité

Le pont **valide lui-même** le JWT que Cloudflare Access injecte dans chaque requête : signature via les clés publiques du compte, émetteur, audience, expiration.

Ce n'est pas redondant avec le filtrage du bord. Le conteneur écoute sur `0.0.0.0` et partage un réseau Docker avec d'autres services : sans cette couche, n'importe quel conteneur voisin pilote le kanban sans authentification, sans jamais passer par Cloudflare. Le bord protège d'Internet, pas des voisins. C'est aussi la condition posée par Cloudflare pour activer l'« OAuth géré » : ne l'activer que pour un serveur MCP qui valide le JWT d'Access.

`ACCESS_VERIFY_JWT=false` existe pour le développement local, et le pont le journalise bruyamment à chaque démarrage.

La mise en place côté Cloudflare — tunnel, les **deux** politiques (machines et humains, qui ne se mélangent pas), OAuth géré, URI de redirection — est décrite dans [`docs/cloudflare-access.md`](docs/cloudflare-access.md).

## Le 421 qui surprend tout le monde

Le SDK MCP Python embarque une protection anti-DNS-rebinding. `streamable_http_app()` prend un paramètre `host` qui vaut `127.0.0.1` par défaut, et **si on ne configure pas explicitement la politique, le SDK en dérive une restreinte à la loopback** : tout nom d'hôte public est rejeté en `421 Invalid Host header`, avec pour seule trace une ligne de log côté serveur — le client, lui, ne voit qu'une erreur de transport générique.

C'est à ça que sert `PUBLIC_HOSTNAMES` : chaque nom est décliné en variante « avec port », puis passé au SDK. Deux tests figent le comportement dans les deux sens ([`tests/test_server.py`](tests/test_server.py)).

## Tests

```bash
pytest
```

La suite vérifie surtout ce qu'on oublie de vérifier : qu'un **jeton légitime passe**. Un validateur qui refuse tout ressemble trait pour trait à un validateur correct ; « sans jeton → 401 » et « jeton forgé → 401 » ne prouvent rien tout seuls.

## Licence

MIT.
