# Import d'historique d'énergie/eau — architecture et décisions

Ce document complète `agents/AGENTS.md`. Il décrit spécifiquement la
fonctionnalité d'import d'historique (`MyHOMEImportDailyEnergyHistoryView`,
dans `custom_components/bticino_myhome/web.py`), les choix de conception
retenus, et pourquoi les alternatives ont été écartées. À lire avant toute
modification de cette fonctionnalité.

## 1. Pourquoi cette fonctionnalité existe

Home Assistant compile ses statistiques horaires à partir de l'historique
d'état des entités. Si l'intégration démarre alors que le compteur BTicino
tourne déjà depuis des mois/années, HA n'a aucune statistique pour cette
période : les graphiques Énergie affichent un trou. La centrale (F454 ou
équivalent OpenWebNet) conserve elle-même un historique de consommation
(jusqu'à ~2 ans en journalier, ~12 mois en horaire) — cette fonctionnalité
va chercher cet historique et l'injecte dans le Recorder de HA comme
statistiques externes/internes, pour combler ce trou une fois, à la demande
(bouton dans le panel de configuration), pas en fonctionnement continu.

## 2. Ce que le protocole OWN fournit réellement

Vérifié empiriquement par sondage direct d'une F454 réelle (connexion
directe au protocole OWN, comparaison des trames brutes) :

