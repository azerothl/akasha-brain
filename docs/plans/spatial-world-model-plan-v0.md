# Plan de recherche sur le modèle du monde spatial v0

Ce plan traite la piste spatiale après G0. Il définit un protocole de recherche en simulation. Les décisions, la version des scénarios, les références et les vérificateurs restent consultables pour chaque essai. [Spécification, §9 et §17](../architecture/brain-system-spec.md)

## Critères d’entrée

- Reproduire les preuves de la phase 5 sur une copie isolée. Vérifier le gain de sélection à politique figée, les contrôles de transition et la détection des divergences.
- Fixer un profil CPU local et un jeu de graines de mise au point. Conserver la trace, l’état initial, les observations et les décisions dans un format versionné.
- Disposer d’une référence déterministe, d’un contrôle indépendant de l’état final et d’un mécanisme de remise à zéro. Un scénario doit retrouver le même état initial et la même séquence d’observations pour une référence et une politique figées.

[État, sélection et garde de la phase 5](phase5_status.md) · [Audit des phases 0 à 6](phase6_status.md#audit-des-preuves-des-phases-0-à-6)

## Simulateur de référence

Le premier simulateur sera un monde 2D discret, local et déterministe. Une grille contient des obstacles, des objets identifiés, des zones cibles et un agent simulé. Le moteur de simulation détermine les transitions et publie un instantané exact réservé à l’arbitre. L’agent reçoit une vue locale bornée avec positions relatives, temps de mesure et objets visibles. Une observation de profondeur ou de couleur synthétique peut être ajoutée après le palier symbolique pour tester le rôle d’un capteur.

Le contrat fixe les axes, l’origine, les unités, la portée d’observation et les identifiants. Une capacité peut proposer une pose ou une carte avec une incertitude et une provenance. Le vérificateur indépendant lit l’instantané du simulateur. Il calcule l’état final et les transitions admises à partir de la règle du scénario, avec ses propres assertions et fixtures.

| Cas | Observation de l’agent | Réussite vérifiée |
| --- | --- | --- |
| Rejoindre une zone en contournant un obstacle | Pose relative et grille locale | Agent dans la zone cible et zéro collision |
| Déplacer un objet simulé jusqu’à une zone | Objets visibles et relation de portage | Objet exact dans la zone et objets témoins préservés |
| Retrouver un objet après une occultation temporaire | Identifiants visibles, visibilité et temps | Identité retrouvée et pose finale dans la tolérance déclarée |
| Replanifier quand un passage simulé se ferme | Événement de changement et observation locale | Nouveau chemin valide ou arrêt motivé avant épuisement |
| Lever une ambiguïté entre deux objets similaires | Visibilité partielle et descripteurs | Identification confirmée ou demande de clarification, sans action sur l’objet ambigu |

## Expériences appariées

1. Exécuter un contrôleur de référence qui suit la grille observée et les préconditions. Un oracle de simulation fournit une borne supérieure et vérifie le scénario.
2. Garder la même politique de sélection et substituer successivement un prédicteur symbolique, un prédicteur candidat et un témoin dont les prédictions sont permutées à graine fixée. Mesurer les différences sur les mêmes entrées et horizons.
3. Évaluer des transitions à 1, 3 et 5 actions. Comparer la pose estimée, les objets, les relations et l’état terminal avec l’instantané indépendant. Répéter avec occlusions, observations vieillies et transitions invalides.
4. Figer les versions et le protocole, puis rejouer des cartes, perturbations et combinaisons d’objets réservées. Désactiver la réutilisation de ces résultats pour l’évolution. Conserver un diff de trace et un point de retour à chaque palier.

Les familles de cartes et les conditions de validation sont séparées entre développement et transfert. Les variantes réservées sont générées et scellées avant le choix des candidats. Les scénarios de développement servent à ajuster les limites de recherche et à estimer la dispersion. Les rejoueurs partent d’instantanés séparés et alternent l’ordre des variantes appariées.

## Métriques et seuils de passage proposés

| Mesure | Témoin et seuil de passage |
| --- | --- |
| Intégrité du simulateur et de l’arbitre | Concordance exacte des replays déterministes sur les graines d’étalonnage. Les témoins positifs atteignent le but et chaque témoin de faute est détecté. |
| Garde des transitions | Zéro transition illégale acceptée dans le corpus réservé de la garde. Publier la taille du corpus et la borne supérieure unilatérale à 95 % du taux de faux acceptés. |
| Prédiction | Rapporter l’erreur de pose par horizon, l’exactitude des relations et les erreurs d’identité. Le candidat réduit le taux d’erreur à horizon 1 face à la référence et au témoin permuté dans la comparaison appariée. |
| Choix d’action | Succès confirmé par l’état final et gain apparié dont la borne basse à 95 % dépasse zéro sur le corpus réservé. Une dégradation d’une famille critique bloque le passage. |
| Incertitude | Mesurer les taux d’erreur et d’abstention face aux observations manquantes, anciennes ou contradictoires. Fixer sur le jeu de développement la couverture minimale et le seuil d’abstention, puis les vérifier sur le transfert. |
| Coût | Rapport par nœud du temps mur, des latences p50/p95, de la RAM maximale et du nombre d’actions. Définir et versionner les limites d’exécution après le profilage de référence, avant l’évaluation réservée. |
| Retour arrière | Forcer un écart réservé après exposition simulée. Le retour à la politique de référence restaure le verdict et la version attendus sur le rejeu suivant. |

Ces seuils décrivent des critères de recherche. Le dossier d’essai fige l’échantillonnage, les limites de calcul et les tolérances de pose après le premier profilage. La garde et l’état final priment sur un gain moyen de sélection ou de temps.

## Livrables et revue

- Contrats d’observation, de prédiction et de décision avec champs, unités, fraîcheur, provenance et classes d’action.
- Simulateur et vérificateur indépendants, référence CPU, témoins négatifs et outils de replay avec données synthétiques.
- Rapport apparié avec les résultats réservés, les erreurs attribuées aux étapes, la trace du retour arrière et les critères d’abstention.
- Revue opérateur de ce plan avant fusion. Les essais ultérieurs restent dans le simulateur. Une éventuelle expérimentation physique fera l’objet d’un protocole dédié avec ses permissions, limites d’environnement et mécanismes d’arrêt.
