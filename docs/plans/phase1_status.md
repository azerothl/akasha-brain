# Phase 1 — Parcours bureau, code et évolution bornée

La phase 1 démarre sur le banc Notes CPU validé en
[phase 0](phase0_status.md). Le premier jalon compile l'objectif structuré
du banc en un graphe versionné. La cible est la baseline fixe exécutée
dans Windows Sandbox pendant la phase 0.

## Registre et compilation

Le [registre initial](../../akasha_brain/capabilities.json) épingle
les capacités par identifiant et version. Un relevé d'évaluation lie
la capacité au banc vérifié. L'OCR du formulaire est évalué sur
le parcours bureau Notes décrit ci-dessous.

Le compilateur valide le `GoalSpec`, les manifestes, la portée du
banc et les permissions déclarées. Il associe les étapes de localisation,
de préparation de la référence et de vérification dans le graphe
`notes-baseline@1.0.0`. Le plan cible le bac Windows et prévoit quatre
tests réussis ainsi que la vérification SQLite indépendante. Une cible,
une condition ou une capacité hors du périmètre évalué produit une
erreur typée.

## Rejouer

Depuis la racine avec la venv du projet.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain capabilities
.\.venv\Scripts\python.exe -m akasha_brain compile contracts/examples/goal_notes_regression.json
.\.venv\Scripts\python.exe -m pytest tests contracts -q
```

Le lancement initial a compilé les trois étapes et refusé le
`GoalSpec` de transfert. Les **63 tests** du parcours et des
contrats passent.

## Exécution dans Windows Sandbox

Le lanceur utilise le profil durci nominal et un bac neuf.
Avant les étapes, l'invité a lu le témoin, refusé sa réouverture en
écriture et refusé la création d'un fichier dans le montage. L'écriture
dans le répertoire temporaire invité a réussi. La sonde ne détecte
ni route par défaut, ni caméra, ni capture audio active, ni imprimante
redirigée. Les empreintes des fichiers du banc hôte concordent avant
et après. Le lanceur a arrêté son bac en fin de run.

Le même contrôle hors modèle a refusé deux demandes R1, l'une sans
preuve de confinement et l'autre hors du périmètre du `GoalSpec`.
L'identité du bac et l'action autorisée ont été vérifiées avant
chacune des trois étapes.

| Étape | Temps mur | Trace du 15 novembre |
| --- | ---: | --- |
| Localiser | 11,917 s | Témoin fautif, 2/4 tests réussis et 2 échecs attendus. |
| Préparer la référence | 2,272 s | Copie stockée dans le bac et empreinte vérifiée. |
| Vérifier | 5,291 s | 4/4 tests sans saut, vérificateur SQLite au vert. |

**Temps mur total 36,578 s**, préparation et arrêt du bac compris.

- `test_saved_note_survives_restart` réussi.
- `test_two_notes_with_accents_multiline_survive_restart` réussi.
- `test_save_acknowledged_in_session` réussi.
- `test_select_redisplays_content` réussi.
- Vérificateur SQLite indépendant réussi, code de sortie `0`.

Deux reprises ont corrigé la capture de sortie de la CLI Windows
Sandbox et la lecture du tableau JSON des noms de tests sous Windows
PowerShell 5.1. La trace ci-dessus provient du troisième bac.
Le rapport local est `phase1-notes-graph/run-3/report.json` dans le
dossier de preuves du banc.

Pour rejouer, affecter à `$pythonPortable` le répertoire du Python
portable du banc et à `$dossierRapport` un nouveau répertoire de
sortie. Le lanceur requiert un emplacement Windows Sandbox libre.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain run contracts/examples/goal_notes_regression.json `
    --python-runtime $pythonPortable --output $dossierRapport
```

## Réparation du graphe par Rbitnet CPU

Le graphe `notes-rbitnet@1.0.0` réutilise la localisation et les
vérifications de la baseline. Le nœud de réparation démarre Rbitnet
sur le loopback avec Qwen3-8B Q4_K_M et les empreintes du
[protocole évalué](../../bench/guided_repair_protocol.md). Le modèle
reçoit la méthode fautive et le lanceur convertit sa proposition en
un diff limité à `save_note`. Le bac reçoit la version fautive et
le diff en lecture seule.

Dans le bac, Git contrôle le diff et l'applique sur une copie
jetable. Le lanceur vérifie l'empreinte du fichier résultant avant
de lancer les quatre tests et le vérificateur SQLite. Une seconde
proposition peut utiliser le résultat de la première validation.

Pour ce parcours, fournir aussi les chemins des trois artefacts
Rbitnet évalués.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain run contracts/examples/goal_notes_regression.json `
    --python-runtime $pythonPortable --output $dossierRapport `
    --rbitnet $rbitnetExe $gguf $tokenizer
```

### Comparaison avec la baseline fixe

Les deux parcours ont utilisé le même hôte, le même profil Windows
Sandbox, le même Python portable et les mêmes fixtures. Chaque bac a
été créé pour son run et arrêté à la fin. Le chronomètre inclut la
préparation des entrées, les contrôles, l'exécution et l'arrêt.

| Parcours | Localisation | Réparation et validation | Total |
| --- | ---: | --- | ---: |
| Baseline fixe | 11,438 s | Copie de référence 2,244 s, validation 5,080 s | 35,695 s |
| Rbitnet CPU | 11,493 s | Deux générations et applications, puis leurs validations | 126,923 s |

Les deux diffs Rbitnet ont passé `git apply --check` puis `git apply`
dans le bac. Les empreintes des fichiers appliqués ont été
confirmées. Le modèle a reçu la méthode fautive et le diagnostic de
la première validation. Le montage du run Rbitnet contenait la copie
fautive et ses propositions.

| Tentative | Génération et application dans le bac | Validation | Tests | SQLite |
| --- | ---: | ---: | ---: | --- |
| Graine 741 | 42,023 s | 5,665 s | 2/4 | Code 0 |
| Graine 751 | 43,223 s | 4,861 s | 4/4 | Code 0 |

Le premier diff persistait la note et fermait la connexion. Le second
conserve la connexion et passe les quatre tests sans saut. Il garde
la docstring historique qui décrit la faute. Le surcoût observé est
de **91,228 s**, soit **3,56 fois** le temps de la baseline pour cette
paire de runs.

Les rapports sont `phase1-rbitnet-notes/baseline-final/report.json`
et `phase1-rbitnet-notes/rbitnet-graph/report.json` dans le dossier
de preuves du banc. Le diff retenu est `rbitnet-2/proposal.diff`
dans le dossier du graphe Rbitnet.

### Connexion et docstring dès la première proposition

Le premier ajustement a demandé à Rbitnet de laisser la connexion à
l'appelant et de réécrire la docstring. Les deux propositions de ce
rejeu s'appliquaient et passaient SQLite, avec **3/4 tests**. Le cache
de session du premier diff créait un doublon dans `list_notes`.

La [consigne finale](../../akasha_brain/prompts/notes-repair-v1.json) demande une
ligne SQLite, le vrai `lastrowid` et la docstring « Enregistre la note
dans SQLite et renvoie son identifiant. » Le premier diff obtenu avec
la graine 741 applique ces trois éléments et garde la connexion
ouverte. `git apply --check`, `git apply` et le contrôle d'empreinte
passent dans Windows Sandbox. Le rejeu réussit **4/4 tests sans saut**
et le vérificateur SQLite renvoie `0`.

| Parcours | Localisation | Réparation | Validation | Total |
| --- | ---: | ---: | ---: | ---: |
| Baseline fixe | 12,126 s | 2,429 s | 5,377 s | 37,632 s |
| Rbitnet CPU, consigne finale | 12,084 s | 43,177 s | 5,246 s | 80,691 s |

Le total inclut la préparation, l'isolation, l'exécution et l'arrêt
du bac. Sur cette paire de runs, Rbitnet prend **43,059 s** de plus,
soit **2,14 fois** le temps de la baseline. Les deux runs utilisent les
mêmes fixtures et le même harnais. Les rapports et le premier diff
validé sont dans `phase1-rbitnet-notes-prompt/`, sous
`baseline/` et `rbitnet-explicit-sqlite/`. Le premier ajustement
est conservé sous `rbitnet/`.

### Trois rejeux de la consigne figée

`notes-repair-v1` reprend mot pour mot la consigne de la première
proposition validée. Le lanceur vérifie son SHA-256. Le banc ajoute la
même méthode fautive et utilise Qwen3-8B Q4_K_M, température 0 et
176 jetons maximum.

Les graines 742, 743 et 744 ont chacune leur bac neuf et leur propre
processus Rbitnet CPU. Le mode `--first-diff-seed` limite le parcours
au premier diff. Le verdict exige le contrôle et l'application dans
Windows Sandbox, les quatre tests sans saut et le vérificateur SQLite.
La baseline fixe est rejouée avec le même harnais et un bac neuf.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain run contracts/examples/goal_notes_regression.json `
    --python-runtime $pythonPortable --output $dossierRapport `
    --rbitnet $rbitnetExe $gguf $tokenizer --first-diff-seed 742
```

| Parcours | Premier diff | Tests sans saut | SQLite | Temps total |
| --- | --- | ---: | ---: | ---: |
| Baseline fixe | Référence | 4/4 | Code `0` | 36,468 s |
| Rbitnet CPU, graine 742 | Appliqué | 4/4 | Code `0` | 81,743 s |
| Rbitnet CPU, graine 743 | Appliqué | 4/4 | Code `0` | 81,619 s |
| Rbitnet CPU, graine 744 | Appliqué | 4/4 | Code `0` | 81,298 s |

Chaque premier diff passe `git apply --check`, `git apply` et la
vérification de l'empreinte du fichier appliqué. Les trois diffs
obtenus à température 0 ont la même empreinte
`27602ad73de14748bae776af74b65203bd1cf07d4e7dfaa2243912ac06cb9206`.
Ils conservent la connexion ouverte et remplacent la docstring.
Les temps incluent la préparation, les contrôles et l'arrêt du
bac. Les trois rejeux Rbitnet prennent **81,553 s** en moyenne,
soit **45,085 s de plus** et **2,24 fois** le temps de la baseline.

Les preuves sont dans `phase1-rbitnet-notes-frozen/` sous
`seed-742/`, `seed-743/`, `seed-744/` et `baseline/`.

## Parcours bureau Notes avec RapidOCR

Le parcours `run-desktop` démarre un bac neuf sous le profil durci
et applique le diff Rbitnet validé sur une copie jetable. Il vérifie
l'empreinte du diff et celle du fichier appliqué. Les roues Python
installées localement sont copiées avec leurs modèles ONNX. Le
chargement d'ONNX Runtime a demandé `MSVCP140_1.dll`. Les DLL
Visual C++ locales sont copiées dans le runtime jetable du bac.
Le rapport conserve leurs empreintes et celles des modèles.

Le script saisit `Note Akasha` et `Contenu durable` avec le focus
UIA vérifié. RapidOCR 1.4.4 sur ONNX Runtime 1.32.0 détecte le bouton
Enregistrer à partir de pixels de la fenêtre Notes. La commande
de clic vérifie le PID avant d'agir. Les sessions de détection,
classement et reconnaissance utilisent `CPUExecutionProvider`.

Le processus Notes se ferme, puis un nouveau processus ouvre la même
base. L'OCR retrouve la note dans la liste, la sélectionne et reconnaît
le contenu réaffiché. Une lecture SQLite séparée, en lecture seule,
confirme exactement une ligne avec un identifiant positif, le titre et
le contenu attendus. Le premier essai concluant a pris `47,970 s`
de bout en bout, avec le code invité `0x471F` et les contrôles du
montage et des canaux réussis. Le rapport se trouve dans
`phase1-notes-ocr/run-3/report.json` dans le dossier de preuves.

### Protocole figé

Le [manifeste v2](../../akasha_brain/protocols/notes-desktop-ocr-v2.json)
fixe le diff de la graine 742, le fichier réparé, le profil Windows Sandbox,
les sources du parcours, les versions des paquets OCR et les empreintes des
modèles ONNX ainsi que des principaux binaires. Le lanceur vérifie les
entrées avant de démarrer chaque bac et consigne l'empreinte du manifeste
dans le rapport.

La première série a révélé deux pertes de focus avant l'enregistrement.
Le parcours v2 tente de rendre le focus à la fenêtre du processus Notes si
elle le perd pendant la saisie. L'envoi de touches exige toujours que la
fenêtre de premier plan et l'élément UIA actif appartiennent à ce processus.

Pour rejouer, fournir comme `$diffNotes` le fichier
`phase1-rbitnet-notes-frozen/seed-742/rbitnet-1/proposal.diff` du dossier de
preuves, le Python portable du banc et un dossier de résultats neuf.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain run-desktop contracts/examples/goal_notes_regression.json `
    --python-runtime $pythonPortable --diff $diffNotes --output $dossierRapport
