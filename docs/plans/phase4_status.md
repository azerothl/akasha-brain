# Phase 4 — Spécialistes

La branche `codex/phase-4` part de `9a74231`, le jalon publié de [clôture de la phase 3](phase3_status.md#clôture).

## Mesure d’entrée sur la réparation SQL Tâches

Le premier candidat envisagé concerne la réparation d’une clause de filtre SQLite lorsqu’une consigne combine plusieurs règles de sélection ou d’ordre. La référence est le graphe `tasks-rbitnet-sql@1.3.0`, avec le [gel SQL v4](../../akasha_brain/protocols/tasks-rbitnet-sql-v4.json) et Qwen3-8B-Q4_K_M sur Rbitnet CPU. Le corpus de développement comporte deux cas synthétiques neufs, « À faire » avec des conditions de report et d’affectation, et « Toutes » avec des groupes de tri dépendant de l’état et de l’échéance. [Corpus de développement](../../bench/phase4_tasks_dev/cases.json)

Chaque cas part d’un seul filtre incorrect. La référence indépendante en Python doit satisfaire les trois listes attendues avant l’inférence. Rbitnet génère le diff sur le CPU de l’hôte. Git, la comparaison des listes visibles et la vérification SQLite tournent dans le bac. Le modèle reçoit la consigne, le DDL et le module. Les états synthétiques et les listes attendues servent au contrôle. Les variantes réservées de la phase 1 restent hors du corpus de développement et les deux cas ne déclenchent aucune évolution automatique.

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase4_tasks_baseline --runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --output $dossierEssai
```

| Cas | Premier diff | Reprise | Temps total |
| --- | --- | --- | ---: |
| « À faire », affectation et report | 2 lignes manquantes, 3 en trop | 2 lignes en trop | 289,245 s |
| « Toutes », groupes de tri | Ordre incorrect | 2 lignes manquantes | 299,979 s |

Les deux témoins ont réussi sur les trois filtres. Les quatre diffs ont passé le contrôle Git et la vérification d’empreinte. Les filtres hors cible et SQLite sont restés intacts. Score du graphe de référence de **0/2 au premier diff et 0/2 après reprise**. Les temps courent jusqu’à l’arrêt de chaque bac. [Relevé CPU](../../bench/results/phase4-tasks-baseline-v1.json)

## GapReport initial — Traduction des règles de sélection et de tri

La lacune se répète lorsque la consigne combine plusieurs règles sur une clause. Dans « À faire », le premier diff applique la date limite de report aussi à l’échéance. La reprise restaure la condition d’état ouvert et laisse passer deux tâches à cause de la condition d’affectation et de priorité omise. Dans « Toutes », le premier diff conserve toutes les lignes mais omet le classement par groupes. La reprise ajoute un classement des tâches ouvertes et écarte les deux lignes non ouvertes. Le graphe disposait du DDL et du module. Les témoins, Git et l’intégrité SQLite permettent d’attribuer les écarts aux clauses produites sur ces deux cas.

Le candidat à évaluer séparera les prédicats de sélection, le tri et le traitement des valeurs nulles dans un contrat de sortie vérifiable. Une conversion déterministe peut alors produire la clause. Ce candidat et l’éventuel recours à un modèle préentraîné restent à comparer. Le [plan de développement](development-plan.md#phase-4--spécialistes) prévoit une mesure sur un corpus réservé neuf, avec le même graphe de référence et les mêmes vérificateurs. Les mesures distingueront le premier diff, les reprises, le verdict final, le temps et les régressions des autres familles. Le périmètre reste l’édition de la seule clause visée et l’exécution confinée. Le retour arrière retirera la compétence du routage actif.

Le premier périmètre utilise des scénarios synthétiques. Les poids, la licence et la provenance d’un éventuel modèle préentraîné seront vérifiés avant intégration. Pour toute version affinée sur des données utilisateur, un accord distinct et la filiation de chaque jeu jusqu’aux versions et dérivés sont des conditions d’entrée. Le mécanisme retenu en cas d’effacement non démontrable est le retrait de chaque version concernée, avec blocage du chargement, du routage et de la réactivation après restauration. Ce mécanisme devra être vérifié avant d’admettre un tel entraînement.

## Spécialiste SQL structuré v1

Le graphe candidat `tasks-rbitnet-sql-structured@1.0.0` demande à Qwen3-8B-Q4_K_M un objet JSON avec `where` et `order`. Le compilateur valide les opérateurs, les colonnes issues du DDL, les groupes ordonnés et le placement explicite des `NULL`. Il produit la clause SQLite avec parenthèses et échappement des littéraux. Le générateur de diff du graphe de référence remplace le seul littéral du filtre en échec.

La comparaison réutilise les mesures CPU archivées de la référence. Le lanceur contrôle les empreintes des cas, du gel et des résultats de référence. Le candidat conserve la graine 742, huit threads, un plafond d’admission de 8 192 Mio et 144 jetons par tentative, avec au plus deux tentatives. Chaque exécution du candidat ouvre un bac neuf et rejoue le même témoin et le même contrôle indépendant des trois filtres et de SQLite.

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase4_tasks_specialist --runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --output $dossierEssai
```

| Cas | Premier contrôle de la référence | Premier contrôle du spécialiste | Reprise de la référence | Reprise du spécialiste | Total référence | Total spécialiste |
| --- | --- | --- | --- | --- | ---: | ---: |
| À faire | 2 manquantes, 3 en trop | 2 manquantes, 3 en trop | 2 en trop | 4 en trop | 289,245 s | 251,864 s |
| Toutes | Ordre incorrect | Ordre incorrect | 2 manquantes | Diff identique refusé | 299,979 s | 358,792 s |

Les deux graphes obtiennent **0/2 au premier diff et 0/2 après reprise**. Les trois diffs distincts du spécialiste s’appliquent avec Git. Les contrôles confirment l’intégrité de SQLite et des filtres hors cible. Sur « À faire », les plans compilés omettent la restriction aux tâches ouvertes et n’encodent pas la condition d’affectation attendue. Sur « Toutes », les plans placent les échéances nulles en dernier et omettent les groupes de tri.

La première exécution du spécialiste sur « À faire » atteint le délai HTTP de 160 s et s’arrête après 265,814 s. Le tableau retient le rejeu en bac neuf avec un délai HTTP de 300 s et le même plafond de 144 jetons. Le relevé conserve les deux exécutions et les mesures de référence archivées. [Relevé comparatif](../../bench/results/phase4-tasks-specialist-v1.json)

## Spécialiste SQL structuré v2

La v2 vérifie le plan JSON avant de compiler la clause SQLite. Un contrat séparé, rédigé à partir de chacune des deux consignes et lié à son empreinte, fixe les prédicats et leurs branches, l’ordre des groupes, les clés de tri et le placement explicite des `NULL`. Le contrôle normalise l’ordre et l’imbrication des termes d’un même opérateur `AND` ou `OR`. Un écart arrête la tentative avant compilation et fournit un retour à la reprise.

Rbitnet reçoit le résumé des exigences du contrat. Le contrôle indépendant des listes visibles et de SQLite reste dans Windows Sandbox. Il vérifie chaque diff compilé et appliqué. Les mesures v1 archivées et les nouveaux essais v2 utilisent les mêmes cas et poids, la graine 742, huit threads, 8 192 Mio et 144 jetons par tentative. La v2 utilise un délai HTTP de 300 s dès le départ.

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase4_tasks_specialist --v2 --runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --output $dossierEssai
```

| Cas | Temps v1 | Temps v2 | Écart v2 − v1 | Tentatives v2 |
| --- | ---: | ---: | ---: | --- |
| À faire | 251,864 s | 185,346 s | −66,518 s | Prédicat mal formé, puis JSON invalide |
| Toutes | 358,792 s | 183,096 s | −175,696 s | Deux réponses JSON invalides |

Les scores sont de **0/2 au premier diff et 0/2 après reprise**, pour les deux versions. La v1 avait appliqué trois diffs erronés dans les bacs. La v2 a arrêté les quatre propositions avant compilation. Une proposition a échoué au contrôle des prédicats et trois au décodage JSON. Les temps vont jusqu’à la fermeture du bac et mesurent ici des parcours en échec.

Le contrôle local a aussi rejeté les quatre plans archivés de la v1. Les tests ciblés vérifient que le compilateur reste hors d’atteinte quand une condition manque, qu’un groupe change de priorité ou qu’un placement de `NULL` est incorrect. [Relevé comparatif v2](../../bench/results/phase4-tasks-specialist-v2.json)

## Spécialiste SQL structuré v3

La v3 demande un objet JSON plat avec trois chaînes, `where`, `groups` et `order`. Le modèle combine des conditions atomiques nommées par des lettres. Le banc tire ces conditions et le résumé de sélection et de tri du contrat v2 de chaque cas. Le parseur accepte une accolade terminale excédentaire après un objet complet, avec une trace dans le rapport. L’expansion des chaînes produit le plan soumis à la même garde de couverture avant compilation.

La comparaison réutilise le relevé v2 et conserve les cas, les contrats, les poids, les paramètres Rbitnet et les vérificateurs. Chaque essai v3 s’exécute dans un bac neuf avec deux tentatives au maximum. Le contrôle indépendant valide les trois listes visibles et l’intégrité de SQLite après l’application de chaque diff.

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase4_tasks_specialist --v3 --runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --output $dossierEssai
```

| Cas | Temps v2 | Temps v3 | Écart v3 − v2 | Verdict v3 |
| --- | ---: | ---: | ---: | --- |
| À faire | 185,346 s | 101,421 s | −83,925 s | Réussi au premier diff |
| Toutes | 183,096 s | 96,436 s | −86,660 s | Réussi au premier diff |

Le score au premier diff passe de **0/2 à 2/2**. Le score final passe aussi de **0/2 à 2/2**. Les deux réponses v3 sont des objets JSON valides dès l’émission. La garde a admis les deux plans avant compilation, puis les deux diffs ont passé Git, les trois filtres et le contrôle SQLite. Les bacs se sont arrêtés. La tolérance d’une accolade terminale excédentaire est vérifiée par les tests ciblés.

Les temps couvrent l’exécution jusqu’à l’arrêt du bac. La v2 a clos deux parcours en échec après deux tentatives chacun. La v3 a clos deux parcours réussis en une tentative chacun. Les deux cas utilisent leurs contrats de développement. [Relevé comparatif v3](../../bench/results/phase4-tasks-specialist-v3.json)

## V3 figée sur deux cas réservés

Le [manifeste de gel](../../akasha_brain/protocols/tasks-sql-specialist-v3.json) fixe la v3 validée sur les cas de développement et la référence `tasks-rbitnet-sql@1.3.0`. Les deux cas réservés ont été créés après ce gel. « Terminées » vérifie une sélection avec une exception pour les échéances absentes et un tri avec les `NULL` en premier. « Toutes » vérifie trois groupes et deux règles de placement des `NULL`. L’ordre est référence puis v3 pour « Terminées », v3 puis référence pour « Toutes ». [Corpus réservé](../../bench/phase4_tasks_reserved/cases.json)

Les deux graphes reçoivent la même consigne. Le spécialiste reçoit aussi le contrat de couverture rédigé à partir de cette consigne. Le témoin Python indépendant utilise les données synthétiques et des listes attendues tenues à part de la génération. Le vérificateur actionne les trois filtres, compare les identifiants et titres visibles dans leur ordre et contrôle les lignes, l’empreinte et l’intégrité de SQLite après chaque filtre.

Chaque réexécution ouvre un bac neuf avec les mêmes poids, la graine 742, huit threads, 8 192 Mio et 144 jetons par tentative. Le délai HTTP est de 160 s pour la référence et de 300 s pour la v3. Les rapports sont marqués `evolution: excluded`.

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase4_tasks_reserved run --runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --output $dossierEssai
```

| Cas | Verdict référence | Temps référence | Verdict v3 | Temps v3 | Écart v3 − référence |
| --- | --- | ---: | --- | ---: | ---: |
| Terminées | Réussi après reprise | 189,195 s | Réussi au premier diff | 96,667 s | −92,528 s |
| Toutes | Échec après reprise | 192,297 s | Réussi au premier diff | 100,824 s | −91,473 s |

La référence obtient **0/2 au premier diff et 1/2 en fin de parcours**. Le premier diff « Terminées » laisse une ligne en trop, corrigée à la reprise. Les deux diffs « Toutes » omettent respectivement deux et trois lignes. La v3 obtient **2/2 au premier diff et 2/2 en fin de parcours**.

Les six diffs se sont appliqués avec Git et ont passé le contrôle d’empreinte. Les filtres hors cible et SQLite ont été vérifiés sur chaque diff. Les deux diffs v3 ont franchi la garde de couverture et passé les trois filtres. Les quatre bacs ont été arrêtés. Les temps incluent le démarrage et l’arrêt des bacs. [Relevé comparatif réservé](../../bench/results/phase4-tasks-reserved-v1.json)
