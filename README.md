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
.\.venv\Scripts\python.exe -m pip install 'jsonschema==4.26.0' 'pytest==9.2.0' 'Pygments==2.21.0' 'pillow==13.0.0'
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

## Ouvrir Akasha Brain depuis Windows

Depuis la racine du dépôt, créez une fois le raccourci et enregistrez le chemin du Python portable.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1 -PythonRuntime $pythonPortable
```

Ouvrez **Akasha Brain** dans le menu Démarrer. Dans **Conversation**, indiquez le dossier à vérifier ou sélectionnez-le. Akasha examine les manifestes Python et npm, contrôle la syntaxe Python et affiche les tests repérés. Pour `check.py`, `verify.py`, `unittest` ou un projet JavaScript qui déclare `node --test` et dont les tests sont repérés, **Lancer les tests dans le bac** exécute les tests sur une copie isolée, hors ligne, et affiche le verdict. Le parcours JavaScript utilise `node.exe` depuis le `PATH` Windows.

Activez les demandes libres avec `-Communication @($moteur, $ggufCommunication, $tokenizer)` lors de la création du raccourci. Utilisez le GGUF Qwen3.5-2B Q8_0 qualifié et le moteur et le tokenizer épinglés du [banc de communication](bench/measurements_phase0.md#provenance-et-licences). Le démarrage direct accepte les mêmes chemins après `--communication`. Le modèle local propose un plan pour les résultats demandés. Vous pouvez demander de vérifier et de résumer un même dépôt en une phrase. L’examen statique indique quels tests peuvent être lancés et le résumé s’appuie sur la documentation et les manifestes du dépôt. Akasha peut aussi comparer deux documents texte ou Markdown du dossier choisi. Indiquez leurs chemins et mettez entre guillemets ceux qui contiennent des espaces. Lorsqu’un outil manque, la conversation le signale. L’exécution dans le bac et l’application d’un diff conservent leurs accords respectifs.

Après un résumé, écrivez « Fais-moi un résumé plus complet » pour approfondir le même projet. La vue détaillée consulte la documentation et les manifestes. Elle lit aussi une sélection des sources JavaScript ou TypeScript pour relier les écrans, les routes et leurs appels aux fichiers et lignes concernés. Cette analyse statique se fait en lecture seule.

Une capacité manquante déclenche une recherche locale et un relevé technique dans `runs/capability-recovery.sqlite`. Pour essayer la reprise automatique, choisissez un dossier contenant un PNG ou JPEG et écrivez « Lis le texte de capture.png ». Si les artefacts RapidOCR sont installés, Akasha valide l’adaptateur sur deux images synthétiques dans Windows Sandbox, puis reprend la demande dans un autre bac. Le texte restitué est limité à 96 octets par lecture. Akasha réutilise la qualification tant que les artefacts correspondent, et retire l’activation si le contrôle échoue à l’usage. Le registre conserve les décisions techniques et la preuve de qualification.

Depuis l’interface Windows, la qualification RapidOCR sur CPU et la première lecture ont pris **121,125 s**. Après redémarrage, Akasha a réutilisé la qualification et lu une deuxième image en **67,484 s**. Les entrées sont restées intactes et les 256 tests automatisés ont réussi. [Relevé de validation](bench/results/conversation-capability-recovery-v1.json)

Pour générer une image, écrivez « Génère une image d’un chat faisant un selfie devant un miroir ». Akasha cherche l’archive CPU et les poids épinglés dans son cache et dans le dossier Téléchargements. Il affiche la source, la licence, la taille et l’empreinte de chaque fichier manquant. **Autoriser ce téléchargement** vaut pour le fichier affiché. Une fois les deux SHA-256 vérifiés, Akasha qualifie SD-Turbo sur une image synthétique, puis reprend votre demande dans un bac neuf de 8 Gio, hors ligne. Sous Windows, le bac démarre sans fenêtre. Akasha reçoit le PNG 512 × 512 par la sortie standard de l’invité via `hcsdiag.exe`, vérifie sa taille et son empreinte avant décodage, puis affiche le résultat dans la conversation. La CLI image peut enregistrer le résultat avec `--output`. Si le modèle de communication local est configuré, Akasha l’utilise pour traduire la description en anglais. [Moteur CPU](https://github.com/leejet/stable-diffusion.cpp/releases/tag/master-955-b7a74e6) · [Poids et licence](https://huggingface.co/samoudi/sd-turbo-gguf)

### Générer une image sans fenêtre sous Linux

Utilisez Linux x86_64 compatible avec le binaire Ubuntu 24.04 du catalogue, un compte non privilégié, Python 3 système et Bubblewrap avec les espaces de noms utilisateur activés. Dans une venv, installez `jsonschema==4.26.0`, `Pygments==2.21.0` et `Pillow==13.0.0`.

```bash
python -m akasha_brain.image_cli \
  --prompt "A cat taking a mirror selfie with a smartphone visible in its paw" \
  --output selfie.png