```

### Trois rejeux en bacs neufs

Les trois rapports attestent la même empreinte du manifeste, trois bacs
distincts et leur arrêt. Pour chaque rejeu, le diff s'applique et le code
invité `0x471F` confirme le clic sur Enregistrer, le redémarrage de Notes,
la sélection de la note et la reconnaissance de son contenu par RapidOCR,
ainsi que la lecture SQLite indépendante.

| Rejeu | OCR après redémarrage | Ligne exacte dans SQLite | Temps total |
| --- | --- | --- | ---: |
| 1 | Réussi | Confirmée | 50,748 s |
| 2 | Réussi | Confirmée | 49,871 s |
| 3 | Réussi | Confirmée | 49,240 s |

Le temps couvre la préparation des entrées, le démarrage du bac, le
parcours et la confirmation de l'arrêt du bac. Les rapports se trouvent
dans `phase1-notes-ocr-frozen-v2-validation/run-1/`, `run-2/` et `run-3/`
sous le dossier de preuves. La série initiale est conservée dans
`phase1-notes-ocr-frozen/`. Les rejeux 1 et 3 s'étaient arrêtés avant
l'enregistrement (code 22) et le rejeu 2 avait réussi en 49,060 s.

## Graphe complet Rbitnet CPU et RapidOCR v2

Le graphe `notes-rbitnet-ocr@1.0.0` lance la vérification bureau après
les quatre tests et le vérificateur SQLite du code réparé. Rbitnet
génère le premier diff sur l'hôte, en CPU sur la boucle locale. Le
lanceur exige que le diff et le fichier résultant correspondent aux
empreintes du protocole RapidOCR v2. Dans le même bac, Git applique le
diff, les tests contrôlent la copie réparée, puis le scénario bureau
démarre Notes depuis cette copie. Après relance de l'application,
RapidOCR retrouve la note et une lecture SQLite indépendante contrôle
la base créée par le scénario bureau.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain run contracts/examples/goal_notes_regression.json `
    --python-runtime $pythonPortable --output $dossierRapport `
    --rbitnet $rbitnetExe $gguf $tokenizer --first-diff-seed 742 --rapidocr
```

Le rejeu du 15 novembre 2026 a pris **109,775 s**, de la préparation
des entrées à l'arrêt confirmé du bac. Les contrôles d'isolation et
d'autorisation ont passé. Les quatre étapes ont utilisé le même bac.

| Étape | Résultat | Temps |
| --- | --- | ---: |
| Localisation | Deux échecs reproduits sur la version fautive | 13,089 s |
| Rbitnet CPU | Premier diff généré, empreinte conforme, appliqué par Git | 43,978 s |
| Validation du code | 4/4 tests sans saut, vérificateur SQLite code `0` | 5,665 s |
| Vérification bureau | Note retrouvée après relance, ligne SQLite exacte | 24,515 s |

La vérification bureau a renvoyé `0x471F`. RapidOCR a retrouvé
`Note Akasha` et reconnu `Contenu durable` après relance. Le rapport
complet et le diff généré sont dans
`phase1-notes-rbitnet-ocr-integrated/run-1/` sous le dossier de preuves.

### Trois graines et baseline fixe

Les graines 742, 743 et 744 ont chacune tourné dans un bac neuf. La
baseline fixe a été rejouée sur le même hôte dans un quatrième bac.
Les temps vont de la préparation des entrées à l'arrêt confirmé du bac.

| Parcours | Premier diff | Tests | RapidOCR après relance | SQLite après relance de Notes | Total | Écart à la baseline |
| --- | --- | --- | --- | --- | ---: | ---: |
| Baseline fixe | Référence copiée | 4/4 | — | — | 37,161 s | — |
| Graine 742 | Appliqué | 4/4 | Réussi | Ligne exacte | 106,589 s | +69,428 s |
| Graine 743 | Appliqué | 4/4 | Réussi | Ligne exacte | 105,159 s | +67,998 s |
| Graine 744 | Appliqué | 4/4 | Réussi | Ligne exacte | 103,881 s | +66,720 s |

Les trois premiers diffs ont la même empreinte SHA-256, conforme au
protocole RapidOCR v2. Git a vérifié et appliqué chaque diff dans le
bac, puis le lanceur a confirmé l'empreinte du fichier réparé. Le
vérificateur SQLite du banc a renvoyé `0` pour les quatre exécutions.
Chaque parcours bureau a renvoyé `0x471F`.

Le graphe complet prend en moyenne **105,210 s**, soit **68,049 s de
plus** et **2,83 fois** la baseline fixe. La baseline couvre la
localisation, la copie de référence, les quatre tests et le vérificateur
SQLite du banc. L'écart inclut la génération du diff et la vérification
bureau.

Les rapports se trouvent dans `phase1-notes-rbitnet-ocr-three-seeds/`,
sous `seed-742/`, `seed-743/`, `seed-744/` et `baseline/`.

## Journal ExperienceRecord et évolution synthétique

Chaque exécution du graphe Notes enregistre un `ExperienceRecord` v1
validé dans SQLite, avec versions de capacités, verdicts techniques,
temps et codes d'erreur. Le journal partagé du mode `--evolution-db`
sert aussi au registre des versions et à la chaîne de décisions.

Sur l'objectif synthétique figé, le premier graphe actif est
`notes-rbitnet@1.0.0`. La fin d'une tâche gérée déclenche un cycle
en arrière-plan lorsque ce parent est actif. Le candidat
`notes-rbitnet-ocr@1.0.0` conserve les contrôles du parent et ajoute
la vérification RapidOCR et SQLite après relance. Les essais
internes écrivent leurs expériences sans déclencher d'autre cycle.

Les paliers replay, observation et exposition limitée utilisent
chacun un bac neuf. Le parent reste actif jusqu'à la décision.
L'activation exige les preuves des trois paliers, le même premier
diff, les quatre tests, SQLite et l'observation bureau, ainsi que
les contrôles d'isolation et d'autorisation. Le bail du registre
limite la concurrence à une exécution. La durée du cycle candidat,
le nombre d'essais, les pools CPU et le budget d'admission RAM de
Rbitnet sont configurables. Le profil invité garde le GPU désactivé.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain run contracts/examples/goal_notes_regression.json `
    --python-runtime $pythonPortable --output $dossierRapport `
    --rbitnet $rbitnetExe $gguf $tokenizer --evolution-db $journal `
    --evolution-wall-s 480 --evolution-max-trials 3 `
    --evolution-cpu-threads 8 --evolution-model-ram-mb 8192
.\.venv\Scripts\python.exe -m akasha_brain evolution status --db $journal
.\.venv\Scripts\python.exe -m akasha_brain evolution rollback --db $journal
```

### Rejeu et retour arrière

La tâche de référence a réussi en **83,070 s** et son
`ExperienceRecord` a déclenché le cycle. Les trois premiers diffs
ont la même empreinte que la référence. Chaque palier a passé les
quatre tests, le vérificateur SQLite et le parcours bureau
RapidOCR et SQLite après relance.

| Palier | Verdict | Temps |
| --- | --- | ---: |
| Replay | Réussi | 111,978 s |
| Observation | Réussi | 113,856 s |
| Exposition limitée | Réussi | 111,074 s |
| Total du cycle candidat | Promotion automatique | 336,953 s |

Le cycle a consommé **3 essais sur 3** et **336,953 s sur 480 s**.
Le bail a refusé un lancement concurrent avant création de son
bac. Le raccord du plafond d'admission RAM a été corrigé après le
démarrage du cycle. Le moteur avait estimé le chargement à
5 021 827 072 octets pour chacun des essais. Avec le raccord corrigé,
le graphe promu a réussi en **113,623 s** sous 8 192 Mio et la
sonde à 1 024 Mio a obtenu un refus de chargement avec `/ready`
en HTTP 503. Ce plafond porte sur l'estimation à l'admission.

Le retour arrière a rétabli `notes-rbitnet@1.0.0`. La nouvelle
tâche a effectivement utilisé ce parent et réussi en **82,024 s**.
Elle a déclenché une demande d'évolution avec un budget de zéro
essai. La demande est restée en attente avec
`resource_budget_exceeded`, avant création d'un bac candidat.

Le dossier de preuves `phase1-notes-evolution/` contient six rapports
de bac et le registre SQLite `registry.db`. La relecture a validé
les six enregistrements `ExperienceRecord` et la chaîne des onze
événements de décision. La promotion porte sur la vérification
supplémentaire du scénario synthétique figé.

### Rejeu avec le plafond RAM corrigé

Le registre SQLite repart d'un état neuf. Le plafond d'admission
Rbitnet de **8 192 Mio** et les pools CPU configurés à **8 threads**
s'appliquent dès la tâche de référence, aux trois essais candidats,
puis aux tâches de contrôle après promotion et retour arrière.
Les six lancements consignent `RBITNET_MAX_LOAD_BYTES=8589934592`.
La sonde à **1 024 Mio** refuse le chargement et renvoie HTTP 503
sur `/ready`.

| Palier candidat | Verdict | Temps |
| --- | --- | ---: |
| Replay | Réussi | 113,759 s |
| Observation | Réussi | 111,443 s |
| Exposition limitée | Réussi | 111,118 s |
| Total du cycle candidat | Promotion automatique | 336,360 s |

Le cycle déclenché par la tâche de référence a passé **3 essais sur 3**
en **336,360 s sur 480 s**. Le bail a refusé un lancement concurrent.
Le premier diff correspond à la référence dans chaque bac. Les
quatre tests et SQLite passent, puis RapidOCR et SQLite confirment
la persistance après relance sur les trois essais candidats.

Une nouvelle tâche utilise le graphe promu et réussit en **111,348 s**.
Le retour arrière restaure `notes-rbitnet@1.0.0`, puis une tâche
réussit avec ce parent en **88,416 s**. Elle déclenche une demande
avec un budget de zéro essai. Le registre consigne
`resource_budget_exceeded` et aucun bac candidat n'est créé.

L'[export du journal et des résultats](../../bench/results/notes-evolution-ram-v1.json)
contient les six `ExperienceRecord` et les onze événements chaînés.
Le registre SQLite et les rapports bruts sont dans le dossier
de preuves `phase1-notes-evolution-ram-frozen/`.

## Transfert sur la variante Tâches v2

Le graphe actif `notes-rbitnet@1.0.0` a été figé au commit
`a4987cc` avant la création de la [variante réservée](../../bench/tasks_transfer_v2/).
Dans Windows Sandbox, avec vGPU désactivé, le compilateur archivé
recompile le graphe Notes à l'identique. Le `GoalSpec` Tâches passe
le schéma et reçoit `capability_unavailable` à l'admission. Le
refus intervient avant l'exécution des nœuds et l'inférence Rbitnet.

Le contrôle indépendant sélectionne chaque filtre dans Tk et lit
les lignes des widgets visibles. Un processus séparé relit SQLite
en lecture seule et vérifie aussi l'empreinte de la base. Le témoin
corrigé applique une modification du sélecteur sur sa propre copie.

| Filtre | Variante fautive | Témoin corrigé |
| --- | --- | --- |
| À faire | Les deux tâches, échec | La tâche à faire seule |
| Terminées | La tâche terminée seule | La tâche terminée seule |
| Toutes | Les deux tâches | Les deux tâches |

SQLite reste inchangé dans les deux cas. Le montage du témoin suit
le verdict d'admission. Le registre actif conserve son empreinte,
ses six expériences et ses onze événements. Le rejeu est exclu
de l'évolution.

Le résultat est dans `phase1-tasks-transfer-v2/run-2/report.json`
dans le dossier de preuves. La mesure complète a pris **35,286 s**.
Le premier bac a révélé des dépendances absentes du paquet portable.
Le paquet complété a été rejoué dans un bac neuf. Rejouer avec
`python -m bench.run_tasks_transfer --python-runtime $pythonPortable
--registry $journal --freeze $snapshot --output $dossierNeuf`.

## Graphe Tâches et transfert v3

Le graphe `tasks-rbitnet@1.0.0` reprend la séquence localisation,
proposition de diff et vérification. Le plan, la consigne générique,
le périmètre d'édition Python, le harnais et les paramètres Rbitnet ont
été [figés](../../akasha_brain/protocols/tasks-rbitnet-v1.json) avant
la création de la [variante v3](../../bench/tasks_transfer_v3/).
La variante v2 est restée hors des entrées de développement.

Dans un Windows Sandbox neuf, le témoin indépendant passe les trois
filtres. Le modèle reçoit le module à réparer, le symptôme et les
verdicts du banc. Le témoin, l'oracle et les données de la base restent
réservés au contrôle. Rbitnet tourne sur CPU sur la boucle locale.
Git vérifie et applique le diff dans le bac, puis le lanceur confirme
l'empreinte du fichier obtenu.

| Filtre | Variante fautive | Témoin indépendant | Après le diff |
| --- | --- | --- | --- |
| À faire | Échec | Réussi | Échec |
| Terminées | Réussi | Réussi | Réussi |
| Toutes | Réussi | Réussi | Réussi |

Le diff remplace `COALESCE(closed_at, '') IS NOT NULL` par
`COALESCE(closed_at, '') IS NULL`. Comme `COALESCE` remplace les
`NULL` par une chaîne vide, ce prédicat laisse le filtre vide.
Le contrôle lit les widgets visibles et relit SQLite en lecture seule
après chaque filtre. Les états et l'empreinte de la base sont inchangés.

Le transfert échoue avec **2/3 filtres**, en **145,976 s** jusqu'à
l'arrêt du bac, dont **104,127 s** de génération. Le registre Notes
conserve son empreinte, ses six expériences et ses onze événements.
Le rapport et le diff sont dans `phase1-tasks-transfer-v3/run-1/`
sous le dossier de preuves.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain run bench/tasks_transfer_v3/goal.json `
    --python-runtime $pythonPortable --output $dossierNeuf `
    --rbitnet $rbitnetExe $gguf $tokenizer --transfer-case bench/tasks_transfer_v3 `
    --transfer-freeze akasha_brain/protocols/tasks-rbitnet-v1.json
