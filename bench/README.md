# Banc d'essai — bureau & code local (Phase 0)

Deux applications Python tkinter + SQLite, chacune avec son dépôt, son état
initial figé, son test de régression et ses non-régressions (spec §12.3).

| Application | Rôle | Bug volontaire |
|---|---|---|
| [notes](notes/) | Référence (optimisation autorisée) | « Enregistrer » affiche la note et annonce le succès, mais ne persiste pas ; la note disparaît après redémarrage |
| [tasks](tasks/) | Variante de transfert (réservée, voir ci-dessous) | Le filtre « À faire » affiche aussi les tâches terminées |

## Isolation du transfert

La variante `tasks/` (dépôt, détails, vérificateurs, résultats) est **réservée
à la mesure du transfert**. Pendant l'optimisation des candidats, aucun de ces
éléments n'est fourni au modèle ou au graphe candidat. Lors de l'évaluation de
transfert, version active figée, bac distinct, auto-évolution désactivée
(spec §12.3).

## Disposition

Chaque application suit la même disposition :

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
