# G7 · Français sur CPU Windows

**Recommandation du 18 novembre 2026.** Intégrer whisper.cpp small multilingue comme candidat G7 sur Windows. Le profil atteint 45 erreurs pour 176 mots, soit une erreur au-dessus du plafond de 44 fixé pour ces huit extraits. Sa qualification par défaut reste ouverte. [Mesures, hypothèses et segments par exécution](../../results/g7-asr-fr-cpu-v1.json)

| Mesure sur la parole réservée | whisper.cpp v1.8.3 small | VibeASR.cpp BitNet |
| --- | ---: | ---: |
| Erreurs / mots | 45 / 176 (25,57 %) | 85 / 176 (48,30 %) |
| Parole propre | 22 / 133 (16,54 %) | 42 / 133 (31,58 %) |
| Bruit ajouté | 23 / 43 (53,49 %) | 43 / 43 (100 %) |
| Temps moyen du lot de 63,36 s | 28,77 s | 32,47 s |
| Temps par minute audio, chargement inclus | 27,24 s | 30,75 s |
| Pic résident du processus | 648,13 Mio | 4 216,17 Mio |
| Chargement médian déclaré par le moteur | 287,5 ms | 734,7 ms |
| Mentions de noms retrouvées intégralement | 3 / 6 | 1 / 6 |
| Fichiers avec segments ordonnés et bornés | 8 / 8 | 0 / 8 (profil texte) |

Machine : AMD Ryzen 7 9800X3D. Les transcriptions des huit phrases sont identiques entre passages pour chaque moteur. Les horodatages ont été vérifiés pour l’ordre et les bornes temporelles ; la précision acoustique de chaque frontière reste à mesurer. Sur le silence, whisper.cpp produit trois points à chaque passage et VibeASR.cpp une chaîne vide. Un essai diagnostique du profil JSON de VibeASR.cpp sur l’extrait de développement a produit une sortie vide. Les mesures comparatives portent sur son profil texte.

Pour le premier adaptateur, traiter explicitement le silence et les segments uniquement ponctués. Évaluer ensuite le profil intégré sur un nouveau lot français réservé, avec davantage de bruit et de noms propres. Les huit phrases de lecture et le bruit blanc représentent un essai pilote.

Gel du 18 novembre 2026. Les deux CLI reçoivent les mêmes WAV mono PCM16 à 16 kHz. Le manifeste contient les références, les empreintes des WAV et les identifiants de phrases. Un extrait de développement précède huit phrases réservées (quatre voix étiquetées masculines, quatre féminines). Deux phrases réservées reçoivent un bruit blanc déterministe à 10 dB. Un silence numérique de trois secondes sert de contrôle distinct. Les références incluent des noms propres et du vocabulaire scientifique.