```

## Graphe Tâches à reprise guidée et transfert v4

Le graphe `tasks-rbitnet@1.1.0` conserve la consigne initiale et
ajoute une seule reprise sur verdict défavorable. Le second appel
reçoit le diff précédent et les verdicts des trois filtres et de
SQLite. Son diff repart du module original, dans une copie de
travail et une base distinctes.

Le [gel](../../akasha_brain/protocols/tasks-rbitnet-guided-v1.json)
précède la création de la [variante v4](../../bench/tasks_transfer_v4/).
Le parcours a été conçu à partir du contrat générique. Les
entrées de la v3 sont restées hors de sa préparation et du rejeu.
La v4 vérifie le dernier événement d'une tâche, y compris après
réouverture, ainsi que le cas d'une tâche sans événement.

Le contrôle indépendant sélectionne les trois filtres dans
l'interface, vérifie les lignes visibles et relit les deux
tables SQLite en lecture seule après chaque filtre. Le témoin
passe **3/3**. La variante fautive passe **2/3**, avec un échec
sur « À faire ». Les rapports sont dans
`phase1-tasks-transfer-v4/` sous le dossier de preuves.

| Bac neuf | Première tentative | Seconde tentative guidée | Temps total |
| --- | --- | --- | ---: |
| 1 | Diff appliqué, 2/3 filtres, SQLite intact | Délai HTTP de 135 s atteint avant réception du diff | 286,549 s |
| 2 | Diff appliqué, 2/3 filtres, SQLite intact | Délai HTTP de 135 s atteint avant réception du diff | 285,646 s |

Les deux premiers diffs ont la même empreinte. Ils vérifient les
statuts `opened` et `reopened` pour traiter les réouvertures. La
base encode les réouvertures avec `open`. Le contrôle confirme
l'échec sur « À faire » et la réussite
sur « Terminées » et « Toutes ». L'historique SQLite reste intact.

Les deux secondes requêtes CPU contiennent le diff et le verdict
de la première tentative. Les deux bacs se sont arrêtés et le
registre d'évolution conserve son empreinte, ses six expériences et
ses onze événements.

### Rejeu v4 avec délai HTTP de 300 s

Le [nouveau gel](../../akasha_brain/protocols/tasks-rbitnet-guided-v2.json)
fixe les délais HTTP à **135 s** pour la première tentative et **300 s**
pour la seconde. Les empreintes de la variante v4 et les deux requêtes
au modèle correspondent au rejeu précédent.

Rbitnet CPU a terminé la seconde génération en **141,457 s**. Git a
vérifié et appliqué le second diff dans un bac Windows neuf, puis le
lanceur a confirmé l'empreinte du fichier obtenu. Les deux diffs sont
identiques octet pour octet.

| Filtre | Après le second diff | Témoin indépendant |
| --- | --- | --- |
| À faire | Échec | Réussi |
| Terminées | Réussi | Réussi |
| Toutes | Réussi | Réussi |

Le contrôle SQLite confirme que les états et l'historique sont intacts.
Le transfert reste à **2/3 filtres**. Le rejeu a pris **302,013 s**
jusqu'à l'arrêt du bac. Le registre d'évolution conserve son empreinte,
ses six expériences et ses onze événements. Le rapport et les deux
diffs sont dans `phase1-tasks-transfer-v4-http300/run-1/` sous le
dossier de preuves.

## Retour détaillé et transfert Tâches v5

Le [gel du graphe](../../akasha_brain/protocols/tasks-rbitnet-guided-v3.json)
`tasks-rbitnet@1.2.0` précède la création de la
[variante v5](../../bench/tasks_transfer_v5/). Le développement s'appuie
sur le contrat générique. Le vérificateur transmet les nombres de
lignes manquantes et inattendues par filtre, ainsi que l'écart d'ordre
quand les mêmes lignes sont visibles. La seconde proposition est
refusée avant application si son diff ou sa structure Python répète
la première.

La variante classe une tâche comme terminée quand elle possède au
moins une étape obligatoire et que toutes ses étapes obligatoires
sont cochées. Le témoin indépendant passe **3/3**. Le code fautif
passe **2/3** avec une tâche manquante sous « À faire ».

| Filtre | Après le premier diff | Après le second diff |
| --- | --- | --- |
| À faire | 1 ligne manquante, 2 inattendues | 1 ligne manquante |
| Terminées | 1 ligne inattendue | 1 ligne inattendue |
| Toutes | Aucun écart | Aucun écart |

Rbitnet CPU reçoit le premier diff et les écarts mesurés avant de
produire la seconde proposition. Les deux diffs ont des empreintes
distinctes, y compris au niveau de la structure Python. Git vérifie
et applique les deux diffs dans Windows Sandbox. Le second restaure
le prédicat fautif du filtre « À faire » et cherche uniquement les
étapes à `checked = 0` sous « Terminées ». Une étape obligatoire à
`NULL` peut ainsi être considérée comme cochée.

Les deux tentatives passent **1/3 filtres** et le vérificateur confirme
l'intégrité SQLite. Le rejeu a pris **304,659 s** jusqu'à l'arrêt du
bac. Les deux diffs et le rapport sont sous
`phase1-tasks-transfer-v5/run-1/` dans le dossier de preuves.
Le rejeu est hors évolution. Le registre conserve son empreinte, ses
six expériences et ses onze événements.

## Protection des filtres initiaux et transfert Tâches v6

Le [gel](../../akasha_brain/protocols/tasks-rbitnet-guided-v4.json)
de `tasks-rbitnet@1.3.0` précède la création de la
[variante v6](../../bench/tasks_transfer_v6/). La règle part du
verdict initial pour déterminer quels filtres la reprise doit
préserver. La consigne de reprise nomme ces filtres et indique
les régressions du premier diff à corriger. Après application
d'un second diff distinct dans le bac, le vérificateur refuse
la reprise si un filtre protégé échoue.

La v6 vérifie le tri par échéance sur « À faire », avec les
tâches non datées à la fin et l'identifiant pour départager les
dates identiques. « Terminées » et « Toutes » gardent le tri par
identifiant. Le contrôle lit les listes visibles et relit SQLite
en lecture seule après chaque filtre.

| Filtre | Contrôle initial | Après le premier diff |
| --- | --- | --- |
| À faire | Lignes exactes dans le mauvais ordre | 4 lignes manquantes |
| Terminées | Réussi, protégé | Réussi |
| Toutes | Réussi, protégé | Régression, 7 lignes manquantes |

Le premier diff passe `git apply --check` et le contrôle
d'empreinte. Le diff introduit le nom `due_date`. La colonne
s'appelle `due` dans le schéma de test et le module fourni au
modèle omet le nom de la colonne d'échéance.

La reprise reçoit « Terminées » et « Toutes » comme contraintes
et demande explicitement de rétablir « Toutes ». Rbitnet CPU
renvoie le même diff et la même structure Python. Le lanceur
refuse ce doublon avant application. Le dernier verdict mesuré
est **1/3**, avec SQLite intact. Le témoin indépendant passe **3/3**.

Le rejeu prend **283,998 s** jusqu'à l'arrêt du bac et reste hors
évolution. Le registre conserve son empreinte, ses six expériences
et ses onze événements. Le rapport et les deux propositions
sont sous `phase1-tasks-transfer-v6/run-1/` dans le dossier de preuves.

## Schéma SQLite et transfert Tâches v7

Le [gel](../../akasha_brain/protocols/tasks-rbitnet-guided-v5.json) de
`tasks-rbitnet@1.4.0` précède la création de la
[variante v7](../../bench/tasks_transfer_v7/). Le graphe fournit le DDL
à Rbitnet dès la première tentative et le renvoie à la reprise. Le
contrôle indépendant initialise SQLite à partir de ce même fichier.
Les deux requêtes contiennent le DDL exact et les lignes d'essai sont
chargées séparément dans le bac. La v6 est restée hors de ce nouveau rejeu.

La v7 utilise une table de statuts avec un indicateur de fin. Le filtre
« À faire » doit suivre cet indicateur pour inclure les tâches nouvelles,
en relecture ou en attente. Le contrôle compare chaque liste visible aux
identifiants et titres attendus, dans l'ordre, puis relit les deux tables
et vérifie l'empreinte du fichier SQLite après chaque filtre.

| Étape | Application dans Windows Sandbox | À faire | Terminées | Toutes | SQLite | Génération CPU |
| --- | --- | --- | --- | --- | --- | --- |
| État initial | Sans diff | 2 lignes manquantes | Réussi | Réussi | Intact | — |
| Témoin indépendant | Sélecteur de référence | Réussi | Réussi | Réussi | Intact | — |
| Tentative 1 | `git apply --check` et empreinte validés | 2 lignes manquantes | Réussi | Réussi | Intact | 111,187 s |
| Tentative 2 | Doublon rejeté avant application | — | — | — | — | 142,880 s |

Le premier diff explicite le cas « Toutes » et conserve la sélection
`state_code = 'new'` pour « À faire ». La reprise reçoit l'écart mesuré
et les deux filtres protégés. Elle produit le même diff et la même
structure Python. Les deux générations atteignent la limite de 384 jetons
en répétant le bloc de code. Le dernier verdict indépendant est de **2/3**.

Le rejeu prend **299,907 s** jusqu'à l'arrêt du bac. Les preuves sont sous
`phase1-tasks-transfer-v7/run-1/`. Le registre d'évolution garde la même
empreinte, le graphe Notes actif, six expériences et onze événements.

## Filtres ciblés et transfert Tâches v8

Le [gel](../../akasha_brain/protocols/tasks-rbitnet-guided-v6.json) de
`tasks-rbitnet@1.5.0` précède la création de la
[variante v8](../../bench/tasks_transfer_v8/). La première requête cible
les filtres qui échouent sur le module d'origine. La reprise cible ceux
qui échouent après le premier diff et garde les filtres déjà valides sous
contrôle. Chaque requête exige de corriger la logique qui sélectionne ou
ordonne les lignes pour les filtres ciblés. Le verdict indépendant reste
obligatoire pour accepter un diff. La v7 est restée hors de ce rejeu.

Dans la v8, « Terminées » doit présenter une seule ligne par tâche ayant
au moins un reçu de clôture accepté. Le contrôle actionne les trois filtres
du tableau, compare les identifiants et titres affichés et vérifie les deux
tables ainsi que l'empreinte SQLite après chaque filtre.

| Étape | À faire | Terminées | Toutes | SQLite |
| --- | --- | --- | --- | --- |
| État initial | Réussi | 1 ligne en trop | Réussi | Intact |
| Témoin indépendant | Réussi | Réussi | Réussi | Intact |
| Premier diff Rbitnet CPU | Réussi | Réussi | Réussi | Intact |

Le premier diff passe `git apply --check` et le contrôle d'empreinte.
Il ajoute `SELECT DISTINCT` dans la branche du filtre « Terminées »,
avec une affectation SQL redondante. La génération prend **117,606 s** et
atteint la limite de 384 jetons après avoir fourni un bloc complet. Le
verdict indépendant accepte le premier diff. Les tests couvrent le calcul
de la cible en reprise et ce rejeu s'arrête après la première tentative.

Le parcours prend **158,983 s** jusqu'à l'arrêt du bac. Les preuves sont
sous `phase1-tasks-transfer-v8/run-1/`. Le registre d'évolution garde la
même empreinte, le graphe Notes actif, six expériences et onze événements.

## Reprise sur la variante Tâches v9

La [variante v9](../../bench/tasks_transfer_v9/) réutilise le
[gel](../../akasha_brain/protocols/tasks-rbitnet-guided-v6.json) de
`tasks-rbitnet@1.5.0`. Le filtre « À faire » doit combiner trois conditions.
La tâche est ouverte, sans report en cours au jour de référence et tous
ses prérequis directs sont terminés. L'essai couvre la date de fin de report
exacte et une tâche avec deux prérequis dont un seul est terminé.

Le témoin classe les tâches en Python après lecture des deux tables.
Le contrôle indépendant compare l'identifiant et le titre de chaque ligne
visible aux listes attendues puis relit SQLite et compare son empreinte
après chaque filtre. Les données d'essai et le témoin servent uniquement
au contrôle dans le bac.

| Étape | À faire | Terminées | Toutes | SQLite | Génération CPU |
| --- | --- | --- | --- | --- | --- |
| État initial | 3 lignes en trop | Réussi | Réussi | Intact | — |
| Témoin indépendant | Réussi | Réussi | Réussi | Intact | — |
| Premier diff appliqué | 1 ligne manquante, 4 en trop | 3 lignes manquantes | 9 lignes manquantes | Intact | 119,723 s |
| Reprise | Doublon rejeté avant application | — | — | — | 178,347 s |

Le premier diff passe `git apply --check` et le contrôle d'empreinte.
Il passe le paramètre SQL `AS_OF` aux trois requêtes, alors que seule
« À faire » a un paramètre. La reprise reçoit les écarts des trois filtres
et la contrainte de rétablir « Terminées » et « Toutes ». Rbitnet CPU
produit le même diff et la même structure Python. Le graphe déclenche
la reprise et écarte le doublon. Le dernier verdict indépendant est
de **0/3**, avec SQLite intact. Les deux générations atteignent le plafond
de 384 jetons.

Le rejeu prend **343,447 s** jusqu'à l'arrêt du bac. Les preuves sont sous
`phase1-tasks-transfer-v9/run-1/`. Le gel et le registre d'évolution
conservent leurs empreintes. Le registre compte six expériences et onze
événements, avec Notes comme graphe actif.

## Reprise sans le premier diff et transfert Tâches v10

Le [gel](../../akasha_brain/protocols/tasks-rbitnet-guided-v7.json) de
`tasks-rbitnet@1.6.0` précède la création de la
[variante v10](../../bench/tasks_transfer_v10/). La consigne de reprise
prend les écarts du contrôle par filtre, les filtres protégés, le DDL et le
module d'origine. Le lanceur conserve le premier diff et son empreinte
pour rejeter une proposition répétée. Le changement ne s'appuie sur aucun
rejeu de la v9.

La v10 vérifie le tri de « Toutes » par responsable après `strip()` et
`casefold()`, puis par identifiant. Les responsables nuls ou vides viennent
en dernier. Le contrôle compare les lignes visibles, leur ordre et
l'empreinte SQLite après chaque filtre.

| Contrôle indépendant | À faire | Terminées | Toutes | SQLite | Génération CPU |
| --- | --- | --- | --- | --- | --- |
| État initial | Réussi | Réussi | Ordre incorrect | Intact | — |
| Témoin | Réussi | Réussi | Réussi | Intact | — |
| Premier diff appliqué | 5 lignes manquantes | 4 lignes manquantes | 9 lignes manquantes | Intact | 114,952 s |
| Second diff distinct appliqué | 5 lignes manquantes | 4 lignes manquantes | 9 lignes manquantes | Intact | 117,622 s |

La trace confirme que la seconde requête contient les écarts des trois
filtres et omet le premier diff. Les deux propositions passent
`git apply --check` et le contrôle d'empreinte. Elles renvoient trois
colonnes à l'interface qui attend des paires identifiant et titre. Le
contrôle observe des listes vides et le graphe refuse la reprise pour
régression de « À faire » et « Terminées ». Le verdict final est de
**0/3**, avec SQLite intact. Les deux générations atteignent la limite
de 384 jetons.

Le rejeu prend **280,240 s** jusqu'à l'arrêt du bac. Les preuves sont sous
`phase1-tasks-transfer-v10/run-1/`. Le registre d'évolution garde son
empreinte, le graphe Notes actif, six expériences et onze événements.

## Réparation limitée à la clause SQL du filtre en échec

Le protocole limite l'édition au littéral SQL associé au filtre en échec.
Le lanceur génère le diff à partir de cette édition et Windows Sandbox
vérifie son application avant le contrôle indépendant des trois listes et
de SQLite. Chaque variante a été préparée après le gel de son protocole.
Les rapports de transfert sont exclus de l'évolution.

| Variante | CPU | CUDA | Contrôle et résultat |
| --- | ---: | ---: | --- |
| v11 | 174,671 s | 85,515 s | Défaut reproduit, témoin 3/3, SQLite intact. Les deux réponses sur chaque backend épuisent les 144 jetons dans le raisonnement. Aucun diff appliqué. |
| v12 | 184,977 s | 86,095 s | Défaut reproduit, témoin 3/3, SQLite intact. En mode sans raisonnement, les réponses commencent par une clause SQL puis la répètent. Le parseur rejette le message complet. Aucun diff appliqué. |

Le [gel suivant](../../akasha_brain/protocols/tasks-rbitnet-sql-v3.json)
extrait le premier bloc SQL complet en tête de réponse. Il a été établi
avant la création de la [variante v13](../../bench/tasks_transfer_v13/),
qui vérifie le tri par priorité du filtre « Toutes ». Les preuves v11 et
v12 sont sous `phase1-tasks-transfer-v11/` et `phase1-tasks-transfer-v12/`.

### Transfert Tâches v13 avec reprise guidée

Chaque backend a utilisé un bac neuf, le même gel et le même cas réservé.
Le premier diff passe `git apply --check` et le contrôle d'empreinte dans
chaque bac. Il préserve « À faire » et « Terminées », mais place encore
les priorités nulles en tête dans « Toutes ». Le second diff part du module
d'origine et modifie uniquement la clause du même filtre. Le contrôle
indépendant retrouve les trois listes attendues et confirme que SQLite est
intact après chaque filtre. Les deux diffs sont distincts par tentative et
identiques entre backends. Les fichiers du cas réservé sont intacts.

| Backend | Premier diff | Second diff | SQLite | Génération 1 | Génération 2 | Total, bac arrêté |
| --- | --- | --- | --- | ---: | ---: | ---: |
| CPU | Appliqué, 2/3 | Appliqué, 3/3 | Intact | 67,730 s | 75,827 s | 189,479 s |
| CUDA | Appliqué, 2/3 | Appliqué, 3/3 | Intact | 24,922 s | 25,166 s | 96,047 s |

Le journal CUDA atteste un appel cuBLAS réussi pendant le préremplissage
du modèle sur l'hôte. Le bureau et SQLite s'exécutent sur CPU dans le bac.
Les rapports, les diffs et les sources gelées sont sous
`phase1-tasks-transfer-v13/`. Les deux rapports indiquent `evolution: excluded`.
Le dossier `replay-source/` de cette preuve contient le code et les contrats
dont les empreintes ont été comparées au gel v3. Il permet de rejouer ce gel
avec sa taxonomie d'erreurs d'origine après l'ajout d'`approval_expired` au runtime courant.

### Transfert Tâches v14 avec admission des modèles

Le [gel SQL v4](../../akasha_brain/protocols/tasks-rbitnet-sql-v4.json)
du graphe `1.3.0`, gestionnaire de ressources compris, précède la création
de la [variante d'atelier](../../bench/tasks_transfer_v14/). Elle vérifie
que « À faire » exclut les interventions confirmées ou annulées tout en
conservant les interventions ouvertes reportées. Le témoin indépendant
réussit sur les trois listes. L'état initial échoue uniquement sur « À faire ».

| Backend | Premier diff | Filtres | SQLite | Inférence | Total, bac arrêté |
| --- | --- | ---: | --- | ---: | ---: |
| CPU | Appliqué | 3/3 | Intact | 69,211 s | 109,358 s |
| CUDA | Appliqué | 3/3 | Intact | 24,651 s | 66,534 s |

Les deux bacs sont distincts. Le contrôle Git et l'empreinte du fichier
modifié passent. Le diff est identique sur les deux backends et les
empreintes de la variante et du témoin restent intactes. Le journal CUDA
confirme un appel cuBLAS réussi. Les rapports marquent `evolution: excluded`.
Les projections OTLP contiennent chacune le span racine et les trois
étapes observées, avec les ressources mesurées et sans contenu du cas.
Les rapports, traces et sources vérifiées sont sous
`phase1-tasks-transfer-v14/`.

## Parcours projet local avec approbation du diff

La commande `inspect-code` offre une vue ou une recherche littérale
dans des chemins explicitement choisis. La lecture est bornée à
256 Kio par fichier, 32 fichiers, 200 lignes et 500 caractères par
extrait. Les protections du parcours projet s'appliquent aussi à cette
commande. Le contrôle a trouvé les lignes et signalé la troncature sur
une copie jetable, puis a refusé l'entrée `.env`.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.project inspect-code --project $projet --file check.py --contains assert --limit 30
```

