# Akasha Brain

MVP Windows d’un système agentique composé de modèles, d’outils et de compétences spécialisés. Le banc local permet de suivre le graphe d’une tâche, de vérifier une réparation et d’exercer l’évolution bornée. Les phases 0 à 6 sont qualifiées sur le banc bureau et code. [Audit de validation](docs/plans/phase6_status.md#audit-des-preuves-des-phases-0-à-6)

## Installer le MVP sur Windows

Utilisez Windows 11 x64 24H2 ou plus récent, sur une édition compatible avec Windows Sandbox et avec la virtualisation activée. Activez la fonctionnalité Windows Sandbox dans les fonctionnalités Windows ou avec `Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All` dans un PowerShell administrateur. Redémarrez si Windows le demande. [Installation de Windows Sandbox](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-install)

Ouvrez Windows Sandbox une première fois pour recevoir la mise à jour avec la CLI, puis vérifiez que `wsb.exe list --raw` fonctionne dans votre session Windows. [Version avec la CLI](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-versions)

Installez Conda pour obtenir le Python 3.12.7 x64 du banc avec Tcl/Tk. Installez Git for Windows et rendez `git` disponible dans PowerShell. Le protocole RapidOCR vérifie le binaire de Git `2.49.0.windows.1`. [Installation de Conda sous Windows](https://docs.conda.io/projects/conda/en/stable/user-guide/install/windows.html) · [Version de Git qualifiée](https://github.com/git-for-windows/git/releases/tag/v2.49.0.windows.1)

Pour initialiser un nouveau PowerShell, lancez `conda init powershell` depuis l’invite Miniconda puis rouvrez PowerShell. Clonez `main` et préparez l’environnement hôte. [Initialisation de Conda](https://docs.conda.io/projects/conda/en/stable/commands/init.html)

```powershell
git clone --branch main https://github.com/azerothl/akasha-brain.git
Set-Location akasha-brain

conda create --name akasha-brain-win --override-channels -c defaults `
    'python=3.12.7=h14ffc60_0' 'sqlite=3.45.3=h2bbff1b_0' 'tk=8.6.14=h0416ee5_0' `
    'libffi=3.4.4=hd77b12b_1' 'zlib=1.2.13=h8cc25b3_1' 'vc=14.40=h2eaa2aa_1' `
    'vs2015_runtime=14.40.33807=h98bb1dd_1'
conda activate akasha-brain-win
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install 'jsonschema==4.26.0' 'pytest==9.2.0'
.\.venv\Scripts\python.exe -m pip check
```

Préparez le Python portable que le lanceur copiera dans Windows Sandbox. Le bac reçoit la bibliothèque standard et Tcl/Tk. Le lanceur y configure les chemins Tcl/Tk et ajoute les dépendances nécessaires au scénario.

```powershell
$ErrorActionPreference = 'Stop'
$pythonHome = $env:CONDA_PREFIX
$pythonPortable = Join-Path $env:LOCALAPPDATA 'AkashaBrain\python-portable-3.12.7'
$lib = Join-Path $pythonPortable 'Lib'
New-Item -ItemType Directory -Path $lib -Force | Out-Null

$runtimeFiles = 'python.exe', 'pythonw.exe', 'python3.dll', 'python312.dll', 'LICENSE_PYTHON.txt'
foreach ($file in $runtimeFiles) {
    Copy-Item -LiteralPath (Join-Path $pythonHome $file) -Destination $pythonPortable
}
$nativeFiles = 'sqlite3.dll', 'tcl86t.dll', 'tk86t.dll', 'ffi.dll', 'zlib.dll', `
    'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'
foreach ($file in $nativeFiles) {
    Copy-Item -LiteralPath (Join-Path $pythonHome "Library\bin\$file") -Destination $pythonPortable
}
Copy-Item -LiteralPath (Join-Path $pythonHome 'DLLs') -Destination $pythonPortable -Recurse
foreach ($folder in 'tcl8.6', 'tk8.6') {
    Copy-Item -LiteralPath (Join-Path $pythonHome "Library\lib\$folder") -Destination $pythonPortable -Recurse
}
Get-ChildItem -LiteralPath (Join-Path $pythonHome 'Lib') |
    Where-Object { $_.Name -notin @('site-packages', '__pycache__') } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $lib -Recurse }

& (Join-Path $pythonPortable 'python.exe') -c 'import sqlite3, tkinter; print(sqlite3.sqlite_version, tkinter.TkVersion)'
```

## Lancer Notes

Fermez toute session Windows Sandbox ouverte avant de démarrer. Lancez le desktop depuis la racine du dépôt et cliquez sur **Lancer Notes**. La référence fixe doit afficher **Réussi · 3/3 étapes**, avec les quatre tests et le contrôle SQLite. L’historique est enregistré sous `%LOCALAPPDATA%\AkashaBrain\runs` par défaut. Passez `--runs` pour choisir un autre dossier.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.desktop --python-runtime $pythonPortable
```

### Générer le diff sur CPU et vérifier le bureau avec RapidOCR

Installez les versions OCR du manifeste. Récupérez le GGUF et le tokenizer aux révisions indiquées dans les mesures de phase 0, ainsi que le `rbitnet-server.exe` Windows du banc. Le lanceur vérifie les trois SHA-256. Le binaire accepté provient du build local documenté en phase 0 et doit être fourni avec le jeu d’artefacts qualifié. [Provenance des modèles et de Rbitnet](bench/measurements_phase0.md#provenance-et-licences) · [Empreintes attendues](docs/plans/phase0_status.md#inférence-cpu-et-réparation-des-notes)

```powershell
$ocr = (Get-Content -LiteralPath 'akasha_brain/protocols/notes-desktop-ocr-v2.json' -Raw | ConvertFrom-Json).ocr.packages
$ocrPackages = @($ocr.PSObject.Properties | ForEach-Object { '{0}=={1}' -f $_.Name,$_.Value })
.\.venv\Scripts\python.exe -m pip install @ocrPackages
.\.venv\Scripts\python.exe -m pip check

$moteur = 'C:\chemin\vers\rbitnet-server.exe'
$gguf = 'C:\chemin\vers\Qwen3-8B-Q4_K_M.gguf'
$tokenizer = 'C:\chemin\vers\tokenizer.json'
.\.venv\Scripts\python.exe -m akasha_brain.desktop --python-runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --rapidocr
```

Le parcours complet doit afficher **Réussi · 4/4 étapes**. Le graphe présente le premier diff vérifié, les quatre tests et SQLite. La dernière étape relance l’application Notes dans le même bac puis vérifie la note avec RapidOCR et SQLite. Si le lanceur signale des entrées différentes du protocole bureau figé, comparez Git, Python portable, les modèles ONNX et les DLL Visual C++ de `System32` au [manifeste RapidOCR v2](akasha_brain/protocols/notes-desktop-ocr-v2.json). Le [profil matériel qualifié](docs/plans/phase1_status.md#configuration-qualifiée) indique les ressources observées.

En ligne de commande, vous pouvez inspecter le plan Notes puis exécuter la référence fixe. Le rapport `report.json` est conservé dans le nouveau dossier de sortie.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain compile contracts/examples/goal_notes_regression.json
$rapport = Join-Path $env:LOCALAPPDATA "AkashaBrain\notes-$([guid]::NewGuid().ToString('N'))"
.\.venv\Scripts\python.exe -m akasha_brain run contracts/examples/goal_notes_regression.json `
    --python-runtime $pythonPortable --output $rapport
```

## Validation de Notes depuis un checkout propre

Le 17 novembre 2026, les deux parcours ont été rejoués depuis `main` à la révision `4ee3eff`, avec un environnement Conda et une venv neufs et le Python portable préparé selon les étapes ci-dessus. Chaque parcours a utilisé un Windows Sandbox neuf. [Révision testée](https://github.com/azerothl/akasha-brain/commit/4ee3eff1b20f14877fd528920933b7c69e4100f9)

| Parcours | Étapes | Tests | Vérification de la persistance | Durée totale |
| --- | ---: | ---: | --- | ---: |
| Référence fixe en ligne de commande | 3/3 | 4/4 | SQLite, code de sortie 0 | 49,717 s |
| Bouton **Lancer Notes** avec Rbitnet CPU et RapidOCR | 4/4 | 4/4 | SQLite, code de sortie 0, puis note retrouvée par RapidOCR et confirmée dans SQLite après relance | 124,032 s |

Dans le parcours complet, le premier diff Rbitnet, obtenu avec la graine 742, a été appliqué dans le bac et son empreinte a été vérifiée. Les deux bacs ont été arrêtés et le checkout de validation est resté propre.

## Documents

- [Spécification d’architecture](docs/architecture/brain-system-spec.md) — capacités, contrats, mémoire, évolution et autorisations.
- [Notes de recherche](docs/research/research-notes.md) — bibliographie annotée et implications pour le système.
- [Plan de développement](docs/plans/development-plan.md) — étapes et critères du MVP.
- [Validation du graphe complet Notes](docs/plans/phase1_status.md#graphe-complet-rbitnet-cpu-et-rapidocr-v2) et [configuration de l’évolution intégrée](docs/plans/phase6_status.md#raccordement-à-linterface-desktop).
