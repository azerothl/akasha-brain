# Sélection vision/OCR — état Phase 0

**Retenue et mesurée : RapidOCR ONNX 1.4.4** (second moteur local réel,
spec §12.2). Accord de téléchargement obtenu, installation le 2026-11-14
dans `.venv` uniquement : `rapidocr-onnxruntime==1.4.4` (Apache-2.0,
METADATA vérifiée), `onnxruntime==1.32.0`, `pillow==13.0.0`,
`numpy==2.5.4`, `opencv-python==5.0.0.93` (+ PyYAML, shapely, six,
flatbuffers, protobuf, pyclipper, tqdm).

## Constat machine (sans téléchargement)

- Python système : `pillow`, `onnxruntime`, `numpy` importables ; pas de
  `torch`, `transformers`, `easyocr`, `pytesseract`, `rapidocr_onnxruntime`.
- Binaire `tesseract` absent ; pas de dossier `Tesseract-OCR`.
- Venv projet : aucun paquet OCR.

## Shortlist

| Option | Source | Coût d'adoption | Réserve |
|---|---|---|---|
| RapidOCR ONNX | PyPI + poids ONNX auto-récupérés | pip dans `.venv` uniquement | Poids récupérés au premier usage (téléchargement à approuver aussi) |
| Tesseract local | Installeur EXE + `pytesseract` | Modification hôte (installation) | Plus lourd, approbation distincte |
| OCR Windows (WinRT) | Paquet `winrt` PyPI | pip dans `.venv` | API système, à évaluer |

Recommandation : RapidOCR ONNX (léger, CPU, ONNX déjà disponible côté
système). Approbation demandée : `pip install rapidocr-onnxruntime`
(versions épinglées, dépendances incluses) + récupération des poids au
premier usage.

## Mesure (2026-11-14, `bench/harness/measure_ocr.py`)

Image synthétique PIL (5 lignes : accents, tiret long, multiligne),
CPU seul : **0,6-0,8 s, 6 boîtes, tous les mots retrouvés après pliage
des accents** (comparaison insensible aux accents documentée dans l'outil).
Poids embarqués dans le wheel (aucun téléchargement séparé) :
détection `ch_PP-OCRv4_det_infer.onnx` (4,53 Mo,
`sha256:D2A7720D…42F49DA9`), reconnaissance `ch_PP-OCRv4_rec_infer.onnx`
(10,35 Mo, `sha256:48FC40F2…37384005`), classification
`ch_ppocr_mobile_v2.0_cls_infer.onnx` (0,56 Mo,
`sha256:E47ACEDF…6DAB185A`). Famille PP-OCRv4 (PaddleOCR, projet
Apache-2.0).

**Limite mesurée : le modèle de reconnaissance omet les accents**
(« réunion » → « reunion ») et peut couper un mot (« première » →
« premiere e »). Conséquence : l'OCR fournit une observation utile mais
n'est jamais l'oracle — le contrôle d'état indépendant décide
(spec §12.3). Comparaisons OCR en Phase 1 systématiquement pliées.

## Protocole restant (Phase 1)

1. Image synthétique via PIL (texte connu, sans affichage requis) → OCR →
   exactitude caractères/mots, temps mur CPU, RAM crête.
2. Capture réelle d'application du banc (Phase 1, parcours bureau) → même
   mesure + contrôle indépendant d'état (spec §12.3).
3. Consigner versions, licence du modèle, empreinte des poids.