Le point d'entrée `python -m akasha_brain.project` couvre la modification
d'un fichier UTF-8 existant. `prepare` copie le fichier, le test Python
et les autres entrées explicitement sélectionnées dans Windows Sandbox.
Le montage est en lecture seule et le réseau est désactivé. Dans le
répertoire temporaire du bac, Git contrôle et applique le diff. Le
lanceur vérifie les empreintes avant et après avoir exécuté le test.

La proposition regroupe le diff exact, le fichier de remplacement et
un manifeste qui lie ces artefacts à l'identité du projet, aux empreintes
des fichiers sélectionnés et au verdict du bac. Après examen du diff,
`apply --approve` exige l'empreinte `approval_sha256` de la proposition.
Le contrôle R2 et la comparaison des empreintes précèdent le remplacement
atomique du fichier. Un changement dans le périmètre sélectionné impose
une nouvelle préparation et une nouvelle approbation.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.project prepare `
    --project $projet --output $proposition --file 'notes_store.py' `
    --replacement $remplacement --test 'check_notes.py' --python-runtime $pythonPortable
Get-Content -LiteralPath (Join-Path $proposition 'proposal.diff') -Encoding UTF8
.\.venv\Scripts\python.exe -m akasha_brain.project apply `
    --project $projet --proposal $proposition --approve $empreinteApprouvee
```

