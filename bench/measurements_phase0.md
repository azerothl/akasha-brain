# Mesures Phase 0 — inférence CPU (profilage, pas preuve)

Protocole : invite fixe (« En une phrase : que doit faire une fonction
save_note ? »), `POST /api/generate` (`stream: false`,
`options: {num_gpu: 0}`), 3 passages par modèle, machine au repos relatif.
`ollama ps` confirme `100% CPU` (runner `llamacpp`) sur les deux modèles ;
le contexte effectif constaté est 8192 (contre 40 960 / 131 072 annoncés —
limite de configuration, pas du poids). La VRAM observée pendant les essais
(~5 Go) n'est pas attribuable à Ollama (affichage et autres processus).

## Résultats (2026-11-14)

| Modèle | Passage | Mur (s) | Tokens | Éval (ms) | Chargt (ms) |
|---|---|---|---|---|---|
| rbitnet-bench-llama32-1b:q4_k_m (1,2 B, Q4_K_M) | 1 | 1,3 | 61 | 1189 | 7 |
| idem | 2 | 0,7 | 35 | 663 | 8 |
| idem | 3 | 0,9 | 43 | 907 | 9 |
| rbitnet-bench-qwen3-8b:q4_k_m (8,2 B, Q4_K_M) | 1 | 54,9 | 425 | 49319 | 5387 |
| idem | 2 | 45,3 | 388 | 45181 | 8 |
| idem | 3 | 50,2 | 421 | 49990 | 9 |

Données brutes : `$env:TEMP/akasha-cpu-runs.json` (session de mesure).

## Lecture (3 essais = profilage, spec §12.2)

- Le 1 B répond en ~1 s CPU : candidat rôle communication/bac.
- Le 8 B (raisonnement activé) produit ~400 tokens en ~50 s CPU : trop
  verbeux pour une boucle interactive sans consigne de concision ou
  désactivation du raisonnement ; à cadrer avant tout seuil (spec §2.4).
- Licence : `qwen2.5:0.5b` annonce Apache-2.0 ; les deux modèles candidats
  n'exposent aucune licence via `ollama show` — provenance à compléter
  avant la Phase 4 (spec §19.4).
- Moteur réel : processus `llama-server` (un par modèle), 100 % CPU.
- RAM résidente mesurée (privée) : 1,2 Go (modèle 1 B), 6,2 Go (modèle
  8 B) — compatibles mono-poste 61,6 Go ; VRAM non sollicitée (CPU seul).
- Concurrence : 2 générations 1 B en parallèle, 2/2 réussies, mur 2,3 s
  (contre ~1 s en solo) — pas de sérialisation ni d'erreur.
- Reprise : `ollama stop` unitaire (n'accepte qu'un modèle par appel),
  `ollama ps` vide vérifié, rechargement à froid 1 B en 816 ms puis
  inférence OK (mur 1,1 s). Cycle arrêt → preuve d'éviction → reprise OK.
- Reste à mesurer (Phase 1) : saturation au-delà de 2 requêtes,
  campagne GPU documentée (spec §6.2, §12.2).
