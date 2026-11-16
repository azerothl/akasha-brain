# Banc d'essai — bureau & code local (Phase 0)

Deux applications Python tkinter + SQLite, chacune avec son dépôt, son état
initial figé, son test de régression et ses non-régressions (spec §12.3).

| Application | Rôle | Bug volontaire |
|---|---|---|
| [notes](notes/) | Référence (optimisation autorisée) | « Enregistrer » affiche la note et annonce le succès, mais ne persiste pas ; la note disparaît après redémarrage |
| [tasks](tasks/) | Variante de transfert initiale, exposée pendant la baseline humaine | Le filtre « À faire » affiche aussi les tâches terminées |
| [tasks_transfer_v2](tasks_transfer_v2/) | Variante évaluée à l'admission du graphe Notes figé | Le sélecteur « À faire » demande toutes les tâches |
| [tasks_transfer_v3](tasks_transfer_v3/) | Variante évaluée avec une tentative | Le prédicat SQL « À faire » inclut les tâches clôturées |
| [tasks_transfer_v4](tasks_transfer_v4/) | Variante évaluée avec reprise guidée | Le filtre « À faire » omet les tâches réouvertes |
| [tasks_transfer_v5](tasks_transfer_v5/) | Variante évaluée avec retour détaillé | Le filtre « À faire » omet les tâches dont la liste de contrôle est partiellement cochée |
| [tasks_transfer_v6](tasks_transfer_v6/) | Variante réservée, préparée après le gel du graphe avec protection du verdict initial | Le filtre « À faire » trie par identifiant au lieu de trier par échéance |
| [tasks_transfer_v7](tasks_transfer_v7/) | Variante réservée, préparée après le gel du graphe avec schéma SQLite | Le filtre « À faire » omet les statuts non terminaux autres que « Nouvelle » |
| [tasks_transfer_v8](tasks_transfer_v8/) | Variante réservée, préparée après le gel du graphe qui cible les filtres en échec | Le filtre « Terminées » affiche une tâche plusieurs fois si elle a plusieurs reçus de clôture acceptés |
| [tasks_transfer_v9](tasks_transfer_v9/) | Variante réservée pour éprouver la reprise avec le graphe `tasks-rbitnet@1.5.0` | Le filtre « À faire » inclut des tâches encore reportées ou bloquées par un prérequis |
| [tasks_transfer_v10](tasks_transfer_v10/) | Variante réservée avec le graphe `tasks-rbitnet@1.6.0` | Le filtre « Toutes » trie par identifiant au lieu de trier par responsable |

## Isolation du transfert

Les variantes de transfert, leurs dépôts, leurs vérificateurs et leurs résultats
sont **réservés à l'évaluation**. Chaque variante est évaluée avec la version
du graphe figée pour son protocole, dans un bac distinct et hors évolution
(spec §12.3).

À partir de `tasks-rbitnet@1.4.0`, le graphe attend un fichier `schema.sql`
qui contient le DDL utilisé par le contrôle indépendant pour initialiser
SQLite. Il fournit ce DDL à chaque tentative. Le contrôle charge les données
d'essai séparément depuis `state.json`.

À partir de `tasks-rbitnet@1.5.0`, chaque requête exige une modification
de la sélection ou de l'ordre pour les filtres en échec au dernier contrôle.
La trace associe les filtres ciblés à leur résultat dans le bac.

À partir de `tasks-rbitnet@1.6.0`, le lanceur transmet les écarts par
filtre à la reprise et conserve le premier diff dans les preuves locales.
Il utilise cette preuve pour écarter une proposition répétée.

## Disposition

Les deux bancs initiaux suivent cette disposition :

- `<nom>_store.py` — couche de stockage SQLite (c'est elle qui porte le bug).
- `<nom>_app.py` — interface tkinter ; lançable via `python <nom>_app.py [chemin.db]`.
- `tests/test_<nom>.py` — régression + non-régressions, état isolé (`tmp_path`).
- `verifiers/verify_<nom>.py` — scénario de référence + contrôle indépendant
  (lecture SQLite directe, sans passer par la couche testée) ; `--reset`
  reconstruit l'état initial figé.

## Exécution des tests

Depuis la racine du projet, avec la venv du projet :

```powershell
.\.venv\Scripts\python.exe -m pytest bench -v
```

État attendu sur les versions fautives figées : la régression échoue
(c'est le comportement attendu du banc), les non-régressions caractérisent
la faute. La correction de ces bugs est le travail des parcours code/bureau
(Phases 1+), pas de la Phase 0.