Deux copies jetables de Notes ont servi de projets de référence pour
l'essai. Les deux préparations ont validé le diff dans des bacs neufs
(22,634 s et 22,004 s). Le test a relu deux notes après réouverture et
confirmé leurs valeurs exactes dans SQLite.

| Cas | Résultat | Contrôle sur le projet de test |
| --- | --- | --- |
| Approbation absente ou liée à l'autre proposition | `approval_required` | Empreintes inchangées |
| Approbation exacte | Appliquée | Le fichier correspond à la version testée dans le bac |
| Édition du fichier après validation du diff | `contract_precondition_failed`, `project_changed` | Édition conservée et empreintes inchangées après le refus |

Le fichier du dépôt qui a servi à créer les copies conserve son empreinte.
Le diff et `report.json` sont sous `phase1-project-approval/` dans le
dossier de preuves.

## Suppressions et déplacements approuvés dans un projet local

`prepare --file $source --delete` et `prepare --file $source --move-to
$destination` préparent chacun une seule opération sur un fichier ordinaire.
Le manifeste `proposal.json` indique l'opération, les chemins concernés,
l'empreinte du fichier source et le verdict du bac. Le déplacement exige
un dossier parent existant dans le projet et une destination libre. Le
lanceur contrôle à nouveau leur état avant application.

Après examen du manifeste, l'application exige à la fois l'empreinte de
la proposition et l'accord propre à l'opération.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.project apply `
    --project $projet --proposal $suppression --approve $empreinteSuppression `
    --approve-delete $source
.\.venv\Scripts\python.exe -m akasha_brain.project apply `
    --project $projet --proposal $deplacement --approve $empreinteDeplacement `
    --approve-move $source $destination
```

Deux copies jetables ont servi à tester la suppression et le déplacement
d'un fichier binaire vers un nom avec espace et accent. Chaque préparation
utilise un bac neuf hors réseau et vérifie les empreintes et l'absence de
la source avant et après le test indépendant. Les préparations prennent
**20,831 s** pour la suppression et **20,396 s** pour le déplacement.

| Accord présenté | Suppression | Déplacement |
| --- | --- | --- |
| Accord propre à l'opération seul | Refusée | Refusé |
| Approbation de la proposition seule | Refusée | Refusé |
| Approbation et accord pour l'autre opération ou un autre chemin | Refusée | Refusé |
| Approbation et accord correspondants | Source supprimée | Source absente et empreinte conservée à destination |

Les refus retournent `approval_required` et laissent les empreintes des
copies intactes. Un troisième bac valide à nouveau la préparation du diff
Notes en 21,725 s. Les rapports sont sous `phase1-project-file-operations/`
dans le dossier de preuves.

## Accord par téléchargement et installation hors ligne

`dependency-request` présente une wheel Python avec son nom, sa version,
son URL directe, son SHA-256 et sa licence déclarée. `dependency-download`
exige une approbation dont l'empreinte correspond à cette demande et à ce
projet. Le cache local publie la wheel après contrôle du SHA-256 et des
métadonnées. Une tentative de téléchargement consomme la demande. Une
préparation ultérieure peut réutiliser la wheel vérifiée du cache.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.project dependency-request `
    --project $projet --output $demande --name $nom --version $version `
    --url $urlWheel --sha256 $sha256Wheel --license $licence
.\.venv\Scripts\python.exe -m akasha_brain.project dependency-download `
    --project $projet --request $demande --approve-download $empreinteDemande
.\.venv\Scripts\python.exe -m akasha_brain.project prepare `
    --project $projet --output $proposition --file $fichier --replacement $remplacement `
    --test $test --python-runtime $pythonPortable --dependency $demande
```

Chaque `--dependency` désigne une demande téléchargée et vérifiée. Le bac
recontrôle les empreintes, installe les wheels depuis le montage en lecture
seule dans son dossier temporaire et compare le rapport de pip aux wheels
approuvées. pip reçoit uniquement les fichiers locaux déclarés, avec
`--no-index`, `--no-deps` et `--require-hashes`.
[Documentation de pip](https://pip.pypa.io/en/stable/cli/pip_install/)

Le serveur HTTP de test sur loopback sert une wheel synthétique
`akasha-fixture-helper==1.0.0` dont la licence déclarée est `0BSD`.

| Contrôle | Résultat |
| --- | --- |
| Accord absent ou empreinte d'une autre demande | `approval_required`, zéro requête HTTP |
| Accord correspondant | Une requête HTTP, SHA-256 et métadonnées vérifiés |
| Nouvel appel avec l'accord déjà utilisé | Refus avant toute nouvelle requête |
| Préparation avec une demande sans cache vérifié | `approval_required` |
| Installation dans Windows Sandbox | Réussie avec pip 24.2, réseau désactivé et source arrêtée |

Le test invité importe la version attendue depuis le dossier d'installation
du bac et vérifie le comportement du code modifié. Il confirme l'absence
de la dépendance transitive volontairement laissée sans accord.
Les fichiers du projet de test conservent leurs empreintes. Le premier
bac a échoué au démarrage de pip faute de `libexpat.dll`. Une copie du
Python portable complétée avec la DLL de son installation d'origine a
passé le rejeu en **35,329 s**, avec la wheel déjà en cache. Le rapport est
sous `phase1-project-dependency-approval/` dans le dossier de preuves.

Les [résultats consolidés du parcours projet](../../bench/results/local-project-v1.json)
reprennent les contrôles d'approbation, d'obsolescence et d'installation.

## Consentement pour l'évolution locale

Le registre SQLite conserve chaque accord `EvolutionConsent` avec son
identifiant, le projet, les catégories autorisées et son état de
révocation. Sa finalité est `local_evolution`. Les équipes qui intègrent
une source lient son identifiant de projet et sa catégorie à l'accord
exact. Un dérivé doit présenter chacune des sources dont il dépend.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.evolution_consent --db $registre grant `
    --project $projet --category source_code
.\.venv\Scripts\python.exe -m akasha_brain.evolution_consent --db $registre check `
    --project $projet --category source_code --provenance project --consent $accord
.\.venv\Scripts\python.exe -m akasha_brain.evolution_consent --db $registre revoke --consent $accord
.\.venv\Scripts\python.exe -m akasha_brain.evolution_consent --db $registre status
```

La CLI vérifie les métadonnées déclarées. Le contrôle runtime refuse les
sources de provenance inconnue, les secrets ou un état de sensibilité
indéterminé et les variantes de transfert. L'accord peut porter une
échéance. La révocation persiste après réouverture du registre. Un nouvel
accord reçoit son propre identifiant et les travaux liés à l'ancien
accord restent refusés.

| Contrôle sur le registre de test | Verdict |
| --- | --- |
| Absence d'accord | `consent_missing` |
| Projet et catégorie approuvés | Autorisé |
| Autre projet ou autre catégorie | `consent_scope_mismatch` |
| Secret déclaré ou variante de transfert | `data_excluded` |
| Accord révoqué | `consent_revoked` |

Le moteur d'évolution vérifie les accords transmis au début et à la fin
des essais, puis dans la transaction de promotion. Les tests pilotent
des cycles avec des résultats d'essai simulés. La révocation empêche le
démarrage d'un essai en attente, arrête le cycle en cours à la fin de
l'essai démarré et empêche la promotion après la dernière preuve. Le
graphe parent reste actif dans les trois cas. Le rapport CLI est sous
`phase1-evolution-consent/report.json` dans le dossier de preuves.

## Collecte et rejeu du parcours projet local

Une proposition de remplacement validée dans Windows Sandbox permet de
sélectionner deux catégories de collecte. `source_code` désigne le code
de remplacement et `diffs` le diff de la proposition. L'accord créé via
`--project-root` est lié à l'identité du dossier local. La collecte exige
le consentement de la catégorie choisie et l'empreinte de la proposition
examinée et déclarée sans secrets. Elle contrôle l'empreinte de l'artefact
avant de le copier dans une base mutable distincte du registre d'évolution.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.evolution_consent --db $registre grant `
    --project-root $projet --category source_code
.\.venv\Scripts\python.exe -m akasha_brain.project collect `
    --project $projet --proposal $proposition --evolution-db $registre `
    --category source_code --consent $accord --reviewed-without-secrets $empreinteProposition
.\.venv\Scripts\python.exe -m akasha_brain.project reuse `
    --project $projet --evolution-db $registre --sample $copie --category source_code `
    --python-runtime $pythonPortable --output $rapport
```

Le rejeu vérifie le projet, la catégorie, l'accord et l'échéance avant
d'accéder à la copie. Il refait les contrôles du projet et du consentement
avant l'essai isolé, puis vérifie le consentement après l'arrêt du bac.
Le contenu du rejeu est temporaire et seul un rapport technique est
publié. L'échéance de la copie est fixée à 30 jours. La révocation bloque
la lecture et la collecte. L'effacement de la copie suit une demande
distincte.

| Sur les deux copies jetables de Notes | Verdict |
| --- | --- |
| Préparation normale | Diff validé en 23,919 s, aucune copie d'évolution créée |
| Collecte sans accord | `consent_missing` |
| Collecte `diffs` avec un accord `source_code` | `consent_scope_mismatch` |
| Collecte `source_code` autorisée | Un artefact copié dans la base de contenus |
| Rejeu depuis l'autre projet ou sous une autre catégorie | `consent_scope_mismatch`, aucun bac démarré |
| Rejeu dans le périmètre | Tests Notes et SQLite réussis en 22,954 s |
| Nouvelle collecte et nouvelle tentative de rejeu après révocation | `consent_revoked` |

Les fichiers des deux projets gardent leurs empreintes. Le rapport est
sous `phase1-project-evolution-data/report.json` dans le dossier de
preuves. Ce premier essai en bac portait sur `source_code`.

## Effacement des copies d'évolution du parcours projet

`project erase` enregistre une demande dans le registre de consentement
avant la suppression. Le marqueur porte l'identifiant opaque de la
demande, ceux des copies visées, l'heure et l'état. Dès son enregistrement,
les rejeux sont bloqués. Pour les propositions dont l'identifiant de
source est enregistré, une nouvelle collecte est également bloquée.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.project erase `
    --project $projet --evolution-db $registre --sample $copie
