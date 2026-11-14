# Rapport d'inventaire — Phase 0 (2026-11-14)

Environnement et outils disponibles pour le banc bureau & code local.
Mesures relevées sur cette machine ; aucune valeur n'est un seuil.

## Machine

- OS : Windows 11 Professionnel Insider Preview (10.0.26220), 64 bits.
- CPU : AMD Ryzen 7 9800X3D, 8 cœurs.
- RAM : 61,6 Go.
- GPU : NVIDIA GeForce RTX 4080 SUPER, 16376 Mio (pilote 610.88) ;
  constatée aussi : carte graphique AMD intégrée + écran virtuel Meta.
- Disques (libre) : C: 102,3 Go · D: 194,8 Go · E: 32,5 Go.
- Protocole Phase 0/1 : relevés CPU seul d'abord (inférence et essais,
  affichage Windows éventuellement accéléré), puis campagne GPU documentée
  en indiquant ce qui reste sur CPU (plan § « Matériel »).

## Chaînes de développement

- Python 3.12.7, venv projet `.venv` (tkinter 8.6, SQLite 3.45.3) ;
  pytest 9.2.0 dans la venv. Lançable via `.\.venv\Scripts\python.exe`.
- Node.js v22.20.0 (+ npm).
- Git 2.49.0 (dépôt initialisé, sans commit au moment du rapport).
- .NET SDK 9.0.320 ; Rust 1.99.1 (rustc + cargo).
- Docker 29.0.1 présent (harness conteneur non évalué en Phase 0).
- VS Code présent (`code`).
- Python : `pillow`, `onnxruntime`, `pydantic`, `jsonschema`, `requests`
  déjà importables ; pas de module OCR (`tesseract`, `easyocr` absents).

## Inférence locale

- Ollama 0.40.15, modèles présents au moment du rapport :
  - `rbitnet-bench-qwen3-8b:q4_k_m` (8,2 B, Q4_K_M, contexte 40 k, outils) —
    rôle communication/code candidat.
  - `rbitnet-bench-llama32-1b:q4_k_m` (1,2 B, Q4_K_M, contexte 128 k, outils).
  - Autres présents : `qwen3.5:9b`, `qwen3.5:2b`, `tinyllama`, `qwen2.5:0.5b`,
    `devstral`, `mistral-small3.1`, `gl m-4.7-flash`, embeddings
    (`qwen3-embedding:4b`, `nomic-embed-text`, `bge-m3`, `snowflake-arctic-embed2`),
    `gpt-oss:20b`, `lfm2`, `x/z-image-turbo`.
- Rbitnet : aucune commande `rbitnet` trouvée — inventaire des capacités
  effectives (serveur/proxy, API, chargement, métriques) restant à faire
  en Phase 0 (plan § Phase 0).
- Vision/OCR : aucun modèle OCR dédié repéré localement ; second moteur
  local + modèle préentraîné à sélectionner avec versions, licences et
  ressources consignées (plan § Phase 0, spec §12.2).

## Isolement

- Windows Sandbox : présence non vérifiable sans élévation (commande
  `Get-WindowsOptionalFeature` refusée) ; le fichier `WindowsSandbox.exe`
  n'a pas été trouvé par ce chemin. À trancher en Phase 0 :
  Sandbox jetable (`.wsb` durci, réseau désactivé) contre checkpoint de VM.
- Contenants du banc : copies de travail sous `bench/`, bases SQLite
  jetables (`--reset`), `*.db` ignorés par git.

## Banc livré (état figé)

- `bench/notes/` — référence : `notes_store.py` fautif, `notes_app.py`
  (tkinter), `tests/test_notes.py` (1 régression + 2 caractérisations),
  `verifiers/verify_notes.py` (contrôle SQLite direct).
- `bench/tasks/` — transfert réservé : `tasks_store.py` fautif (filtre),
  `tasks_app.py` (tkinter), `tests/test_tasks.py`,
  `verifiers/verify_tasks.py` (état initial scellé `SEED`).
- Résultat observé sur versions fautives : 3 échecs / 3 succès
  (`pytest bench -v`) ; vérificateurs en FAIL documenté.
- Contrôle positif : copies corrigées en scratch (`$env:TEMP`,
  non versionnées) → 6/6 tests PASS, vérificateurs PASS. Les corrections
  de référence ne sont pas fournies à l'agent.
- Applications GUI compilées (`py_compile` OK) mais non lancées dans
  cette session ; le parcours bureau (ouverture, saisie, fermeture réelle,
  réouverture) reste à exercer en Phase 1.
