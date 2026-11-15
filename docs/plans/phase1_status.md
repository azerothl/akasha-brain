# Phase 1 — Premier jalon du parcours Notes

La phase 1 démarre sur le banc Notes CPU validé en
[phase 0](phase0_status.md). Le premier jalon compile l'objectif structuré
du banc en un graphe versionné. La cible est la baseline fixe exécutée
dans Windows Sandbox pendant la phase 0.

## Registre et compilation

Le [registre initial](../../akasha_brain/capabilities.json) épingle
les capacités par identifiant et version. Un relevé d'évaluation lie
la capacité au banc vérifié. L'OCR du formulaire est déclaré dans
le registre en attendant son évaluation sur le parcours Notes.

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
`GoalSpec` de transfert. Les **61 tests** du parcours et des
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

[Plan de la phase 1](development-plan.md#phase-1--parcours-bureaucode-et-évolution-bornée-mvp)