```

La demande regroupe les copies d'une même proposition. Le lanceur
supprime les rapports techniques inscrits à l'inventaire, puis les
contenus SQLite avec `secure_delete`. Si un rejeu est encore actif,
l'effacement est repris à son point sûr. Si un rapport a été remplacé
ou que son emplacement est inaccessible, la demande reste en attente
et conserve le blocage. Une nouvelle invocation reprend la même demande.

Sur une copie jetable de Notes, `source_code` et `diffs` ont chacun été
collectés puis rejoués dans Windows Sandbox. L'essai a enregistré la
demande et mesuré le blocage avant le nettoyage, pour distinguer ces deux
étapes.

| Vérification | Résultat |
| --- | --- |
| Demande enregistrée, copies encore présentes | Deux rejeux et une nouvelle collecte refusés |
| Traitement de la demande | Deux copies SQLite et deux rapports enregistrés supprimés |
| Contrôle après traitement | Aucune entrée ni aucun rapport restant pour la demande, témoin absent des fichiers SQLite de l'évolution |
| Nouvelle invocation par l'identifiant de la copie `diffs` | Même demande, état `erased` |
| Fichiers d'origine et proposition de travail | Empreintes identiques |

Cette preuve couvre le stockage local et les rapports enregistrés depuis
l'ajout de l'inventaire. La restauration des sauvegardes relève de ses
propres essais. Le rapport est sous `phase1-project-erasure/report.json`
dans le dossier de preuves.

## Sauvegarde locale chiffrée et restauration filtrée

`backup-grant` enregistre un `BackupConsent` distinct de l'accord
d'évolution. La sauvegarde inclut les copies admissibles dans les
catégories accordées et leurs rapports enregistrés. L'archive locale
est valable sept jours. La restauration conserve l'échéance la plus
proche de la copie et de l'archive.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.project backup-grant `
    --project $projet --evolution-db $registre --category source_code --category diffs
.\.venv\Scripts\python.exe -m akasha_brain.project backup `
    --project $projet --evolution-db $registre --consent $accordSauvegarde --output $archive
.\.venv\Scripts\python.exe -m akasha_brain.project restore `
    --project $projet --evolution-db $registre --backup $archive
```

Le manifeste d'archive et chaque paquet de copie avec ses rapports
utilisent AES-256-GCM avec une clé propre et un nonce aléatoire. Les clés
sont enveloppées par DPAPI à portée utilisateur dans le coffre courant,
hors de l'archive. L'archive est produite à la demande sous Windows avec
PowerShell 7. [AES-GCM (.NET)](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.aesgcm) · [DPAPI (.NET)](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.protecteddata)

L'effacement supprime les clés des objets visés et avance la tête
authentifiée des marqueurs dans le coffre. La restauration confronte le
registre courant à cette tête, filtre le manifeste avant de déchiffrer
les objets et revérifie la tête avant de publier sous le verrou SQLite
du registre. Les rapports admissibles restaurés rejoignent la base de
contenus avec leur identifiant de copie. Les chemins des anciens rapports
et les fichiers du projet restent intacts.

Sur une copie jetable de Notes, l'archive contenait trois copies et deux
rapports de rejeu avant l'effacement. Deux copies et un rapport étaient
liés à la proposition effacée. La troisième copie et son rapport ont
servi de témoin. Le stockage courant du banc a été vidé avant la
restauration pour vérifier que le témoin provenait de l'archive.

| Contrôle | Résultat |
| --- | --- |
| Accord absent ou accord d'évolution présenté seul | `backup_consent_missing` |
| Effacement | Clés des deux objets effacés retirées du coffre courant |
| Restauration avec le registre d'avant l'effacement | `ledger_unverified` |
| Restauration avec le registre courant | Deux copies filtrées, seul le témoin et son rapport restaurés |
| Contrôle après restauration | Rejeu du témoin réussi dans Windows Sandbox, rejeu des deux copies effacées refusé |

Les empreintes du projet et de l'archive antérieure concordent avant et
après l'essai. Le rapport est sous `phase1-project-backup/report.json`
dans le dossier de preuves.

Les [résultats consolidés du bloc données](../../bench/results/project-data-v1.json)
couvrent le consentement, le rejeu, l'effacement et la restauration.

## Interface desktop du graphe et des exécutions

`akasha_brain.desktop` ouvre une fenêtre native Windows avec le plan
Notes compilé, son graphe de dépendances et l'historique des tâches.
La molette et les boutons règlent le zoom. Le fond glissé déplace le
graphe et la sélection d'un nœud affiche sa capacité, sa version,
ses dépendances et les résultats disponibles.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.desktop `
    --python-runtime $pythonPortable --runs $dossierExecutions
```

Le bouton **Lancer Notes** démarre le lanceur du banc dans un thread de
travail. Le lanceur publie le début et la fin de chaque étape et la
fenêtre actualise le graphe et le décompte. Les rapports et l'historique
restent consultables depuis le dossier d'exécutions. `--rbitnet` accepte
le binaire, le GGUF et le tokenizer du protocole Notes. `--rapidocr`
ajoute le contrôle après relance lorsque ces artefacts sont fournis.

L'essai dans la fenêtre Windows a vérifié le zoom, le déplacement,
l'inspection d'un nœud et la consultation de l'historique après
réouverture. Un second lancement du parcours Notes avec référence fixe
a affiché la progression puis **3/3 étapes**, **4/4 tests** et SQLite au
vert en **39,127 s**. Le bac dédié s'est arrêté. Le rapport est sous
`phase1-desktop/runs/e4be8f77-0fd8-4cc3-bb02-dfc93a04c380/result/report.json`
dans le dossier de preuves.

### Conversation et lecture du diff Notes

La conversation peut consulter le dernier résultat vérifié dans
l'historique. La consigne v2 de Qwen3.5-2B reste figée. La fiche de résultat
nomme le banc et lui attribue les tests, avec le score sous forme `X/Y`.
Dans la fenêtre, la synthèse locale reprend **4/4 en 105,2 s**. Le verdict
déterministe ajoute les contrôles SQLite et RapidOCR. Une réponse qui
omet le nom du banc ou un chiffre entraîne le repli sur le rapport vérifié.

L'inspecteur du nœud de génération présente le diff de la tentative
dont l'empreinte a été contrôlée en bac. La lecture refuse une empreinte
différente, un chemin hors de l'exécution et un fichier illisible.
L'affichage a été vérifié sur le diff réel du rejeu CUDA repris dans
l'historique du desktop.

### Commandes desktop de l'évolution Notes

Le mode `--evolution-db` ouvre le registre local du banc synthétique.
Il prend la version active dans le registre et affiche la version
candidate tant que celle-ci attend sa promotion. **Voir le plan Notes**
ouvre le graphe actif. Les exécutions passées conservent leur graphe.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.desktop `
    --python-runtime $pythonPortable --runs $dossierExecutions `
    --rbitnet $binaireRbitnet $ggufNotes $tokenizerNotes `
    --evolution-db $registreNotes
```

**Pause** laisse l'essai en cours se terminer. Le cycle attend ensuite
avant l'essai suivant ou la promotion. Le registre conserve la demande
de pause. **Reprendre** autorise le cycle à continuer avec les preuves
déjà acquises. L'attente compte dans le budget de **480 s** du cycle,
qui admet au plus trois essais sur huit threads CPU avec un plafond
Rbitnet de **8 192 Mio**. Si le budget expire pendant la pause, le
cycle se termine et la demande de pause reste en vigueur.

**Retour arrière** restaure le parent enregistré après la fin du cycle.
Le registre journalise les commandes, le point de pause atteint et le
changement de version active.

#### Validation du 16 novembre 2026

La fenêtre a lancé le cycle `7213ed78-600f-41b6-bf64-b28fe04bcb1c`
avec Rbitnet CPU, graine 742. Une demande de pause pendant `replay`
a laissé cet essai se terminer. Le registre a marqué la pause avant
`shadow` et Windows Sandbox ne listait alors aucun bac actif.
Après **32,557 s** d'attente, **Reprendre** a lancé `shadow` dans le
même cycle.

| Parcours | Temps | Tests | SQLite | RapidOCR après relance |
| --- | ---: | --- | --- | --- |
| Référence | 88,344 s | 4/4 | Réussi | — |
| `replay` | 126,839 s | 4/4 | Réussi | Réussi |
| `shadow` | 115,256 s | 4/4 | Réussi | Réussi |
| `limited` | 116,150 s | 4/4 | Réussi | Réussi |

Chaque parcours a appliqué son premier diff dans un bac neuf et a
produit un `ExperienceRecord` distinct. Le diff avait la même empreinte
sur les quatre parcours. Le cycle candidat a duré **390,938 s sur 480 s**,
pause comprise. La fenêtre a affiché `notes-rbitnet-ocr v1.0.0` comme
version active et son graphe à quatre étapes. **Retour arrière** a
rétabli `notes-rbitnet v1.0.0` et son graphe à trois étapes. Le registre
confirme la promotion et le retour arrière. Les quatre bacs sont fermés.

Le rapport se trouve sous
`phase1-desktop-evolution/runs/8f724249-b66c-4557-a469-d9e7233d9489/result/report.json`
dans le dossier de preuves, et le journal sous
`phase1-desktop-evolution/registry.db`.

#### Priorité aux tâches interactives entre deux essais

Les lancements Notes et les préparations de projet du desktop utilisent
la même file pour Windows Sandbox. L'évolution est planifiée en arrière-plan.
Après l'arrêt confirmé du bac et la publication du rapport d'un essai,
la file interactive passe avant l'essai suivant ou la promotion. Elle
conserve son ordre d'arrivée. Le cycle garde son identifiant, le budget
continue à courir et le journal inscrit `interactive_priority`.
Les synthèses de la conversation passent aussi par cette file pour
sérialiser les chargements Rbitnet dans le desktop. Les plafonds de durée,
d'essais, de threads et de RAM sont réglables au lancement du desktop.

En CPU, une préparation de projet puis une tâche Notes sont entrées dans
la file pendant le premier essai candidat. Elles ont réussi dans des bacs
neufs en **22,124 s** et **90,917 s**. L'original du projet est intact et
la proposition attend son accord. Notes passe les quatre tests et SQLite
avec la version active au démarrage. L'essai suivant démarre après ces
deux exécutions. Les trois essais candidats passent, avec RapidOCR et
SQLite après relance. Le candidat est promu en **464,515 s sur 480 s**
et le retour arrière rétablit le parent. L'ensemble prend **554,782 s**
et les six bacs distincts sont fermés.

Le rejeu CUDA suit le même ordre et produit la même décision. Les trois
essais du candidat passent et le retour arrière est confirmé. Le cycle
dure **406,844 s sur 480 s** et l'ensemble **482,218 s**. Les journaux des
cinq lancements Rbitnet attestent chacun un appel cuBLAS réussi au
préremplissage. La qualification sélectionne CUDA dans le lanceur de
preuve côté hôte. Les bacs gardent le profil durci et RapidOCR sur CPU.

Le rapport, les journaux et le lanceur sont sous `phase1-interactive-priority/`.

#### Déclenchement après une préparation de projet

En mode évolution, la préparation de projet terminée envoie son verdict
à la file d'arrière-plan du desktop. Le succès et l'échec sont couverts
par les tests. La requête démarre un cycle sur le banc Notes figé, avec
une référence synthétique puis les trois essais candidats. Le même
budget s'applique à la référence et aux essais. Une version déjà promue
sans autre candidat compatible produit une attente motivée.

Le rejeu desktop a démarré par **Tester dans Windows Sandbox** sur le
projet jetable sans accord de réutilisation. La référence synthétique
passe en **87,326 s** et les trois essais candidats passent, avec les
quatre tests, RapidOCR et le contrôle SQLite après relance. Le candidat
est promu en **441,813 s sur 480 s**. La fenêtre affiche la nouvelle
version active. La préparation et les quatre exécutions Notes utilisent
cinq bacs distincts, tous fermés à la fin.

Le registre Notes contient un seul déclenchement et quatre
`ExperienceRecord` synthétiques. Une recherche des marqueurs distinctifs
du fichier source, du nom et du diff dans le journal, le registre et les
artefacts texte du cycle ne retrouve aucun de ces éléments. Le registre de
collecte du projet est absent de ce rejeu. La proposition et le journal
d'approbation restent dans le dossier de travail du projet. Les preuves
sont sous `phase1-project-synthetic/verification.json`.

### Écran desktop des données d’évolution

Le bouton **Données** ouvre le registre du parcours projet. Le dossier
sélectionné détermine le périmètre des accords, copies et demandes
d'effacement affichés. L'écran propose les deux catégories collectées
par le parcours projet, **Code source** et **Diffs**. Il affiche l'état
des accords et l'échéance de chaque copie sans lire son contenu.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.desktop `
    --data-db $registreProjet --data-project $dossierProjet
