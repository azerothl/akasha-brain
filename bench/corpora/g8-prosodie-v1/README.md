# Écoute des intonations françaises

[Ouvrir les neuf extraits à l’aveugle](ecoute-79ee9ff269b9/ecoute.html)

Le 19 novembre 2026, la deuxième phrase a donné un premier son disponible après 18,30 s pour le Piper actuel, 17,51 s pour le Piper ajusté et 10,76 s pour Qwen déjà chargé. Les deux temps Piper proviennent du contrôle isolé qui suit la préparation et les essais Qwen. La première mesure Piper actuel sur cette même phrase avait atteint 67,60 s pendant la préparation sur disque. Les mesures isolées sont des observations uniques et portent sur la configuration testée. Le rapport conserve tous les essais. [Chronométrages](../../results/g8-prosodie-79ee9ff269b9-latences.json) · [Vérification des niveaux et des WAV](../../results/g8-prosodie-79ee9ff269b9-verification.json)

Les trois textes de [phrases.json](phrases.json) sont communs aux trois synthèses. Ils couvrent une question suivie d’une correction, une opposition entre deux noms de ville et une réponse en plusieurs phrases. Le choix final revient à l’auditeur.

| Variante | Paramètres figés avant les rendus |
| --- | --- |
| Piper SIWIS medium, pilote G8 | Moteur 2023.11.14-2 et voix française du pilote, CPU sous Windows Sandbox, durée relative 1,1 et pause par défaut. |
| Piper SIWIS medium, ajusté | Même moteur, voix, appareil, texte et ponctuation. Durée relative 1,0 et pause entre phrases de 0,32 s. |
| Qwen3-TTS-12Hz-1.7B-CustomVoice | Voix Vivian, langue française, même consigne conversationnelle sur les trois textes, graine 7319. RTX 4080 SUPER, bfloat16, SDPA, modèle en mémoire après le premier appel. [Modèle officiel](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/tree/0c0e3051f131929182e2c023b9537f8b1c68adfe) |

Le chronomètre démarre à la demande, téléchargement exclu. Chaque chemin restitue le signal complet au lecteur. Le premier son disponible correspond au retour du signal augmenté du silence qui précède la première fenêtre de 10 ms au-dessus de −50 dBFS RMS. Cette mesure logicielle exclut le tampon de la carte son. Le premier appel Qwen inclut ses imports, son initialisation CUDA et le chargement des poids. Piper démarre un nouveau bac pour chaque phrase. Les temps décrivent ces chemins d’exécution sur le poste Windows.

Les WAV d’écoute sont mono, PCM 16 bits à 24 kHz. Un gain constant égalise le volume intégré (LUFS) sans comprimer la dynamique ni changer les pauses. La répartition A/B/C est tirée une fois par lot et équilibrée sur les trois phrases. La planche HTML fonctionne hors ligne et exporte le vote en JSON. La clé reste dans un fichier distinct pour dépouiller les réponses.

Depuis la racine du dépôt, `python -m bench.g8_piper_listening` rend les deux profils Piper. Le script [Qwen](../../g8_qwen_listening.py) fixe la révision, les bibliothèques et les paramètres de génération du rendu GPU local. Après ces passes, `python -m bench.g8_piper_listening --controle` rejoue la deuxième phrase dans les deux profils CPU. Enfin, `python -m bench.g8_blind_listening` produit les extraits anonymes, la planche, la vérification audio et les mesures. Les fichiers bruts et les poids restent dans le dossier local ignoré `.venv/g8-listening`.