```

La CLI indique la taille, la source, la licence et l’empreinte de chaque artefact manquant et attend un accord distinct dans le terminal. Les poids déjà présents et vérifiés sont réutilisés. `--runs` permet de choisir le dossier du registre et du cache `image-engine`. Le backend Linux vérifie le confinement avant de démarrer le moteur, avec les entrées en lecture seule et un espace temporaire privé. Le PNG sort par un flux borné. Akasha le vérifie, retire ses métadonnées et renvoie sa taille et son SHA-256 dans le relevé JSON. Le fichier de destination doit être nouveau.

Le rejeu du selfie a pris **85 s** depuis la conversation Windows avec la qualification en cache, avant l’extraction du backend commun. Sous Ubuntu WSL2, la CLI a refusé le téléchargement sans accord, vérifié l’archive Linux après accord, qualifié le moteur et exporté le PNG en **66,6 s** au total. Le fichier a conservé la même empreinte après copie. La suite Windows a passé 260 tests et les contrôles ciblés Linux en ont passé 7. [Relevé Windows et Linux](bench/results/image-windows-linux-v1.json)

Avec l’export Windows sans fenêtre, la CLI a qualifié le moteur et exporté le selfie en **103,6 s**. La conversation a réutilisé la qualification et affiché le même PNG 512 × 512 en **52,9 s**, avec le même SHA-256. Les deux rejeux ont utilisé la sortie standard HCS, avec le réseau désactivé et les entrées en lecture seule. [Relevé Windows headless](bench/results/image-windows-headless-v1.json)

Sur Documentalist (`4538575`), le résumé détaillé a lu 49 sources JavaScript et TypeScript. La relance a pris **0,328 s** et produit 12 références vérifiées, dont le filtrage de la recherche, l’instantané de publication et l’écriture chiffrée dans SQLite. Les 163 empreintes comparées et l’état Git sont identiques avant et après l’essai en lecture seule. [Relevé de validation](bench/results/documentalist-code-summary-v1.json)

Pour lire un fichier, écrivez `Lis value.py`. Pour tester un remplacement, saisissez `Remplace "VALUE = 7" par "VALUE = 11" dans value.py`, indiquez le chemin relatif d’un script de test existant, puis confirmez **Tester le remplacement**. Le verdict et l’aperçu du diff reviennent dans la conversation. **Examiner le diff** ouvre la fenêtre d’approbation avec le diff complet.

Pour exécuter la démonstration, écrivez « Lance le banc Notes » et confirmez. L’onglet **Exécutions** affiche le graphe, le détail des étapes et l’historique du banc Notes. **Préparer un projet** reste accessible pour un fichier de remplacement complet ou une opération sur les chemins.

Terminez la session Windows Sandbox éventuellement ouverte avant de lancer une tâche. La référence fixe doit afficher **Réussi · 3/3 étapes**, avec les quatre tests et le contrôle SQLite. L’historique du desktop est enregistré sous `%LOCALAPPDATA%\AkashaBrain\runs` par défaut.

Le desktop est aussi accessible depuis PowerShell. Passez `--runs` pour choisir le dossier de l’historique.

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

Pour retrouver ce parcours dans le menu Démarrer, recréez le raccourci avec `& .\scripts\install-windows.ps1 -Rbitnet @($moteur, $gguf, $tokenizer)`.

Le parcours complet doit afficher **Réussi · 4/4 étapes**. Le graphe présente le premier diff vérifié, les quatre tests et SQLite. La dernière étape relance l’application Notes dans le même bac puis vérifie la note avec RapidOCR et SQLite. Si le lanceur signale des entrées différentes du protocole bureau figé, comparez Git, Python portable, les modèles ONNX et les DLL Visual C++ de `System32` au [manifeste RapidOCR v2](akasha_brain/protocols/notes-desktop-ocr-v2.json). Le [profil matériel qualifié](docs/plans/phase1_status.md#configuration-qualifiée) indique les ressources observées.

En ligne de commande, vous pouvez inspecter le plan Notes puis exécuter la référence fixe. Le rapport `report.json` est conservé dans le nouveau dossier de sortie.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain compile contracts/examples/goal_notes_regression.json
$rapport = Join-Path $env:LOCALAPPDATA "AkashaBrain\notes-$([guid]::NewGuid().ToString('N'))"
.\.venv\Scripts\python.exe -m akasha_brain run contracts/examples/goal_notes_regression.json `
    --python-runtime $pythonPortable --output $rapport