```

La révocation bloque les copies liées à l'accord sélectionné.
La demande d'effacement porte sur les copies de la même proposition
et leurs rapports de rejeu. L'écran affiche le motif d'attente et permet
de reprendre la même demande après résolution du problème.

Le 16 novembre 2026, une proposition Notes a été préparée dans un bac
neuf en **22,319 s**, puis le diff autorisé a été rejoué dans un autre bac
en **22,735 s**. Les contrôles ont refusé la collecte sans accord, la
collecte hors catégorie ou hors projet et la révocation inter-projets.
Révoquer l'accord Code source a bloqué son rejeu, et le diff restait
disponible sous son propre accord.

Un rapport de rejeu temporairement inaccessible a laissé la demande
en attente avec le motif affiché dans la fenêtre. Le rejeu a été refusé
dès l'enregistrement de cette demande. Après rétablissement de l'accès
au rapport, la reprise a effacé **deux copies et un rapport**. La même
demande apparaît comme effacée et les empreintes des fichiers d'origine
des deux projets concordent. Les opérations ont été vérifiées via le
service de l'écran et les états ont été observés dans la fenêtre.
Le rapport est sous `phase1-desktop-data/report.json` dans le dossier de preuves.

### Aperçu et approbation du diff dans le desktop

**Proposition du projet** ouvre une proposition de remplacement préparée pour
le projet sélectionné. La fenêtre affiche le diff unifié en lecture
seule, le fichier visé et le résultat du test dans Windows Sandbox.
La case d'approbation concerne l'empreinte de la proposition affichée.
Chaque tentative consomme cet accord. Si le projet a changé, la fenêtre
demande une nouvelle proposition et une nouvelle approbation.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.desktop `
    --project $dossierProjet --proposal $dossierProposition
```

Deux copies jetables du projet Notes ont servi à l'essai. Les propositions
ont passé le test de persistance SQLite dans des bacs neufs en **23,746 s**
et **22,910 s**. Les trois tentatives d'application ont été faites
depuis la fenêtre.

| Cas | Résultat | Contrôle du disque |
| --- | --- | --- |
| Case d'approbation décochée | Accord requis | Empreintes initiales conservées |
| Case d'approbation cochée | Diff appliqué | Fichier identique au remplacement testé, autres fichiers intacts |
| Fichier modifié après l'ouverture de l'aperçu et l'accord | Diff refusé, `project_changed` | Édition concurrente conservée |

Le rapport est sous `phase1-desktop-diff/report.json` dans le dossier
de preuves.

### Accords desktop de suppression et de déplacement

La même fenêtre affiche le fichier à supprimer ou les chemins de départ
et d'arrivée du déplacement. Les deux cases sont décochées à l'ouverture.
La première approuve l'empreinte de la proposition affichée. La seconde
autorise la suppression du fichier affiché ou son déplacement vers la
destination affichée. Chaque tentative remet les deux cases à zéro.
Le lanceur revérifie le projet et les chemins avant d'écrire.

Les propositions ont été préparées sur deux copies jetables, dans deux
bacs neufs. Le témoin vérifie la copie modifiée. La préparation a pris
**22,167 s** pour la suppression et **21,286 s** pour le déplacement.

| Accords donnés | Suppression | Déplacement |
| --- | --- | --- |
| Aucun | Refusée, fichiers intacts | Refusé, fichiers intacts |
| Proposition seule | Accord de suppression requis | Accord de déplacement requis |
| Proposition et opération | Source supprimée, témoin intact | Source absente, empreinte identique à destination, témoin intact |

Le déplacement a été testé depuis la fenêtre avec la destination
`archive/notes café.bin`. Pour la suppression, les contrôles affichés
ont été vérifiés dans la fenêtre et le gestionnaire du bouton a été
exercé sur la copie jetable dans le banc de test. Les empreintes
des fichiers ont été contrôlées après chaque refus et après application.
Le rapport est sous `phase1-desktop-file-operations/report.json`.

### Préparation du projet et accord de téléchargement dans le desktop

**Préparer un projet** lance le parcours de copie isolée pour un
remplacement, une suppression ou un déplacement. Il recueille les
fichiers autorisés et le script de test, puis ouvre la proposition
validée pour examen. Il affiche pour chaque demande de téléchargement
le nom, la version, l'URL, la licence et le SHA-256. L'accord est lié
à l'empreinte de la demande affichée. Une autre demande exige son propre
accord et un cache altéré échoue à la vérification avant installation.

Le test desktop a utilisé une wheel synthétique servie sur loopback.
Sans accord, le serveur a reçu **zéro requête**. Avec l'accord affiché,
il a reçu **une requête** et le cache a été publié. Après l'arrêt du
serveur, le gestionnaire de préparation a installé la wheel avec pip
24.2 hors ligne dans un bac neuf et validé le remplacement en **35,215 s**.
Le projet d'origine a conservé ses empreintes. Le rapport est sous
`phase1-desktop-dependencies/report.json`.

### Expiration des accords et reprise d'une application

Les demandes d'application et de téléchargement expirent au bout de
**30 minutes**. L'échéance apparaît dans l'interface. Une tentative à
l'échéance renvoie `approval_expired`, famille délai, avant écriture dans
le projet ou requête HTTP. Le CLI renvoie l'état `paused`. La reprise d'une
proposition dont le projet est intact émet une nouvelle demande et remet
les cases d'accord à zéro. Une demande de téléchargement expire de la même
façon. Une wheel déjà vérifiée peut encore être installée hors ligne.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.project renew-approval --project $projet --proposal $proposition
```

Le checkpoint SQLite de l'application est enregistré avant l'écriture.
Au redémarrage, une application interrompue après écritures peut être
confirmée par les empreintes et les absences attendues. Si l'état est
indéterminé ou a changé après application, le runtime s'arrête et donne
le motif. Les demandes de téléchargement consignent leur consommation
sur disque avant l'appel réseau.

Les décisions de projet et de téléchargement forment une chaîne de
digests SQLite séparée des propositions et de leurs checkpoints. Elle
conserve des métadonnées de décision et une action expurgée. Le contrôle
détecte une entrée modifiée et les déclencheurs SQLite bloquent les
modifications et suppressions ordinaires des entrées.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.project verify-audit --audit $journal
```

Les tests Windows couvrent l'expiration exacte, une échéance franchie
pendant le checkpoint, le refus de l'ancienne empreinte après reprise,
une interruption après l'écriture suivie d'une confirmation sans second
effet et zéro requête HTTP avec une approbation expirée.

Le rejeu CLI sur trois projets jetables prépare en bac un remplacement,
une suppression et un déplacement. Dans les trois cas, l'horloge de la
tentative est positionnée à l'échéance. Le CLI rend `paused` et les
fichiers restent intacts. La reprise émet une empreinte distincte et
l'ancienne est refusée. La suppression et le déplacement exigent à
nouveau l'accord propre à l'opération. Un arrêt du processus après
écriture et avant confirmation est ensuite injecté. Un nouveau processus
confirme l'effet enregistré sans réexécution et le fichier témoin garde
ses octets. Le journal chaîné contient **11 décisions vérifiées**.

Les préparations prennent **21,230 s**, **22,132 s** et **22,560 s**. Le
rejeu complet prend **77,500 s** et les trois bacs se ferment. Le rapport
est sous `phase1-project-approval-lifecycle/report.json`. La suite du dépôt
passe **156 tests**.

Dans la fenêtre desktop, un premier clic sans accord est refusé sur le
remplacement jetable. L'horloge de test est placée à l'échéance après
avoir coché l'ancien accord. Le bouton d'application se désactive et
la case se vide. **Nouvelle demande d'accord** affiche une autre échéance
avec la case décochée. L'application exige le nouvel accord. Le fichier
est intact avant ce dernier accord et le résultat correspond ensuite
au remplacement présenté. Le journal du rejeu contient trois décisions
vérifiées sous `phase1-project-synthetic/runs/proposals/`.

Dans le même desktop, une demande de wheel à l'échéance affiche
**Accord expiré** et désactive le téléchargement. Le renouvellement
affiche **À approuver** avec une échéance distincte et la case décochée.
Le clic sans nouvel accord est refusé et aucune demande n'est consommée.

### Refus des entrées secrètes et des tests dépendant du réseau

Le parcours projet refuse avant copie les chemins d'identifiants connus,
dont `.env`, ses variantes et les dossiers `.ssh` et `.aws`. Il refuse
également un fichier sélectionné qui contient un en-tête de clé privée.
L'exclusion s'applique aussi au fichier choisi comme remplacement.

Sur le projet jetable, sélectionner `.env` renvoie `secret_input` avant
création d'un dossier de proposition. Le test témoin passe en bac et
confirme l'absence de `.env` et de la variable sentinelle présente sur
l'hôte. Les tests qui exigent cette variable ou une connexion réseau
échouent tous deux avec le code invité `0x4714`. La sonde des canaux
confirme le profil durci dans les trois bacs. Les deux échecs laissent
les sources intactes et aucune proposition validée. Les trois bacs sont
fermés. Le rapport est sous `phase1-project-channel-refusals/report.json`.

Un objectif Notes ciblant `host-desktop` est aussi refusé au lancement,
avec `capability_unavailable` avant création d'un espace d'exécution.
Le rapport est sous `phase1-project-channel-refusals/host-desktop-refusal.json`.

Le journal append-only reçoit le résultat minimal d'un effacement, dont
le motif si l'effacement reste en attente. Deux copies d'une proposition
validée ont été collectées avec accord sur une copie jetable, puis effacées.
Le fichier source reste intact. La chaîne du journal est valide et
l'événement exclut les identifiants de copie, l'empreinte et le contenu.
La preuve est sous `phase1-project-channel-refusals/erasure-audit/`.

## Échéances de rétention appliquées

Le runtime utilise les fenêtres de **90 jours** pour les expériences
techniques minimisées, **30 jours** pour les contenus projet et **7 jours**
pour les captures et les archives. La collecte de contenus projet du
MVP porte sur le code source et les diffs. La classe captures est
définie par la politique et testée au calcul de l'échéance. Un fichier
`RetentionPolicy` peut être fourni par `AKASHA_RETENTION_POLICY`.

Les échéances stockées bornent le rejeu, la sauvegarde et la
restauration. Une copie restaurée garde la plus proche de l'échéance
d'origine et de celle portée par l'archive. Les tests vérifient la
reprise d'un registre d'expériences ancien, la purge à la limite exacte
et la suppression d'une copie avec son rapport de rejeu. Le traitement
des contenus arrivés à échéance réutilise le registre d'effacement.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.retention --db $registre --project $dossierProjet
```

