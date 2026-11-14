# Statut Phase 0 — relevé des livrables (2026-11-14)

Référence : plan § Phase 0 (`docs/plans/development-plan.md:46-66`).
Légende : FAIT (preuve jointe) · PARTIEL (mesure ou décision restante) ·
ATTENTE (action utilisateur requise).

## Contrats et tâches représentatives

- FAIT — 8 schémas gelés v0 (`contracts/schemas/`, `$id` versionnés,
  SemVer exacte, fenêtre de support = majeur courant) : GoalSpec,
  SuccessPredicate (ensemble fermé, profondeur ≤ 2), CapabilityManifest
  (R0-R3, permissions normatives, sandbox, resource_profile, uncertainty),
  ArtifactEnvelope, ExperienceRecord (audit minimal vs contenus effaçables),
  RemoteInferenceGrant, RetentionPolicy (90/30/7 j, sauvegarde chiffrée
  quotidienne 7 j), EvolutionConsent. Validateur runtime + registre local,
  erreurs typées 7 familles, prédicats fermés évalués sur l'état réel,
  autorisation hors modèle + grants (refus par défaut). Suite maintenue :
  **27/27 PASS** (`pytest contracts -q`). Exemples GoalSpec du banc.
- FAIT — Dépendance unique `jsonschema==4.26.0` (MIT), installée dans
  `.venv` sur accord explicite du 2026-11-14, consigné (`contracts/README`).
- FAIT — Banc figé : `bench/notes` (référence, bug sauvegarde) et
  `bench/tasks` (transfert réservé, bug filtre), tests + vérificateurs
  indépendants. Attendu observé : 3 échecs / 3 succès sur versions fautives.
- FAIT — Correction de référence scellée (`bench/reference/`, jamais
  fournie aux candidats) ; contrôle positif 6/6 en scratch.
- FAIT — Baseline fixe mesurée : `bench/run_baseline.py` → BASELINE PASS,
  localisation (2 échecs) → réparation → validation (3 passed +
  vérificateur PASS), **temps mur 1,3 s** (métrique de coût primaire §15.1).

## Modèles et mesures

- FAIT — Candidats CPU : `rbitnet-bench-qwen3-8b:q4_k_m` (~50 s / ~400
  tokens, raisonnement verbeux à cadrer) et
  `rbitnet-bench-llama32-1b:q4_k_m` (~1 s) sur Ollama, `100% CPU` vérifié
  (`bench/measurements_phase0.md`, 3 passages chacun, données brutes en
  `$env:TEMP/akasha-cpu-runs.json`). Licences des deux candidats non
  exposées → provenance à compléter avant Phase 4.
- FAIT — Rbitnet inventorié : `rbitnet-server.exe` 0.2.0 (build local),
  contrat HTTP vérifié en stub (`/health`, `/ready`, `/v1/models`,
  `/metrics` Prometheus, `/v1/chat/completions` OpenAI-compatible) ;
  GGUF natif `ggml-model-i2_s.gguf` (1,2 Go) présent mais chargement réel
  non démontré (serveur resté en stub : config modèle/tokenizer à instruire,
  flux d'installation `rbitnet models install` non exécuté — aucun
  téléchargement sans accord).
- ATTENTE — Vision/OCR : rien d'exploitable sans téléchargement
  (constat consigné, shortlist + protocole prêts :
  `bench/vision_ocr_selection.md`). Accord demandé le 2026-11-14, resté
  sans réponse. Reposera la question à la reprise.
- FAIT — Ressources et reprise : moteur `llama-server` identifié
  (100 % CPU), RAM résidente 1,2 Go (1 B) / 6,2 Go (8 B), concurrence 2×1 B
  OK (2,3 s), cycle arrêt → éviction vérifiée → reprise à froid 816 ms
  (`bench/measurements_phase0.md`). Reste Phase 1 : saturation >2
  requêtes, campagne GPU.

## Harness et autorisations

- FAIT (artefacts) / PARTIEL (démarrage) — `bench/harness/` :
  profil durci `akasha-bench.wsb` rédigé et validé automatiquement (PASS),
  procédure d'import/export (`sandbox_profile.md`), binaire présent après
  activation + redémarrage, harness PASS. **Non démontré : démarrage d'une
  session par Akasha** — `WindowsSandbox.exe` (profil durci comme défaut)
  se termine en <10 s sans fenêtre ni worker visible. Une session
  `vmmemWindowsSandbox` vit sur le poste mais appartient vraisemblablement
  à `codex-windows-sandbox-service` (outillage tiers actif) : laissée
  intacte comme processus étranger vivant. J'ai arrêté des processus
  `WindowsSandboxServer/RemoteSession` pendant l'investigation — ils
  appartenaient peut-être à cette session tierce : perturbation possible,
  signalée, à vérifier côté tiers. En conséquence, le checkpoint VM reste
  le harness primaire ; le bac jetable exige un démarrage Akasha prouvé
  (Phase 1).
- FAIT — Matrice d'autorisation R0-R3 testée (8 tests : accords, refus
  typés, escalade `destructiveHint`, classe inconnue = R3).

## Harness et observation (complément 2026-11-14)

- FAIT — Couverture accessibilité vérifiée sans dépendance :
  `bench/harness/check_uia.ps1` (lecture seule) + constat agrégé
  (`bench/harness/uia_coverage.md`). COM `CUIAutomation` non enregistré
  sur ce poste → repli managé `UIAutomationClient` opérationnel (34
  éléments de premier niveau, 5/5 fenêtres nommées lisibles). Titres de
  session réelle non versionnés (JSON en TEMP uniquement).
- FAIT — Conception rétention/sauvegarde/effacement
  (`contracts/retention_design.md`) : cycle de vie des clés (DPAPI),
  effacement cryptographique, registre de marqueurs, critères de preuve ;
  mécanismes à vérifier en Phases 0-2.

## Reste pour clore la Phase 0 (côté utilisateur)

1. Activation Windows Sandbox (avec élévation) ou confirmation du
   checkpoint VM comme harness unique.
2. Baseline humaine chronométrée (`bench/baseline_human.md`, ~15-30 min).

Point 1 soldé le 2026-11-14 : RapidOCR ONNX 1.4.4 installé sur accord
(`bench/vision_ocr_selection.md`, mesure CPU 0,6 s, limite accents
documentée).

Sortie Phase 0 (plan) : baseline mesurée ✓, schémas gelés v0 ✓, métrique
de coût fixée (temps mur) ✓, premiers seuils dérivés des mesures ✓
(1 B ~1 s, 8 B ~50 s verbatim) — seuils d'acceptation restant à fixer
après la baseline humaine et la mesure OCR.