```

## Utiliser Akasha Brain depuis un agent

Installez le SDK MCP dans la venv du projet, puis déclarez le serveur dans votre client MCP local. Le serveur utilise les entrées et sorties standard du processus. [Configuration d’un client MCP](https://py.sdk.modelcontextprotocol.io/get-started/real-host/)

```powershell
.\.venv\Scripts\python.exe -m pip install 'mcp==2.0.1'
```

Adaptez les chemins absolus de cet exemple au dépôt.

```json
{
  "mcpServers": {
    "akasha-brain": {
      "command": "D:/dev/akasha-brain/.venv/Scripts/python.exe",
      "args": ["D:/dev/akasha-brain/scripts/akasha-mcp.py"]
    }
  }
}
```

L’agent peut appeler `notes_plan`, puis `notes_start` pour obtenir un identifiant et `notes_status` pour suivre la tâche jusqu’au verdict. Le résultat indique les tests, SQLite et, si le parcours le produit, le diff vérifié. Ces appels opèrent sur le banc synthétique Notes dans Windows Sandbox.

Le serveur relit le dossier Python portable enregistré par l’application. Les arguments `--python-runtime`, `--rbitnet` et `--rapidocr` permettent de configurer son lancement. Les rapports MCP sont conservés sous `%LOCALAPPDATA%\AkashaBrain\agent-runs` par défaut.

### Préparer un diff sur un projet réel

Ajoutez `"--project", "D:/chemin/vers/le-projet"` aux `args` du serveur MCP. Ce dossier détermine le projet accessible à l’agent. Le répertoire des propositions doit se trouver en dehors de ce projet.

1. Utilisez `project_inspect` avec un chemin relatif pour lire le code nécessaire.
2. Appelez `project_prepare` avec `target`, le texte UTF-8 `replacement`, le script de test `test` et, si nécessaire, les chemins relatifs `inputs`. Le serveur teste ce remplacement dans une copie isolée dans Windows Sandbox et renvoie `proposal_id`.
3. Appelez `project_status` avec cet identifiant. Une proposition validée renvoie `awaiting_approval`, le diff vérifié, son SHA-256, le verdict du bac et `proposal_path`.
4. Dans **Proposition du projet**, choisissez le dossier du projet et ouvrez `proposal_path`. Examinez le diff, cochez **J’approuve ce diff pour ce projet**, puis cliquez sur **Appliquer le diff**. L’exécuteur vérifie l’accord et l’état du projet avant le remplacement.

Sur un projet jetable, un client MCP a récupéré le diff vérifié dans Windows Sandbox et le même verdict après reconnexion. La fenêtre Windows a refusé l’application sans accord, puis appliqué le diff après approbation explicite. Le journal contient les deux décisions, et l’index et le commit Git du projet ont été préservés. [Relevé de validation](bench/results/mcp-real-project-v1.json)

### Validation de la conversation et du serveur MCP

Le 17 novembre 2026, le parcours lancé depuis la conversation a renvoyé quatre tests réussis et un verdict SQLite positif en **46,916 s**. Un client MCP local a lancé le parcours Rbitnet CPU et RapidOCR et a reçu le verdict `passed` en **138,147 s**, avec quatre tests réussis et la persistance confirmée après relance. Les 797 octets du diff renvoyé correspondent au premier diff appliqué et vérifié dans le bac. Les deux Windows Sandbox ont été arrêtés. [Relevé des deux essais](bench/results/windows-interface-mcp-notes-v1.json)

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
