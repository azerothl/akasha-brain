# Qwen3-TTS résident sur la RTX 4080 SUPER

[Écouter les trois phrases à l’aveugle](ecoute-32d496d848c9/ecoute.html)

Le banc du 19 novembre utilise la voix Vivian de Qwen3-TTS-12Hz-1.7B-CustomVoice, les poids vérifiés du premier essai et le même [corpus français](../g8-prosodie-v1/phrases.json). Les trois versions de chaque phrase sont issues du flux réel. Deux consignes cherchent une fin de question plus marquée et une narration plus sobre. La consigne précédente sert de témoin. Les prises sont conservées dans l’ordre prévu, à volume égalisé.

## Délai jusqu’au premier son disponible

| Situation | Phrase entière | Streaming |
| --- | ---: | ---: |
| Phrase 1, démarrage à froid | 11,80 s | 10,57 s |
| Phrase 1, moteur en mémoire | 1,13 s | 0,25 s |
| Phrase 2, moteur en mémoire | 1,82 s | 0,25 s |
| Phrase 3, moteur en mémoire | 2,15 s | 0,26 s |

Chaque cellule est la médiane de trois essais. Les deux colonnes utilisent le même moteur accéléré, faster-qwen3-tts 0.3.2, CUDA bfloat16 et les mêmes paramètres. Le premier essai de chaque processus inclut l’import des bibliothèques, le chargement du modèle, la capture des graphes CUDA et la synthèse. Le cache disque du système reste en place. Les demandes suivantes réutilisent le modèle chargé. Le premier banc Qwen en phrase entière utilisait une autre implémentation. [Mesures précédentes](../g8-prosodie-v1/README.md) · [Moteur de streaming](https://pypi.org/project/faster-qwen3-tts/0.3.2/)

Le texte de chaque phrase est disponible en entier au départ. Le flux de sortie livre le PCM en blocs de quatre trames de codec. Chaque horodatage est pris après la copie des échantillons en mémoire hôte. Le seuil de son est fixé à −50 dBFS RMS sur 10 ms. Le calcul tient compte du silence initial et de l’arrivée des blocs. Il exclut la latence de la carte son. Sur les 18 demandes en streaming, les blocs sont arrivés assez vite pour une lecture continue en démarrant dès le premier bloc. L’écoute proposée assemble ces mêmes échantillons dans un WAV.

Pour reproduire, utiliser l’environnement GPU du premier banc avec `faster-qwen3-tts==0.3.2`. Lancer `python -m bench.g8_qwen_streaming MODE SESSION` dans six processus successifs avec `stream 1`, `full 1`, `full 2`, `stream 2`, `stream 3`, `full 3`. Chaque session réserve ses propres fichiers. `python -m bench.g8_stream_report` vérifie les blocs et calcule les médianes. `python -m bench.g8_blind_listening --stream-v1` prépare les pistes anonymes. [Mesures et horodatages bruts](../../results/g8-qwen-streaming-v1.json) · [Contrôles du lecteur et de son export](../../results/g8-streaming-32d496d848c9-verification.json)

Le contrôle indépendant par transcription retrouve les trois phrases de narration. Pour les questions, il hésite entre « jeudi » et « je dis », et restitue de façon variable « Camille », « pas celui de Lille » et « la prévenir ». L’écoute sert aussi à juger leur articulation.
