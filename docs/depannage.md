# Dépannage

Les symptômes rencontrés en vrai, et ce qu'ils veulent dire.

## `421 Invalid Host header`

Le SDK MCP Python embarque une protection anti-DNS-rebinding. Sans politique explicite, il en dérive une depuis le paramètre `host` de `streamable_http_app()`, qui vaut `127.0.0.1` par défaut : tout nom d'hôte public est rejeté.

Le 421 est une réponse HTTP en texte brut, pas une erreur JSON-RPC : le client MCP ne remonte qu'une erreur de transport générique, et le nom d'hôte refusé n'apparaît que dans les logs du serveur.

**Correctif** : renseigner `PUBLIC_HOSTNAMES` avec le nom servi par le tunnel. Le pont décline chaque nom en variante « avec port ». Derrière un reverse proxy qui contrôle déjà l'en-tête `Host`, désactiver explicitement la protection est plus honnête que de bricoler la liste — au moins la décision est écrite.

## « Impossible de s'inscrire auprès du service de connexion »

Claude s'enregistre dynamiquement comme client OAuth et déclare l'URL de retour. Si le champ « URI de redirection autorisées » de l'application Cloudflare est vide, aucune URI n'est acceptée, donc l'enregistrement est refusé.

**Correctif** : déclarer `https://claude.ai/api/mcp/auth_callback`.

## Une règle Access qui ne s'applique pas

Une politique dont l'action est « Autorisation de service » n'évalue **que** du non-identitaire. Y ajouter une adresse e-mail ne produit aucune erreur : la règle est ignorée. Inversement, une politique « Autoriser » avec un sélecteur de jeton redirige vers un login au lieu de valider le jeton.

**Correctif** : deux politiques distinctes sur la même application, une par population.

## 401 alors que le jeton semble bon

Dans l'ordre de probabilité :

1. `ACCESS_AUD` ne correspond pas au tag d'audience de **cette** application ;
2. `ACCESS_TEAM_DOMAIN` n'est pas exactement l'émetteur (`iss`) du jeton, schéma `https://` compris ;
3. le jeton est expiré — Access les émet à durée courte.

Les logs du pont impriment la raison exacte remontée par PyJWT.

## Le pont répond sans authentification

Vérifier `ACCESS_VERIFY_JWT`. À `false`, le pont accepte toute requête qui l'atteint et le journalise à chaque démarrage. Ce mode n'existe que pour le développement local : sur un réseau Docker partagé, il donne le kanban à tous les conteneurs voisins.

## Tester le cas passant

Après avoir ajouté une validation, « sans jeton → 401 » et « jeton forgé → 401 » sont des preuves rassurantes qui ne prouvent rien : **un validateur qui refuse tout ressemble trait pour trait à un validateur correct**. La seule preuve qui compte est qu'un jeton légitime passe — c'est ce que couvre `tests/test_access.py::test_jeton_legitime_passe`.
