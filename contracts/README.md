# Contrats Akasha Brain — gel v0 (Phase 0)

Schémas JSON Schema 2020-12 versionnés, validateur runtime, bibliothèque
fermée de prédicats et vérification des grants (spec §5-6, §5.4, §6.1,
§13.6-13.7, §16.1).

## Disposition

- `schemas/<Nom>/v1.0.0.json` — schémas versionnés (`$id` `akasha://schemas/…/1.0.0`,
  SemVer exacte) : GoalSpec, SuccessPredicate,
  CapabilityManifest, ArtifactEnvelope, ExperienceRecord, RemoteInferenceGrant,
  RetentionPolicy, EvolutionConsent, BackupConsent et RetentionCopy.
- `akasha_contracts/` — `validate.py` (validation + erreurs typées),
  `errors.py` (taxonomie stable), `predicates.py` (évaluateurs fermés),
  `grants.py` (vérification des grants, refus par défaut).
- `tests/` — suite maintenue des contrats.
- `examples/` — deux GoalSpec du banc (parcours code, transfert).

[Contrat de rétention et restauration](retention_design.md).

## Gel v0 et support

Fenêtre de support : **majeur courant seul** (N=1) par schéma, fixée avant
ce gel. Changement cassant = majeur ; champ optionnel ajouté = mineur
(spec §16.1). `human_confirms` ne transite jamais par un jugement LLM.

## Exécution (venv du projet)

```powershell
.\.venv\Scripts\python.exe -m pytest contracts -v
```

Dépendance : `jsonschema==4.26.0` (PyPI, licence MIT vérifiée dans
`METADATA` après récupération), installée dans `.venv` sur accord explicite
de ce téléchargement le 2026-11-14 (spec §13.7). Prédicats `window_foreground` / `ui_element_state` sans
évaluateur en Phase 0 (retournent une erreur typée, jamais un succès) ;
`process_exit_zero` exécute une commande locale — réservé au bac isolé.
