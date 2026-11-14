# Rétention, sauvegarde, effacement — conception (spec §10.2, §10.5)

Conception à vérifier en Phases 0-2 ; décrit le MVP à construire, pas des
capacités implémentées. Schémas : `RetentionPolicy/1.0.0`,
`EvolutionConsent/1.0.0`, `ExperienceRecord/1.0.0` (champ `redacted`).

## Cycle de vie et clés

- Sauvegarde locale chiffrée quotidienne, fenêtre 7 j ; contenus réels
  inclus seulement sur accord distinct par projet et catégories.
- Clé maître par racine `AKASHA_HOME`, chiffrée au repos via DPAPI
  utilisateur Windows ; rotation avec rechiffrement, destruction de
  l'ancienne génération après vérification.
- Effacement cryptographique : détruire la clé et toutes ses copies
  contrôlées ; ne vaut preuve que si chaque copie est traitée et vérifiée.

## Effacement et non-résurrection

- L'effacement ciblé contourne les références : retire le contenu et tous
  ses dérivés recensés (filiation obligatoire), ajoute un événement minimal
  au journal d'audit (sans contenu ni empreinte testable).
- Registre protégé de marqueurs de suppression, hors version à restaurer ;
  avant toute exposition d'une restauration, appliquer marqueurs et
  échéances ; registre absent ou invérifiable = restauration refusée.
- Sauvegardes : mêmes suppressions appliquées, jamais de réintroduction ;
  aucune suppression déclarée terminée tant qu'une copie contrôlée ou un
  dérivé demeure lisible. Échec de traitement = état « en attente » avec
  motif, jamais de succès annoncé.

## Critères de preuve (à outiller Phase 1-2)

- Relecture après suppression (contenu + dérivés illisibles), journal des
  opérations sans contenu, test de restauration n'exposant rien d'effacé,
  vérification des clés détruites. Besoin de replay ne crée pas d'exception.