- **Dimension 513/514** (`*18*59#<mois>*<where>##` pour l'année en cours,
  `*18*510#<mois>*<where>##` pour il y a 1-2 ans) : une valeur par jour du
  mois, keyée uniquement par jour (pas d'année dans la trame). Conservé
  environ 2 ans en arrière par la centrale.
- **Dimension 511** (`*#18*<where>*511#<mois>#<jour>##`) : 24 valeurs pour un
  jour donné, une par heure locale (index 1 = 00h-01h ... index 24 =
  23h-00h), plus un index 25 = total du jour. Pas d'année dans la trame non
  plus → utilisable seulement sur les ~12 derniers mois.
- **Les deux dimensions sont des deltas de consommation**, pas des relevés de
  compteur ("aujourd'hui le compteur affichait X"). Confirmé par test direct :
  la somme des 24 valeurs horaires d'un jour est exactement égale à la valeur
  journalière du même jour, sur plusieurs jours testés.
- La F454 **n'expose jamais** son compteur total tel qu'il était à une date
  passée — seulement son compteur total *actuel* (dimension 51, live) et des
  deltas de consommation passés. Toute reconstruction d'un historique de
  "valeur de compteur" pour le passé est donc nécessairement une
  reconstruction, jamais une lecture directe.

## 3. Pourquoi un mode hybride journalier/horaire (et pas l'un ou l'autre)

- Import **journalier uniquement** (design initial) : un seul point par jour,
  posé à la fin de la journée locale. Fonctionne, mais un point unique par
  jour ne peut jamais s'aligner avec le découpage horaire que HA utilise pour
  ses vraies statistiques — dès qu'il existe des statistiques réelles
  adjacentes (capteur live), on obtient un "pic" ou un "trou" artificiel à la
  jonction (voir section 6).
- Import **horaire uniquement** : aligné exactement sur les buckets HA, donc
  pas de pic — mais la centrale ne garde le détail horaire que ~12 mois, donc
  impossible de couvrir 2 ans d'historique.
- **Décision retenue : hybride.** Détail horaire (dimension 511) sur la
  fenêtre récente où il est disponible (`hourly_days_back`, plafonné à 365
  jours), et repli sur un point journalier unique (dimension 513/514) pour le
  reste de la fenêtre demandée (`months_back`, jusqu'à 24 mois). Le choix se
  fait jour par jour selon la disponibilité réelle des données, pas par une
  coupure de calendrier fixe.
- Compromis assumé : la précision horaire n'est disponible que sur la partie
  récente de l'historique ; les jours plus anciens restent un point unique
  par jour, avec le risque de micro-écart résiduel que ce point unique
  implique s'il existe déjà des statistiques réelles adjacentes à ce jour-là
  (rare, car au-delà de 12 mois il n'y a généralement pas encore eu de suivi
  live).

## 4. Fenêtre de temps (`months_back`, `_iter_recent_months`)

La fenêtre de la centrale est une durée glissante ancrée sur "aujourd'hui"
(ex. jour J moins 2 ans), pas une liste de mois calendaires. `_iter_recent_months`
(dans `gateway.py`) calcule donc le cutoff avec `dateutil.relativedelta`
(`date.today() - relativedelta(months=N)`), puis énumère les mois calendaires
touchés par cette fenêtre. Une implémentation antérieure comptait N mois en
partant du mois courant (compté comme un mois plein alors qu'il est
généralement partiel), ce qui perdait systématiquement le mois le plus
ancien de la fenêtre réelle — corrigé par le calcul par durée ci-dessus.
`months_back=24` couvre donc bien la totalité des ~2 ans conservés par la
centrale.

## 5. Reconstruction du cumul (`sum_alignment_offset`)

HA stocke les statistiques d'un capteur `total_increasing`/`sum` sous forme
de valeurs cumulatives croissantes, pas de deltas. Comme la centrale ne
fournit que des deltas (section 2), l'import doit reconstruire un cumul
plausible :

1. **Cumul relatif** : les deltas importés (jour ou heure) sont additionnés
   les uns après les autres (`running_imported_total`), en partant
   arbitrairement de 0 — ce cumul relatif n'a de sens qu'entre les points
   importés eux-mêmes, pas en valeur absolue.
2. **Ancrage** (`sum_alignment_offset`) : une constante ajoutée à tout le
   cumul relatif pour le recaler sur la réalité. Recherchée dans cet ordre :
   - **Chevauchement avec de vraies statistiques existantes** : si des jours
     de la fenêtre importée ont déjà de vraies statistiques horaires en base
     (capteur live qui tournait déjà), on compare notre delta reconstruit à
     la valeur réelle de ces mêmes jours ; l'écart (valeur réelle − cumul
     relatif) de chaque jour "proche" (± 10 %, `_is_close_daily_value`)
     devient un candidat d'ancrage, et on prend la **médiane** des candidats
     (résiste mieux qu'une moyenne à un jour aberrant, ex. jour où le suivi
     live vient de démarrer en cours de journée).
   - **Premier point réel après la fenêtre importée**, si aucun chevauchement
     fiable n'existe : on ancre pour que le dernier point importé se
     raccorde exactement à ce premier point réel.
   - **Valeur live actuelle du capteur**, en dernier recours (aucune
     statistique nulle part, première utilisation) : on recule depuis
     "compteur maintenant" moins tout ce qu'on vient d'importer.
3. **Limite assumée** : l'ancrage est une **constante unique** appliquée à
   toute la fenêtre importée. Si le compteur physique a été remplacé/reseté
   entre l'ancrage et une partie lointaine de la fenêtre, ou si l'écart réel
   variait dans le temps, l'algo ne le détecte pas — il part de l'hypothèse
   que l'écart entre cumul relatif et vrai compteur est constant sur toute la
   période importée. Pas de garde-fou spécifique contre ce cas à ce jour.

## 6. Bug historique : le "pic" nocturne et comment il a été corrigé

Symptôme observé : un pic de consommation isolé, suivi d'un creux, sur les
graphiques Énergie, autour du changement de jour. Cause racine : le point
journalier était posé au début du jour D (au lieu de la fin) et en UTC
(au lieu de l'heure locale) — la centrale renvoie ses données en heure
**locale**, pas en UTC, et le code ne convertissait pas correctement.
Corrigé via `_day_end_utc(day, tz)`, qui place le point à la fin du jour
local converti en UTC via le fuseau de `hass.config.time_zone`. Le mode
hybride horaire (section 3) élimine la quasi-totalité du problème à la
racine sur les 12 derniers mois.

## 7. Garde-fou anti-collision (`dont_override_hourly`, "don't override")

Le flag payload s'appelle `dont_override_hourly` (coché par défaut) : quand
actif, l'import ne réécrit jamais un point dont l'horodatage exact coïncide
avec une vraie statistique déjà en base (capteur live qui a déjà tourné à ce
moment précis) — vérification précise à l'heure près
(`occupied_starts`/`_load_hourly_daily_totals`), pas seulement au jour près.
Décoché, l'import écrase tout sans distinction (ancien comportement, gardé
disponible pour les cas de correction volontaire d'un historique déjà
importé/faux).

## 8. Vérification de persistance après import (`_persisted_statistics_count`)

`async_import_statistics`/`async_add_external_statistics` de HA sont des
`@callback` fire-and-forget : ils empilent une tâche dans la queue interne
du thread Recorder et retournent immédiatement, sans aucun moyen natif
d'attendre un accusé de réception par ligne. Si l'écriture échoue
temporairement (base occupée), la tâche se **replace elle-même** en fin de
queue indéfiniment jusqu'à réussir.

En conséquence, l'import ne peut vérifier son propre succès qu'en relisant
ensuite les statistiques réellement présentes en base et en les comparant à
ce qui a été envoyé. Un nombre fixe de cycles de vidage
(`async_block_till_done()`) ne garantit jamais totalement l'absence de faux
négatif (une tâche peut toujours se re-mettre en queue juste après le
dernier cycle) et échoue plus facilement sur un gros import (des centaines
à ~1300+ lignes) sous charge. La vérification utilise donc un **backoff
exponentiel** (1s, 2s, 4s, ... jusqu'à un budget cumulé de 30s), en
re-vidant et re-vérifiant à chaque palier, jusqu'à ce que toutes les lignes
matchent ou que le budget soit épuisé.

## 9. Fichiers concernés

- `custom_components/bticino_myhome/web.py` — vue HTTP d'import
  (`MyHOMEImportDailyEnergyHistoryView`), reconstruction du cumul, garde-fou
  de collision, vérification de persistance.
- `custom_components/bticino_myhome/gateway.py` — récupération des données
  brutes depuis la centrale (`fetch_daily_history`, `fetch_hourly_history`,
  `_iter_recent_months`).
- `custom_components/bticino_myhome/OWNd/message.py` — parsing des trames
  OpenWebNet (dimensions 51/511/513/514), vendored, non modifié pour cette
  fonctionnalité.
- `custom_components/bticino_myhome/frontend/panel/{events.js,api.js,modals/import_modal.js}`
  — UI du panel de configuration (déclenchement de l'import, options
  `months_back`, `use_hourly_detail`, `dont_override_hourly`, etc.).
- `tests/test_daily_history_import.py`, `tests/conftest.py` — suite de tests
  (exécutée via `tests/run.sh`, environnement Docker avec HA installé,
  nécessaire car HA n'est pas installable simplement en local).

## 10. Ce qui reste hors périmètre de cette fonctionnalité

- Le léger décalage du capteur **live** (totalisateur dimension 51) est une
  limite matérielle de la centrale (registre mis à jour peu fréquemment), pas
  un bug de l'intégration. Aucune correction de code n'est prévue pour ce
  point ; décision prise avec l'utilisateur de s'appuyer sur l'import
  (fiable) pour l'historique plutôt que de complexifier le suivi live.
