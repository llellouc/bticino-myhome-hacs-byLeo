# Assistant IA - Contexte repo BTicino MyHome

Ce fichier complete les instructions globales du workspace.
Priorite ici: maintenance et evolution du fork BTicino MyHome pour Home Assistant.

## Repo cible
- Fork principal: llellouc/bticino-myhome-hacs-integration
- Integration HA: custom_components/bticino_myhome

## Contexte technique cle
- Gateway cible principale: BTicino F454 (192.168.0.91:20000)
- Protocole: OpenWebNet / OWNd
- Correctif historique important deja applique:
  - probleme: AttributeError: 'NoneType' object has no attribute 'write'
  - correction attendue: reconnexion/retry propre quand le stream writer est perdu
- Version manifeste du fork: 1.0.1 (README + manifest alignes)

## Objectifs sur ce repo
1. Fiabilite runtime (sessions commandes/events, reconnect, timeout, erreurs reseau).
2. Evolutions capteurs sans regressions (power, energy, water, power_energy, unit_scale).
3. UX panel de config/discovery claire, coherente, avec actions surees (ex: import protege).
4. Compatibilite Home Assistant + HACS

## Regles de changement
- Privilegier les patchs minimaux et lisibles.
- Eviter les refactors massifs sans gain clair.
- Garder la compatibilite de config existante (migrations douces).
- Preserver la compatibilite avec les autres modules BTicino MyHome deja utilises dans l'installation.
- Ne pas decouper un fichier uniquement pour la taille; decouper seulement si la cohesion fonctionnelle s'ameliore vraiment.
- Prioriser des extractions progressives a faible risque (helpers, builders, handlers) plutot qu'un grand refactor en une fois.
- Pour tout decoupage: documenter le gain attendu (lisibilite/testabilite/maintenance), la verification rapide, et le rollback.
- Pour les changements sensibles:
  - expliciter impacts
  - proposer verification rapide
  - proposer rollback

## Maintenance des instructions IA
- Tenir ce fichier a jour quand les demandes modifient les objectifs, les contraintes, la roadmap ou les pratiques de livraison sur ce repo.
- Lors de changements importants (nouveau flux, nouvelle regle, nouveau standard), proposer ou appliquer la mise a jour de ce fichier dans la meme session.
- Garder ce fichier aligne avec le fichier global et supprimer les consignes obsoletes.

## Qualite attendue avant livraison
- Pas d'erreurs syntaxe/lint sur fichiers modifies.
- Verification du flux principal touche (ex: discovery, import, creation capteur).
- Pour les changements lies aux devices (lumieres, volets, energy, water, climate, etc.), privilegier un test local concret du flux impacte quand l'environnement le permet.
- Si un test local complet n'est pas possible, expliciter ce qui a ete verifie et le risque residuel.
- Message de commit explicite et oriente impact utilisateur.

### Protection des appels HA (obligatoire)
- Tout appel Home Assistant/Recorder potentiellement rejetable doit etre protege par:
  - validation prealable des parametres/metadonnees (ex: statistic_id, source, unit_class, timestamps)
  - gestion d'erreur explicite (type + message) sans echec silencieux
  - remontée visible dans la reponse API ou les logs (jamais ignorer une exception)
- Les acces Recorder potentiellement bloquants (lectures DB, statistics_during_period, etc.) doivent passer via executor (async_add_executor_job).
- Dans les vues web, privilegier des wrappers safe dedies pour les appels storage/reload/Recorder afin d'uniformiser les erreurs HTTP renvoyees.
- En cas de file d'attente Recorder asynchrone, la reponse doit expliciter ce qui est:
  - valide/rejete immediatement
  - seulement enqueue (non confirme en base a ce stade)

### Gate de validation minimale (obligatoire avant annonce "pret a tester")
- Si deplacement de modules/fichiers Python:
  - verifier tous les imports residuels (pas seulement les fichiers modifies directement)
  - inclure explicitement les modules transverses critiques dans la verification (ex: gateway.py, __init__.py, web.py, config_flow.py)
- Toujours lancer une compilation Python sur:
  - fichiers modifies
  - fichiers dependants critiques connus (au minimum gateway.py + __init__.py pour cette integration)
- Pour les refactors de structure (nouveaux sous-packages devices/helpers):
  - verifier qu'il n'existe plus d'imports vers les anciens chemins
  - verifier la coherence des imports relatifs depuis chaque sous-package
- Si l'environnement local ne contient pas Home Assistant:
  - ne pas presenter un "import smoke test" comme validation fonctionnelle
  - documenter explicitement la limite et fournir le test runtime HA cible

### Process operatoire obligatoire (avant tout message "pret a tester")
- Etape 1: verification structurelle imports
  - rechercher les imports orphelins/residuels suite aux moves
  - verifier les modules transverses qui importent des entities/devices (priorite: gateway.py)
- Etape 2: compilation elargie
  - compiler les fichiers modifies ET les points d'entree critiques (__init__.py, gateway.py, web.py, config_flow.py)
- Etape 3: verification setup/unload des plateformes
  - verifier que les chemins de plateformes forwardes sont coherents avec la structure reelle des modules
  - verifier setup ET unload (pas uniquement setup)
- Etape 4: evidence minimale a fournir dans la reponse
  - lister exactement ce qui a ete verifie
  - lister ce qui n'est PAS verifiable hors runtime HA
  - fournir le test runtime HA cible (logs + action UI)

### Regle de blocage
- Si une etape du process obligatoire n'est pas executee, ne pas annoncer "pret a tester".
- En cas d'incertitude sur un import transverses, traiter comme bloquant jusqu'a verification explicite.

## Format de reponse attendu
- Commencer par la conclusion/diagnostic.
- Ensuite actions concretes, etapes courtes, verifiables.
- Rester pragmatique et oriente production.
