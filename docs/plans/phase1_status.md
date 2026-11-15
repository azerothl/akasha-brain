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

[Plan de la phase 1](development-plan.md#phase-1--parcours-bureaucode-et-évolution-bornée-mvp)
