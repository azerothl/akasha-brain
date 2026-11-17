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

## Routage et retrait du spécialiste Tâches

Le point d’entrée `python -m akasha_brain.tasks_routing` gère le routage SQL du seul banc `bench-tasks`. Il admet la v3 sur la qualification publiée, un objectif Tâches et un contrat de couverture lié aux fichiers du cas et à la consigne. Pour la v3, le schéma SQLite doit correspondre à celui du banc figé. Dans le bac, le filtre localisé doit aussi correspondre au contrat avant la génération.

Le registre local conserve la progression candidat, actif, déprécié puis retiré. Une proposition sans contrat compatible ou un spécialiste devenu invérifiable est dirigé vers la référence. Le registre journalise le retrait et chaque nouvel appel Tâches sélectionne alors la référence. La vérification rejoue « Terminées » à contrat identique dans deux bacs et exerce les parcours Notes et projet jetable pendant que la v3 est active.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.tasks_routing init --registry $registre
.\.venv\Scripts\python.exe -m akasha_brain.tasks_routing bind --case $cas --plan $plan --target $filtre --output $contrat
.\.venv\Scripts\python.exe -m akasha_brain.tasks_routing activate --registry $registre
.\.venv\Scripts\python.exe -m akasha_brain.tasks_routing run --registry $registre --case $cas --coverage $contrat `
    --runtime $pythonPortable --rbitnet $moteur $gguf $tokenizer --output $dossierEssai
.\.venv\Scripts\python.exe -m akasha_brain.tasks_routing retire --registry $registre
```

| État du registre | Graphe sélectionné sur « Terminées » | Verdict | Durée |
| --- | --- | --- | ---: |
| Actif | V3 | Premier diff accepté | 102,969 s |
| Retiré | Référence | Second diff accepté | 201,572 s |

Le premier diff de la référence a reproduit l’écart d’une ligne en trop. Le second a validé les trois filtres. SQLite est resté intact après chaque diff. Les deux décisions de routage et le retrait figurent dans le journal vérifié après réouverture du registre.

Pendant l’activation, Notes a passé les quatre tests, le vérificateur SQLite, puis RapidOCR et SQLite après relance. Le projet jetable a passé la validation isolée, le refus d’application sans accord et l’application avec accord. Les trois graphes Notes, le routage des autres familles et les sorties des gabarits de communication ont donné le même résultat à l’initialisation, à l’activation et après retrait. Les quatre bacs se sont arrêtés. [Relevé de routage et de retrait](../../bench/results/phase4-tasks-routing-v1.json)

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase4_tasks_routing --runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --output $dossierDeValidation
```

## Clôture

Les trois critères de sortie du [plan de développement](development-plan.md#phase-4--spécialistes) sont vérifiés sur le banc local. Le spécialiste v3 obtient 2/2 au premier diff et 2/2 au total sur les deux cas réservés, avec un contrat de couverture par cas. La référence obtient 0/2 au premier diff et 1/2 au total. Notes code et bureau, le parcours projet jetable et les contrôles de routage et de gabarits de communication ont passé la non-régression. Le retrait exercé dans un registre jetable a rétabli la référence, qui a corrigé « Terminées » après reprise.

Le [jalon de routage et de retrait](https://github.com/azerothl/akasha-brain/commit/8ff927000d0186dc59455a3292b296c69ee0c786) clôt ce volet. Le pilote Path A ci-dessous complète la qualification de phase 4 avant la [phase 5](phase5_status.md).

## Porte de décision Tâches avec akasha-model 0.3.0

La roue PyPI MIT a été téléchargée par le parcours unitaire avec empreinte approuvée. La publication PyPI lie la roue au dépôt `azerothl/akasha-model` et à la révision `d56c145e72bf871744053bb501d793a78f92fdf8`. Son SHA-256 est `c32a19ac01d26203a5a117bd67649dd442daa6695ccbc96aa983537b62cc188f`. La roue universelle est vérifiée et installée dans le répertoire temporaire du bac, avec l’entrée en lecture seule et le réseau désactivé. [Roue et attestation PyPI](https://pypi.org/project/akasha-model/#akasha_model-0.3.0-py3-none-any.whl)

Le chemin `tasks_routing run --gate-request $demande` est activable explicitement. Le système hôte prépare la proposition et les signaux typés. Le Path A applique une seule évaluation `Choice`, `Score`, `Noul` pour l’appel réel. Un dossier Tâches admis porte une proposition certaine et des attestations booléennes. Les seuils exacts de 1 sur ces signaux et le niveau de risque R1 sont des règles de ce pilote. Après `ready`, le système hôte revérifie le GoalSpec, la qualification, le contrat et le registre avant d’exécuter le graphe proposé.

La matrice compare les deux politiques sur douze cas identiques, avec un verdict attendu fixé par cas. Elle inclut l’ambiguïté, le budget épuisé, le périmètre de risque, l’autorisation et la confirmation. Les temps de décision sont des médianes de moyennes par cas, avec cinquante répétitions et une résolution de 0,1 µs. Les deux politiques donnent 12/12, avec zéro faux `ready`, `abstain` ou `blocked`. Les médianes mesurées dans le bac sont de 0,2 µs pour la politique déterministe et de 20,35 µs pour le Path A.

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase4_tasks_gate --runtime $pythonPortable `
    --gate-request $demande --rbitnet $moteur $gguf $tokenizer --output $dossierDeValidation
```

Les deux bras ont rejoué « Terminées » avec la même consigne et le même contrat, en gardant la démarche hors évolution. Le routage déterministe termine en 98,958 s. Avec Path A, le total est de 124,933 s, dont 21,760 s pour le bac de la porte. Les deux bras passent Git, les trois filtres et SQLite dès le premier diff. L’écart de 25,975 s correspond à cette paire de rejeux.

Notes code et bureau a passé les quatre tests, RapidOCR et SQLite après relance. Le parcours projet jetable a confirmé le refus sans accord et l’application après accord. Les plans Notes et les contrôles de routage et de gabarits de communication donnent les mêmes résultats avant et après la campagne. Les six bacs se sont arrêtés et la chaîne d’audit du registre a été revérifiée.

Le choix par défaut est déterministe. Le Path A est disponible par option pour l’évaluation, avec un score égal sur la matrice et un temps total supérieur sur le rejeu apparié. [Relevé comparatif et non-régression](../../bench/results/phase4-tasks-gate-v1.json)