L'appel déclenche la purge pour les périmètres indiqués.

### Sauvegarde quotidienne et rotation des archives gérées

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.daily_backup `
    --project $dossierProjet --db $registre --output-dir $dossierArchives `
    --consent $accordSauvegarde --watch
```

Le processus publie une archive par jour UTC et par projet. Un appel
sans `--watch` réalise le même contrôle une fois, pour un lancement par
un ordonnanceur externe. L'accord de sauvegarde distinct est vérifié
au moment de la publication. L'inventaire scellé par DPAPI protège l'identité du
fichier, l'échéance et l'empreinte du paquet. Une publication interrompue
peut être reprise au même jour. La rotation détruit d'abord les clés
de l'archive arrivée à échéance, puis son fichier enregistré si son
empreinte concorde. Une copie inaccessible laisse une rotation en attente.

Le test Windows a utilisé le vrai coffre DPAPI et une horloge contrôlée.
Il a vérifié le refus avec le seul accord d'évolution, une interruption
avant la publication, la reprise, l'idempotence dans la journée et la
suppression de l'archive et de ses clés à **sept jours**. Une archive
plus récente reste lisible. Après effacement de la source, cette
archive plus récente ne restaure aucune copie effacée.

## Qualification GPU sur RTX 4080 SUPER

Le pilote **610.88** expose **16 376 Mio** sur ce poste. Avec la
bibliothèque CUDA native chargée explicitement, le premier essai court
de Qwen3.5-2B a enregistré **186 GEMM quantifiés**, **2 806 GEMV GPU**
et **16 rejeux de graphe CUDA**. Mistral 7B a également produit des
compteurs GPU. Qwen3-8B a journalisé des appels cuBLAS réussis alors que
son champ `backend_accelerated` restait à `false`. Les indications
de disponibilité sont rapportées avec les preuves d'exécution.

Le rejeu de communication conserve Qwen3.5-2B, la consigne v2 et les
deux gabarits déterministes. Les six fiches donnent les mêmes textes
sur CUDA et CPU, avec **6/6** critères validés sur chaque backend. Le
temps de bout en bout, démarrage et arrêt du serveur compris, est de
**4,70 s sur CUDA** et **80,90 s sur CPU** pour ce rejeu. Les preuves
sont sous `phase1-gpu-qualified-library/` et
`phase1-gpu-communication/`.

Le parcours complet Notes, graine 742, a ensuite été rejoué avec CUDA
activé pour le serveur Qwen3-8B sur l'hôte. Le journal atteste un GEMM
cuBLAS réussi pour 183 tokens sur le chemin de préremplissage. Le premier
diff a été appliqué et les **4 tests**, RapidOCR et SQLite après relance
ont réussi. Le bac a été arrêté après **106,902 s**. Le précédent rejeu
CPU de la même graine prenait **106,589 s**. Les deux mesures sont
des observations individuelles. RapidOCR et les vérificateurs ont
continué en CPU dans le bac. Le rapport complet et le lanceur de
qualification sont sous `phase1-gpu-notes/`.

### Admission RAM et VRAM dans le lanceur Notes

Un bail d'inférence partagé entre processus de la session Windows
sérialise Rbitnet et l'observation ONNX Runtime. Rbitnet réserve son budget
sur l'hôte. Pour RapidOCR, le gestionnaire comptabilise les **4 096 Mio**
du bac déjà admis. Les limites globales par défaut sont **8 192 Mio**
pour la RAM du modèle et **8 192 Mio** pour la VRAM utilisée. Elles sont
configurables par `AKASHA_RAM_LIMIT_MIB` et `AKASHA_VRAM_LIMIT_MIB`.
Le CLI et le desktop sélectionnent CUDA avec `--cuda-library` et
`--model-vram-mib`. L'empreinte de la bibliothèque est vérifiée pour Notes.

Les sondes refusent un binaire manquant, un artefact incompatible et une
réservation de **8 193 Mio** au-dessus des plafonds globaux. Rbitnet
refuse aussi le chargement avec une limite de **1 024 Mio de VRAM**.
Pendant un chargement CPU réel, un second processus reçoit `inference_busy`
et le premier répond encore à `/ready`. Après libération, l'endpoint ferme
et le second processus obtient le bail.

| Graphe Notes, graine 742 | Total avec arrêt du bac | Bail Rbitnet | RAM hôte libre à l'admission | VRAM libre à l'admission |
| --- | ---: | ---: | ---: | ---: |
| CPU | 120,516 s | 49,032 s | 23 757 Mio | — |
| CUDA | 105,230 s | 32,924 s | 23 716 Mio | 12 100 Mio |

Avec les arguments normaux du lanceur, le premier diff passe dans chaque
bac, suivis des quatre tests, de RapidOCR et de SQLite après relance.
Le journal CUDA atteste le préremplissage cuBLAS. Les ressources sont
visibles dans l'inspecteur et exportées en OTLP lorsqu'elles sont mesurées.
La lecture du rapport CUDA depuis l'historique du desktop a confirmé
l'affichage des réservations, des mesures d'admission et de la durée du bail.
Les rapports et les sondes sont sous `phase1-model-residency/`.

### Configuration qualifiée

Les essais ont tourné sur Windows Pro `26320.9877`, un Ryzen 7 9800X3D
avec 16 processeurs logiques, 61,6 Gio de mémoire physique utilisable
et la RTX 4080 SUPER de 16 376 Mio. Le profil CPU configure 8 threads
Rbitnet. Le modèle peut réserver 8 Gio avec le bac de 4 Gio ouvert.
Les valeurs définissent le profil d'admission testé pour le banc.

Les deux GGUF, tokenizers, binaire Rbitnet et bibliothèque CUDA occupent
6,60 Gio. Le Python portable occupe 31,7 Mio et l'environnement hôte
285,2 Mio. Le cycle synthétique complet conserve 1,06 Gio de preuves,
dont les préparations instrumentées. L'enveloppe de référence est de
**10 Gio** pour ces dépendances locales et un cycle conservé, hors
installation Windows et archives supplémentaires de projets.

## Export des traces Notes vers OpenTelemetry

La couche locale émet un document OTLP JSON avec un span racine,
un span par invocation de nœud et des liens vers les dépendances
effectivement exécutées. Les versions des capacités et les erreurs
typées sont exportées. Le nœud modèle porte les attributs GenAI
épinglés en **1.37.0**. Les prompts, contenus, diffs et messages
d'erreur bruts sont exclus de la projection.
[Encodage OTLP JSON](https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding) ·
[Conventions GenAI 1.37.0](https://github.com/open-telemetry/semantic-conventions/blob/v1.37.0/docs/gen-ai/gen-ai-spans.md)

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.telemetry --report $rapportNotes --output $traceOtlp
```

L'export du rejeu Notes CUDA comporte le span racine et les quatre
spans d'exécution, dont l'appel Rbitnet. Il est sous
`phase1-gpu-notes/run-742/trace.otlp.json`.

## Audit des critères de sortie

La phase 1 est validée le **16 novembre 2026** sur le profil qualifié.
La suite `pytest tests contracts` passe **168 tests**.
La qualification porte sur le MVP Windows et les scénarios locaux du
[plan de développement](development-plan.md#phase-1--parcours-bureaucode-et-évolution-bornée-mvp).
Les preuves conservent les versions, les paramètres et les limites du
poste qualifié. Le transport d'inférence du MVP est local sur loopback.
Le contrat `RemoteInferenceGrant` et ses refus sont testés dans les
contrats. Aucune invocation d'inférence distante ne figure dans la campagne.

| Exigence | Validation |
| --- | --- |
| Entrée de phase, contrats, compilation et versions | [Phase 0](phase0_status.md#entrée-en-phase-1), tests des contrats et exécutions des graphes Notes et Tâches, [traces OTLP](#export-des-traces-notes-vers-opentelemetry). |
| Régression Notes, non-régressions et persistance après relance | [Trois graines et baseline](#trois-graines-et-baseline-fixe), puis [rejeu avec admission des moteurs](#admission-ram-et-vram-dans-le-lanceur-notes). |
| Transfert réservé, contrôle indépendant et absence de réutilisation | [v13 avec reprise](#transfert-tâches-v13-avec-reprise-guidée) et [v14 sur le runtime actuel](#transfert-tâches-v14-avec-admission-des-modèles). |
| Recherche et lecture bornée, édition et tests isolés | [Parcours projet et inspection du code](#parcours-projet-local-avec-approbation-du-diff), [refus réseau et secrets](#refus-des-entrées-secrètes-et-des-tests-dépendant-du-réseau). |
| Interface de suivi, diff, conversation, versions et commandes | [Graphe interactif](#interface-desktop-du-graphe-et-des-exécutions), [conversation et diff Notes](#conversation-et-lecture-du-diff-notes), [commandes d'évolution](#commandes-desktop-de-lévolution-notes). |
| Évolution automatique bornée, priorité, promotion et retour arrière | [Cycle et budgets](#rejeu-avec-le-plafond-ram-corrigé), [priorité CPU et CUDA](#priorité-aux-tâches-interactives-entre-deux-essais), [déclenchement projet et données minimisées](#déclenchement-après-une-préparation-de-projet). |
| Accords par projet et catégorie, révocation et effacement | [Consentement](#consentement-pour-lévolution-locale), [collecte et rejeu](#collecte-et-rejeu-du-parcours-projet-local), [effacement](#effacement-des-copies-dévolution-du-parcours-projet), [écran de données](#écran-desktop-des-données-dévolution). |
| Échéances, sauvegarde chiffrée et non-résurrection | [Échéances appliquées](#échéances-de-rétention-appliquées), [rotation quotidienne](#sauvegarde-quotidienne-et-rotation-des-archives-gérées), [restauration filtrée](#sauvegarde-locale-chiffrée-et-restauration-filtrée). Le cas des captures réelles est couvert au calcul de l'échéance. Le parcours actuel collecte code et diffs. |
| Autorisations, échéance, opérations idempotentes et journal minimal | [Accords et reprise](#expiration-des-accords-et-reprise-dune-application), [accord par téléchargement](#accord-par-téléchargement-et-installation-hors-ligne), [refus des canaux et du bureau hôte](#refus-des-entrées-secrètes-et-des-tests-dépendant-du-réseau). |
| Deux moteurs, mesures et admission des ressources | [Provenance Rbitnet](../../bench/measurements_phase0.md#provenance-et-licences), [sélection OCR](../../bench/vision_ocr_selection.md), [qualification CUDA](#qualification-gpu-sur-rtx-4080-super), [admission et profils](#admission-ram-et-vram-dans-le-lanceur-notes). |
