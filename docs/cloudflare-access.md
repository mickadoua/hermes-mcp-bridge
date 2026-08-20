# Mettre le pont derrière Cloudflare Access

Objectif : que le pont soit joignable depuis Claude sur n'importe quel appareil, sans qu'aucun port ne soit ouvert sur la box, et sans qu'aucune IP publique ne soit à protéger.

Les noms d'hôtes, identifiants d'application et adresses de ce document sont des placeholders.

## 1. Le tunnel

Créer un tunnel dans Zero Trust, puis publier le pont dessus. Le connecteur `cloudflared` tourne à côté du pont (voir [`compose.yaml`](../compose.yaml)) et **sort** vers Cloudflare : rien n'entre.

Route publique du tunnel :

```
agent.example.com  →  http://hermes-mcp-bridge:8080
```

Renseigner le même nom dans `PUBLIC_HOSTNAMES`, sinon le SDK MCP répond 421 (voir [dépannage](depannage.md)).

## 2. L'application Access

Créer une application **self-hosted** sur `agent.example.com`.

Puis, et c'est le point qui coûte du temps : **deux populations, deux politiques distinctes**.

### Politique « machines » — action *Autorisation de service*

Pour les scripts, avec un jeton de service (une paire d'en-têtes `CF-Access-Client-Id` / `CF-Access-Client-Secret`).

> Une politique dont l'action est « Autorisation de service » n'évalue **que** du non-identitaire : jetons, mTLS, IP. Y ajouter une règle sur une adresse e-mail ne produit aucune erreur — la règle est simplement ignorée.

### Politique « humains » — action *Autoriser*

Pour vous, via votre fournisseur d'identité (e-mail, Google, GitHub…).

> La réciproque est vraie : une politique « Autoriser » avec un sélecteur de jeton ne valide pas le jeton, elle redirige vers une page de login.

Access évalue les politiques de service d'abord, les autres ensuite.

## 3. L'audience

Relever le **tag d'audience (AUD)** de l'application et le mettre dans `ACCESS_AUD`. C'est ce qui distingue *cette* application des autres applications du même compte : sans ce contrôle, un jeton émis pour une autre app passerait la validation du pont.

Renseigner aussi `ACCESS_TEAM_DOMAIN` avec `https://<votre-équipe>.cloudflareaccess.com`.

## 4. L'OAuth géré

L'interface des connecteurs Claude ne propose que de l'OAuth : pas de bearer, pas d'en-tête personnalisé. Or un jeton de service Cloudflare **est** une paire d'en-têtes — toute la configuration « machine » est donc structurellement inutilisable par un connecteur web.

Activer donc l'**OAuth géré** sur l'application, qui fait d'Access le fournisseur OAuth. Sa documentation pose une condition : ne l'activer que pour un serveur MCP qui valide le JWT d'Access. C'est ce que fait ce pont — gardez `ACCESS_VERIFY_JWT=true`.

Déclarer l'URI de redirection, sans quoi l'enregistrement dynamique du client échoue (« Impossible de s'inscrire auprès du service de connexion ») :

```
https://claude.ai/api/mcp/auth_callback
```

## 5. Brancher le connecteur

Dans Claude, ajouter un connecteur MCP distant pointant sur :

```
https://agent.example.com/mcp
```

La première connexion ouvre la page de login Access ; ensuite les sept outils apparaissent.

## Vérifier, dans le bon ordre

Isoler une variable à la fois. Avant de brancher le connecteur, tester la chaîne avec un simple **jeton de service** : Cloudflare émet alors un vrai JWT **sans impliquer OAuth**.

```bash
curl -sS https://agent.example.com/healthz \
  -H "CF-Access-Client-Id: $CF_ID" \
  -H "CF-Access-Client-Secret: $CF_SECRET"
```

Puis, depuis le NAS et **sans le moindre en-tête**, vérifier que l'origine refuse bien :

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://hermes-mcp-bridge:8080/mcp   # attendu : 401
```

Si celui-ci répond autre chose qu'un 401, le pont ne valide rien et n'importe quel conteneur voisin peut piloter le kanban.
