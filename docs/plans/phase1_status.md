# Phase 1 — Premier jalon du parcours Notes

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

## Parcours projet local avec approbation du diff

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

[Plan de la phase 1](development-plan.md#phase-1--parcours-bureaucode-et-évolution-bornée-mvp)
