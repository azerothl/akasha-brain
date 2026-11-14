# Baseline humaine — protocole (à chronométrer)

Baseline de référence exigée par la spec §12.1 : mêmes tâches, humain
chronométré, conditions consignées. **Mesure à effectuer par l'utilisateur.**

## Tâches

1. **Notes** : ouvrir `bench/notes/notes_app.py` (base jetable en copie),

   reproduire l'échec (saisie → Enregistrer → fermeture réelle → réouverture
     → note absente), corriger `notes_store.py` pour persister, revérifier
     (note réapparaît exacte + non-régressions), lancer `pytest`.
2. **Transfert** : sur `bench/tasks/tasks_app.py`, vérifier chaque filtre

   et consigner les éléments visibles (sans modifier les états).

## Relevés par tâche

| Tâche                                    | Début | Fin   | Durée      | Réussite                                                                  | Remarques                                                                                                             |
| ---------------------------------------- | ----- | ----- | ---------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Notes (reproduire + corriger + vérifier) | 23:33 | 23:46 | 13 minutes | a moitié, les notes sont enregistrées, mais impossible de les ré afficher | on ne sait pas si la correction est limité a l'affichage des notes dans la liste ou l'affichage du contenu de la note |
| Transfert (vérifier 3 filtres)           | 23:50 | 23:53 | 3 minutes  | oui                                                                       | -                                                                                                                     |

Conditions à consigner : machine, date, applications ouvertes en fond,
interruptions. Ces durées calibrent les seuils et la comparaison
candidat/référence (spec §18) ; elles ne sont jamais importées d'ailleurs.

14/11/26 : cette machine (desktop_AI), et les applications déjà ouvertes (YouTube Studio, Cursor, les consoles Python). Un menu flottant est aussi ouvert en bas à droite de l’écran.