Les lectures proviennent de FLEURS, Conneau et al., Google, sous licence [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Les WAV distribués ici ont été convertis de flottant en PCM16. Le bruit et le silence sont des ajouts du banc. [Révision des sources et annotations](https://huggingface.co/datasets/google/fleurs/tree/70bb2e84b976b7e960aa89f1c648e09c59f894dd/data/fr_fr)

## Protocole avant rejeu réservé

- VibeASR.cpp CPU, poids BitNet officiels, décodage greedy en texte, limite de 256 jetons. whisper.cpp CPU, modèle multilingue small F16, français explicite, greedy sans reprise de température. Aucun contexte lexical fourni. Quatre threads par moteur. Un processus neuf par fichier, deux passages successifs avec ordre des moteurs alterné puis inversé. Le cache de fichiers Windows reste actif.
- WER micro = somme des distances de Levenshtein sur les mots / somme des mots de référence. Normalisation Unicode NFC, casse ignorée, accents conservés, ponctuation et apostrophes séparatrices, chiffres inchangés. Rapporter le premier passage pour la qualité et vérifier l’accord au second. Compter séparément noms attendus et texte sur silence.
- Temps principal = du lancement du processus à sa terminaison, chargement compris. RTF = temps cumulé / durée audio cumulée. Mesurer aussi les temps de chargement signalés par chaque moteur. Pic RAM = maximum du PeakWorkingSetSize natif Windows du processus pendant la mesure. Exclure développement et silence des agrégats de parole réservée.
- Pour proposer le premier profil à intégrer, viser WER ≤ 25 %, RTF total ≤ 1 et pic ≤ 4 Gio sur le réservé. À qualité voisine (écart ≤ 2 points), préférer le moteur le plus rapide disposant de segments exploitables. Les horodatages et le silence sont des contrôles de livraison distincts. Un échec sur ces contrôles doit être résolu et rejoué avant promotion.

Pour reconstruire les WAV, placer les archives FLEURS françaises dev/test et les TSV correspondants dans le cache sous leurs noms d’origine. Lancer `python -m bench.freeze_g7_french CACHE`. Le rejeu utilise `python -m bench.run_g7_asr CACHE RAPPORT.json`.

## Artefacts Windows du rejeu

Les chemins ci-dessous sont relatifs au cache. Les empreintes individuelles des deux exécutables, des poids et des DLL whisper figurent dans le [relevé natif](../../results/g7-asr-fr-cpu-v1.json).

- Extraire [whisper-bin-x64.zip v1.8.3](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.3) dans `whisper/` (SHA-256 de l’archive : `d824b1e37599f882b396e73f1ee0bfd5d0529f700314c48311dcbd00b803321d`). Placer [ggml-small.bin multilingue](https://huggingface.co/ggerganov/whisper.cpp/blob/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-small.bin) à la racine.
- Cloner [VibeASR.cpp](https://github.com/microsoft/VibeASR.cpp/tree/c4334009c88060f86cdbbd684b62662f710b6c20) dans `vibe/`, avec les sous-modules à la révision du dépôt. Le fork llama.cpp utilisé est `a2fdadc20285df2dce90402fca9264a93a8eb32f`. Placer à la racine les deux [GGUF BitNet de Microsoft](https://huggingface.co/microsoft/VibeVoice-ASR-BitNet/tree/66e78021ab8f5f06133d1ab421ba4d348bda97c9).
- Extraire [LLVM-MinGW UCRT x86_64 du 17 novembre 2026](https://github.com/mstorsjo/llvm-mingw/releases/tag/20261117) dans le cache. Depuis ce cache, placer son dossier `bin` en tête du PATH, puis compiler avec CMake et Ninja. L’inclusion de `cstdlib` fournit les déclarations de `free` et `realloc` à Clang 23.1.6.

```powershell
cmake -S vibe -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ "-DCMAKE_CXX_FLAGS=-include cstdlib" -DGGML_CUDA=OFF -DGGML_VULKAN=OFF
cmake --build build --target asr_infer -j 8
```
## Rejeu GPU sur la RTX 4080 SUPER

Sur les huit extraits parlés (63,36 s, 176 mots de référence), Whisper small obtient 44 erreurs de mots et VibeVoice Streaming 81, à froid comme à chaud. Sur l’ensemble de ces extraits, les temps cumulés de Whisper passent de 110,12 s à 1,19 s avec 964 Mio de VRAM au pic. Ceux de VibeVoice passent de 119,64 s à 12,66 s avec 5 528 Mio au pic. Sur le silence, Whisper renvoie une ponctuation et VibeVoice des balises de silence.

Le [relevé GPU](../../results/g7-asr-fr-gpu-v1.json) contient le texte brut, le texte évalué et les temps de chaque passage. Les huit fichiers de test servent au taux d’erreur global. Le fichier de développement et le témoin de silence sont mesurés à part. Les deux fichiers bruités du corpus CPU d’origine contiennent du bruit blanc ajouté à 10 dB.

Chaque moteur traite deux fois le même WAV. Le premier temps va de la création du processus à l’écriture du résultat. Le second couvre la nouvelle transcription avec le modèle en mémoire. Les fichiers du modèle peuvent être présents dans le cache de Windows. Les moteurs tournent à tour de rôle, et leur ordre alterne entre fichiers. Chaque mesure inclut la lecture et la préparation de l’audio. Le pic mémoire est le maximum observé de la mémoire vidéo locale du processus d’inférence sur l’adaptateur CUDA, interrogée environ toutes les 10 ms.

Whisper décode en français avec quatre threads hôtes, un seul candidat et sans repli en température. VibeVoice utilise le parcours fichier officiel de Microsoft en BF16 avec SDPA, sans vocabulaire suggéré, à température zéro et avec les fenêtres du modèle. Son encodeur acoustique échantillonne des représentations internes. Les deux sorties sont conservées et évaluées séparément. Les identifiants de locuteur et les balises d’ambiance reconnues sont retirés du texte évalué. Le calcul du taux d’erreur réutilise celui du banc CPU.

Pour relancer, préparer un cache GPU distinct du cache CPU. Extraire l’archive Windows CUDA 12.4 de whisper.cpp dans `whisper/`, placer les fichiers du modèle Streaming dans `model/` et le code de Microsoft dans `VibeVoice/`. Le Python d’inférence utilisé disposait de PyTorch 2.8.0+cu128, Transformers 4.57.1, Diffusers 0.35.2 et FFmpeg dans le PATH. Depuis la racine du projet, lancer `python -m bench.run_g7_gpu CACHE_GPU CACHE_CPU PYTHON_VIBE RAPPORT.json`. [whisper.cpp v1.8.3](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.3) · [Poids Streaming évalués](https://huggingface.co/microsoft/VibeVoice-ASR-Streaming-1.5B/tree/4262d23d8a539a6530cf64fbd0b1751ef9a30853) · [Code d’inférence évalué](https://github.com/microsoft/VibeVoice/blob/16fb2cb1217c9934a886e1948ffb06120caa2df5/demo/vibevoice_asr_streaming_inference_from_file.py)
