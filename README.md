# Test des fenêtres Codex avec ChatGPT Plus

**Préparation uniquement : aucun envoi activé par défaut.** Ce dépôt prépare un
test à un seul message, pas encore un service permanent. Il utilise une connexion
ChatGPT Plus, jamais une clé API séparément facturée. Il ne lit ni ne modifie
une tâche ou une conversation ChatGPT existante.

## Fonctionnement

1. Un lancement manuel `test` mémorise une échéance fictive avec fuseau horaire.
   Exemple du scénario discuté : `2026-10-19T19:00:00+02:00` (Paris).
2. Le client officiel Codex lit `account/rateLimits/read`. Le programme remplace
   l'échéance fictive par celle du compte, sans coder en dur l'heure réelle.
3. Les contrôles suivent cette échéance toutes les cinq minutes. Une fenêtre
   active démarrée par l'utilisateur annule l'envoi prévu.
4. Après expiration, le programme vise échéance + cinq minutes. GitHub peut
   retarder ou manquer un passage ; il ne garantit pas cet horaire.
5. Avant l'envoi, le programme relit le quota et enregistre une intention durable.
   Il lance au plus **un appel CLI** (le CLI peut lui-même reconnecter ses
   transports), puis vérifie l'apparition d'une échéance stable d'environ cinq
   heures. Si nécessaire, il relit le quota aux cibles +15, +30, +60 et +120
   secondes après le retour du CLI. Chaque contrôle utilise deux lectures
   espacées de huit secondes et s'arrête dès confirmation. Une lecture lente
   peut dépasser une cible. Les sorties du CLI ne sont pas publiées.
6. Le test s'arrête après cet essai, même en cas de résultat incertain. Aucun
   deuxième message ni enchaînement permanent n'est activé.

Le succès logiciel est une observation compatible avec un démarrage de fenêtre.
Comparer avec l'interface du compte, sans usage concurrent, reste nécessaire.
Une échéance fictive teste le recalage, pas un véritable reset mondial.

## Préparation sans activation

- Publier les fichiers sur la branche par défaut du dépôt GitHub choisi.
  Les tests hors ligne fonctionnent sans connexion ChatGPT.
- Laisser la variable Actions `QUOTA_TEST_ARMED` absente ou à `false`.
  Les passages programmés n'accèdent alors à aucun identifiant et n'envoient rien.
- Le job connecté exige un dépôt public pour utiliser les runners standard gratuits.
  Il refuse de s'exécuter dans un dépôt privé. Ne pas rendre public un dépôt privé
  sans avoir revu son contenu et donné son accord.
- Ne pas lancer le mode `test` avant le créneau convenu. Son autorisation expire
  après 24 heures et porte sur un seul essai.

La configuration des identifiants ci-dessous reste à faire à l'activation.
Aucun identifiant de la session qui prépare ce dépôt n'est récupéré.

## Connexion sécurisée, au moment choisi

