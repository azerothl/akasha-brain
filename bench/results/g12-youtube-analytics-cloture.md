# G12 — Qualification YouTube Analytics sur Windows

La CLI s’est connectée à une chaîne autorisée via le navigateur Google. Le premier rapport de 28 jours contenait 26 dates. La fenêtre a été décalée pour se terminer au dernier jour disponible, puis la CLI a renvoyé les 28 jours consécutifs demandés.

## Comparaison avec YouTube Studio

La comparaison utilise l’export journalier Studio fourni par le propriétaire de la chaîne pour la même fenêtre. Les dates ont été rapprochées une par une. Les heures du CSV ont été converties en minutes sans arrondi intermédiaire.

| Contrôle | Résultat |
| --- | --- |
| Dates présentes dans les deux relevés | 28 sur 28 |
| Vues identiques | 28 sur 28, écart total nul |
| Écart absolu maximal de durée sur une journée | 1 minute |
| Écart cumulé de durée, CLI moins Studio | −13 min 24 s |

La CLI additionne les minutes entières reçues pour chaque jour. L’export Studio exprime la durée en centièmes d’heure. Les écarts observés sont compatibles avec ces résolutions. [Métrique YouTube Analytics](https://developers.google.com/youtube/analytics/metrics#estimatedMinutesWatched)

## Révocation

Avant la révocation, l’entrée du coffre Windows a été vérifiée. La CLI a ensuite reçu la confirmation de Google et renvoyé `google_revoked: true` avec l’état `revoked`. La référence a disparu du registre local et du Gestionnaire d’identification Windows. Une nouvelle tentative de rapport a échoué avec `connection_revoked`.

Le relevé conserve la méthode et les écarts. Les identifiants, les dates exactes, les totaux de la chaîne, les données journalières et les références aux identifiants OAuth restent privés.

[Configuration et rejeu](../../README.md#consulter-les-statistiques-dune-chaîne-youtube) · [Tests CLI et coffre Windows](../../tests/test_youtube_analytics.py)
