# Calibration de l’alerte de transcription française

L’unité de mesure est le segment affiché par le pilote. Un segment exact contient les mots de la référence dans le même ordre après normalisation Unicode, passage en minuscules et suppression de la ponctuation. Les accents restent significatifs. Une graphie en chiffres et sa transcription en lettres peuvent donc compter comme une erreur. L’alignement est calculé sur toute la phrase. Une suppression est attribuée au segment du mot suivant, ou au dernier segment en fin de phrase. Une absence totale de texte compte comme une abstention explicite.

Le [manifeste](g7-alert-v3.json) fige les identifiants, les phrases de référence, les niveaux de bruit et les empreintes des fichiers PCM. La sélection par empreinte utilise 60 phrases du lot français de développement de FLEURS pour le réglage et 45 du lot de test pour l’évaluation. Les identifiants de phrase sont disjoints entre les lots et des essais G7 précédents. Les clips courts ont entre 4 et 28 mots et durent au maximum 12 secondes. [FLEURS, Conneau et al., CC BY 4.0](https://huggingface.co/datasets/google/fleurs/tree/70bb2e84b976b7e960aa89f1c648e09c59f894dd/data/fr_fr)

Les voix du test sont mélangées à trois prises de son du sous-ensemble ESC-10 de Karol J. Piczak. Chaque ambiance est utilisée cinq fois à chacun des rapports signal/bruit de 8, 15 et 22 dB. Les pistes d’ambiance de cinq secondes sont converties en mono 16 kHz et répétées si nécessaire, avec une position de départ déterminée par l’identifiant de la voix. Il s’agit de mélanges contrôlés de sources réelles. Une conversation enregistrée sur place présenterait aussi les effets de la distance au micro et de l’acoustique de la pièce. [Version d’ESC-50 et crédits originaux](https://github.com/karolpiczak/ESC-50/blob/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6/LICENSE)

| Ambiance | Source |
|---|---|
| Feu | « lg fire5.wav », lgarrett, CC BY. [Freesound](https://freesound.org/s/17150/) |
| Pluie | « unlocki door to mod rain.wav », cognito perceptu, CC0. [Freesound](https://freesound.org/s/17367/) |
| Vagues | « Branding_kort.wav », HerbertBoland, CC BY. [Freesound](https://freesound.org/s/28135/) |

Le banc exécute whisper.cpp small sur le CPU Windows avec les mêmes paramètres français que le pilote. Une seule transcription par fichier sert aux deux règles. La grille fait varier la confiance minimale, la confiance moyenne et la tolérance au dépassement de fin de fichier. Les scores absents et les textes mal encodés gardent une alerte. Sur la calibration, on minimise les fausses alertes sous la contrainte de ne pas augmenter le nombre de passages erronés non signalés. Sur le test indépendant, le candidat doit réduire les fausses alertes sans augmenter les erreurs non signalées pour remplacer la règle du pilote.

Le réglage principal a conservé les seuils d’origine. Pour chiffrer le coût d’une diminution des alertes, un second réglage a été choisi sur les seules données de calibration, avant lecture du résultat indépendant. Parmi les candidats réduisant les fausses alertes sur la calibration, on minimise la moyenne du taux de fausses alertes parmi les passages exacts et du taux d’omissions parmi les passages erronés.

Pour reproduire le test, placer les archives et TSV français de FLEURS dans le cache du banc G7 et les trois WAV ESC-10 originaux dans un second dossier. Utiliser la même version du moteur et du modèle que le pilote. Fournir un troisième dossier temporaire pour les WAV dérivés et les sorties natives. Exécuter ces étapes depuis la racine du projet.

```powershell
python -m bench.calibrate_g7_alert prepare   $cacheG7 $sonsESC $dossierTemporaire
python -m bench.calibrate_g7_alert calibrate $cacheG7 $sonsESC $dossierTemporaire
python -m bench.calibrate_g7_alert lock-challenger $cacheG7 $sonsESC $dossierTemporaire
python -m bench.calibrate_g7_alert test      $cacheG7 $sonsESC $dossierTemporaire
python -m bench.calibrate_g7_alert compare   $cacheG7 $sonsESC $dossierTemporaire
```
