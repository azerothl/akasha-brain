# Akasha Brain

Proposition d’architecture pour un système agentique composé de modèles, d’outils et de compétences spécialisés, dont les connexions évoluent avec les résultats observés.

## Documents

- [Spécification d’architecture](docs/architecture/brain-system-spec.md) — vision, composants, contrats, graphe de capacités, modèle du monde, mémoire, auto-évolution, sécurité, évaluation et phasage.
- [Notes de recherche](docs/research/research-notes.md) — bibliographie annotée et implications de travaux sur JEPA, modèles du monde, orchestration, agents spécialisés, compétences et coordination.
- [Plan de développement](docs/plans/development-plan.md) — phasage opérationnel du prototype sur le banc bureau & code, distinct de la cible de fond spatiale.
- [Statut de la phase 0](docs/plans/phase0_status.md) et [démarrage de la phase 1](docs/plans/phase1_status.md).

## Compiler l'objectif Notes

Depuis la racine avec la venv du projet.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain compile contracts/examples/goal_notes_regression.json
```

## État

La phase 0 est validée sur le banc Windows CPU. La phase 1 démarre avec le registre de capacités et le compilateur de l’objectif Notes. La spécification est en v0.16 et le plan en v0.15 : le banc de référence du MVP est une application de notes annonçant une sauvegarde sans la persister ; une application de gestion de tâches dont le filtre « À faire » est incorrect sert de variante de transfert indépendante. L'évolution locale utilise par défaut le banc synthétique admissible et des résultats techniques minimisés ; les contenus réels et leurs dérivés exigent un accord explicite par projet et catégorie. Le MVP associe parcours bureau/code isolés, modèles préentraînés de communication, code et vision/OCR, Rbitnet et un second moteur local, interface desktop avec graphe consultable et évolution automatique bornée privilégiant la fiabilité. Le fonctionnement est d'abord vérifié en CPU seul, puis avec la RTX 4080 SUPER 16 Go sur les composants compatibles. Un grand modèle généraliste reste un secours ponctuel ; les appels distants nécessitent un grant précis, expirant et journalisé. Le journal d'audit reste limité aux métadonnées minimales et les contenus et dérivés sont effaçables. Les valeurs par défaut prévoient 90 jours pour les résultats techniques minimisés, 30 jours pour les contenus réels autorisés et dérivés, 7 jours pour les captures réelles et l'OCR associé, ainsi qu'une sauvegarde locale chiffrée quotidienne conservée 7 jours ; les contenus réels ne sont sauvegardés qu'avec un accord distinct par projet et catégorie. Le banc jetable dispose d'une autonomie contrôlée ; pour un projet réel, la proposition de modifications doit être validée avant application et les suppressions ou déplacements exigent un accord explicite au cas par cas. Les tests restent isolés, chaque téléchargement de dépendance demande un accord et le bureau réel est exclu du MVP. Les mécanismes de sauvegarde et de suppression, critères de preuve, modèles exacts et seuils mesurés restent à préciser (voir §19 de la spécification et le plan).