Le code reprend l'idée du projet MIT
[claude-codex-warmer](https://github.com/viseshb/claude-codex-warmer), mais pas son
workflow : pas de secours aveugle sur le dernier envoi ni de retry de message.

1. Sur une machine de confiance, créer un répertoire Codex dédié et y effectuer
   une connexion officielle ChatGPT (par appareil si disponible). Ne pas copier
   le fichier de la session utilisée au quotidien. Une session dédiée réduit les
   conflits ; sa révocation reste possible.
2. Enregistrer son fichier d'authentification uniquement dans le secret Actions
   `CODEX_AUTH_JSON`, via les paramètres sécurisés GitHub ou l'entrée standard de
   `gh secret set`. Ne jamais le coller dans une conversation, un ticket, un
   commit ou un journal. Ne plus utiliser la copie locale transférée : le runner
   devient le propriétaire de cette session.
3. Créer un jeton GitHub limité à ce dépôt, permission **Secrets: read and write**,
   et l'enregistrer dans le secret `QUOTA_SECRETS_TOKEN`. Il sauvegarde les
   renouvellements OAuth entre runners. Surveiller sa date d'expiration.
4. Vérifier la variable Actions `CODEX_WARM_MODEL` : défaut `gpt-5.6-sol`, modèle
   essayé par le projet de référence. Sa disponibilité et son effet sur le quota
   de ce compte restent à confirmer. Aucun modèle de secours automatique.

Ces secrets permettent d'agir avec les autorisations du compte : limiter l'accès
en écriture au dépôt et ne pas exécuter de code non relu avec ces secrets.
Le compte Plus et le compartiment `codex` de 300 minutes sont vérifiés. L'usage
inclus doit être autorisé ; les mécanismes de réserve ne sont pas activés.
Le backend et ses champs peuvent changer : une réponse inconnue bloque le test.

## Activation au créneau convenu

1. Prévoir un créneau sans usage Work/Codex autour de l'expiration et de l'envoi.
   Suspendre soi-même le rappel concurrent, par exemple celui de 21 h 25.
   Ce programme ne le suspend pas.
2. Lancer **Actions → Codex quota test → Run workflow → observe**, sans baseline.
   Ce mode lit le compte et n'envoie jamais de requête de modèle. Vérifier
   l'échéance UTC avec l'interface du compte. Le 19 octobre 2026, Paris = UTC+2.
3. Si l'observation est correcte, placer `QUOTA_TEST_ARMED=true`, puis lancer
   `test` avec la baseline fictive voulue. Les deux conditions sont nécessaires :
   variable vraie ET armement manuel. Ne pas relancer `test` : les passages
   programmés continuent le premier essai.
4. Le journal `Realigned` doit montrer le remplacement de l'échéance fictive.
   Aucun envoi tant que la fenêtre reste active.
5. Pour reprendre le même essai manuellement, utiliser `continue` sans baseline,
   jamais `test` une deuxième fois. Cela ne renouvelle pas les 24 heures ni le droit
   à un message. Si aucun événement `schedule` n'apparaît dans Actions, la cadence
   automatique n'est pas validée, même si le lancement manuel fonctionne.
6. Après l'essai, comparer `verified_reset`, dans `state.json` sur la branche
   `quota-test-state`, avec l'interface avant d'envoyer un autre message.
   L'échéance doit être environ cinq heures après l'envoi réel.
7. Remettre `QUOTA_TEST_ARMED=false`. Reprendre le rappel si le test n'est pas
   retenu. Le mode permanent viendra seulement après validation de cet essai.

## Protections et limites

- La branche `quota-test-state` conserve échéances UTC, empreinte du compte,
  statut et au plus 400 observations assainies : horaires des deux lectures,
  échéances, permission d'usage, phase et décision. `last_check_at` et
  `last_trigger` permettent de distinguer lancement manuel et passage programmé.
  Après envoi, elle conserve aussi le résultat CLI, l'heure de confirmation ou
  une cause d'échec générique. Aucun jeton, identifiant brut, erreur backend brute
  ou texte de réponse.
- Les nouvelles lectures après envoi ne sont jamais de nouveaux messages.
  Une mise à jour retardée ou temporairement ambiguë peut se stabiliser pendant
  les quatre contrôles. Un changement de compte ou une sauvegarde OAuth impossible
  bloque la suite. Sans confirmation, le statut reste bloquant et aucun deuxième
  envoi n'est tenté.
- Verrou global GitHub et relecture de l'état à chaque run. Une écriture impossible
  bloque l'envoi. `pending`, `unverified` et `complete` interdisent un nouvel essai,
  même après redémarrage ou lancement manuel.
- Pour réinitialiser : désactiver les passages, vérifier le compteur puis supprimer
  manuellement `state.json` sur la branche d'état. Ne pas effacer un statut
  incertain pour contourner le blocage.
- État inactif reconnu par une échéance passée ou une échéance glissante d'environ
  cinq heures sur deux lectures espacées. Cette représentation glissante reste
  à vérifier sur le compte. Une échéance future stable est active, même avec une
  jauge arrondie à 100 % restant.
- Un reset anticipé vers un état inactif démarre le délai à sa détection. Une
  échéance active modifiée est suivie. Aucune attribution automatique à une annonce.
- Pas d'email spécifique ajouté : activer les notifications d'échec Actions dans
  GitHub. Les statuts bloquants restent aussi visibles dans l'état.
- Les runners standard d'un dépôt public bénéficient normalement des minutes
  gratuites. En privé, les passages consomment l'allocation Actions : environ
  8 640 passages par mois à cinq minutes, avant retards et temps d'installation.
  Vérifier forfait et limites de dépenses avant une activation prolongée.
- Les tâches publiques peuvent être désactivées après 60 jours sans activité.
  Ce test de 24 heures n'a pas besoin de heartbeat.

## Tests locaux sans compte

```sh
python3 -m unittest discover -s tests -v
```

Les tests simulent recalage, démarrage récent, expiration, reset anticipé, usage
concurrent, erreurs, armement, reprise après crash et confirmation du compteur.
Ils ne prouvent pas l'effet d'un message sur le compte.

Client épinglé : `@openai/codex@0.159.2`. Pas de dépendance Python supplémentaire.
