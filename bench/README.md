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

Pour vérifier l’application Akasha et ses contrats, lancez la suite
depuis la racine du dépôt.

```powershell
.\.venv\Scripts\python.exe -m pytest tests contracts -q
```

## Rejeux des images headless

Les parcours CLI et MCP utilisent la chaîne commune de découverte,
de qualification et de validation PNG, puis Windows Sandbox ou
Bubblewrap selon l’OS du processus. Les rendus sont exécutés sur CPU.
La qualification Linux publiée utilise Ubuntu sous WSL2.

| Relevé | Parcours |
| --- | --- |
| [CLI Windows et Linux](results/image-windows-linux-v1.json) | Backend commun et export PNG Linux |
| [Windows sans fenêtre](results/image-windows-headless-v1.json) | CLI et conversation avec export HCS |
| [MCP Windows et Linux](results/image-mcp-headless-v1.json) | Client stdio, verdict et contenu image vérifié |
| [MCP à cache vide](results/image-mcp-cold-cache-v1.json) | Deux accords distincts, qualification et reprise du même selfie |

Le protocole à cache vide commence par un appel `image_start`.
Le client vérifie l’attente du moteur, puis sa persistance après
`image_resume` tant que l’artefact manque. Le terminal refuse
d’abord le moteur, puis accepte le moteur et refuse les poids,
puis accepte les poids. Deux reçus distincts sont contrôlés.
Le client reprend le même identifiant de tâche, récupère le verdict
et le PNG, puis recalcule le SHA-256 du fichier reçu.

Dans les rejeux publiés à cache vide, les réponses d’accord sont
simulées dans la CLI. La source locale fournit les octets des
artefacts épinglés déjà approuvés. La qualification et la génération
s’exécutent dans les bacs réels, hors ligne et avec les entrées
en lecture seule. Les relevés distinguent le temps total de celui
mesuré après les accords.

Les commandes d’installation et d’utilisation figurent dans le
[README principal](../README.md#générer-une-image-sans-fenêtre-en-cli).
Les contrôles et les transports sont décrits dans le
[profil des bacs](harness/sandbox_profile.md#exécution-image-sans-fenêtre-sur-windows-et-linux).
