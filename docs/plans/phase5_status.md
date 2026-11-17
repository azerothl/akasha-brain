# Phase 5 — Prédicteur d’état/action

La branche locale `codex/phase-5` inclut le commit `51ee863`, qui publie la porte Path A sur `codex/phase-4`. Le routage déterministe reste le réglage par défaut. Les [critères de sortie de la phase 4](phase4_status.md#clôture) ont été vérifiés.

## Premier DesktopState sur Notes

`DesktopState@1.0.0` relève le PID et la présence du processus, le titre et la visibilité de la fenêtre dans UI Automation, le propriétaire du premier plan Win32 et le propriétaire du focus UIA. Il précise la provenance de chaque groupe de champs et l’intervalle UTC de capture mesuré par l’hôte. Les valeurs des widgets et la capture d’écran sont déclarées non observées.

Le banc lance l’application Notes avec son stockage de référence dans un Windows Sandbox neuf. Le script renseigne une note synthétique et invoque le bouton Tk « Enregistrer ». Une sonde SQLite séparée ouvre la base en lecture seule, contrôle son intégrité et compare le titre et le contenu exacts de la note. La troisième observation suit la fermeture et la relance de l’application sur la même base.

| Observation | Processus Notes | Fenêtre visible, premier plan et focus UIA | SQLite |
| --- | --- | --- | --- |
| Avant enregistrement | Initial | Oui | Base intègre, vide |
| Après enregistrement | Même PID | Oui | Base intègre, une note exacte |
| Après relance | Nouveau PID | Oui | Base intègre, même note |

Les sondes ont confirmé la lecture seule du montage hôte, l’écriture dans le dossier temporaire invité et l’absence de route réseau par défaut. Le profil désactive la redirection du presse-papiers. Le processus `rdpclip` était présent lors de la sonde. Les fichiers d’entrée sont intacts et le bac a été arrêté. Le rejeu a duré 35,6 s, dont 10,2 s pour la capture dans le bac. [Relevé DesktopState Notes](../../bench/results/phase5-notes-desktop-state-v1.json)

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase5_notes_desktop_state --runtime $pythonPortable `
    --output $dossierDeValidation
```

## Prévision avant enregistrement et relance de Notes

Le prédicteur symbolique part du dernier `DesktopState` observé. L’hôte écrit la prévision dans le rapport avant d’envoyer la commande au bac. La relance prend comme point de départ le relevé obtenu après l’enregistrement. Le banc active la fenêtre pendant la préparation, puis observe le premier plan et le focus sans les rétablir après les actions.

| Action | Prévision | Relevé dans Windows Sandbox | Variables conformes |
| --- | --- | --- | ---: |
| Enregistrement | Même PID et même état de fenêtre. Base intègre avec une note exacte. | PID 8032 conservé. Fenêtre visible, au premier plan, avec le focus UIA. Une note exacte. | 9/9 |
| Relance | Nouveau PID. Fenêtre visible, au premier plan, avec le focus UIA. Même note. | PID 8032 → 8804. Fenêtre et focus confirmés. Base intègre avec la même note exacte. | 9/9 |

Les neuf variables par action couvrent le processus, la fenêtre et SQLite. Le rejeu a duré 38,8 s et le bac a été arrêté. Le rapport contient les prévisions, les horodatages des commandes, les observations et la comparaison champ par champ. [Relevé des transitions Notes](../../bench/results/phase5-notes-desktop-transition-v1.json)

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase5_notes_desktop_state --predict --runtime $pythonPortable `
    --output $dossierDeValidation
```

### Contrôle négatif avec le stockage fautif

Le même prédicteur a été rejoué dans un bac neuf avec le stockage fautif figé du banc. Le pilote a vérifié le message Tk « Note sauvegardée. » et la présence du titre dans la liste de session avant d’interroger SQLite en lecture seule.

| Action | Prévision SQLite | Observation SQLite | Variables conformes |
| --- | --- | --- | ---: |
| Enregistrement | Une ligne avec la note exacte | Zéro ligne, note absente | 7/9 |
| Relance | Zéro ligne selon le dernier état observé | Zéro ligne, note absente | 9/9 |

Après l’enregistrement, la comparaison a signalé `sqlite.row_count` et `sqlite.exact_fixture_present`. Le contrôle d’intégrité SQLite, le processus et les relevés de fenêtre étaient conformes à chaque étape. Le contrôle négatif a réussi en 37,5 s et le bac a été arrêté. [Relevé du contrôle négatif](../../bench/results/phase5-notes-desktop-transition-faulty-v1.json)

Le rejeu avec le stockage de référence a obtenu 9/9 pour les deux actions dans un second bac, avec le même pilote Tk et la même sonde. Les empreintes des entrées confirment que seul le module de stockage différait.

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase5_notes_desktop_state --predict --faulty `
    --runtime $pythonPortable --output $dossierDeValidation
```

## Sélection d’action Notes à politique figée

Le [protocole](../../bench/phase5_notes_actions.json) fixe cinq cas, les quatre plans candidats et l’ordre alterné des deux bras. Chaque paire utilise un bac neuf. Les deux bras y démarrent chacun une instance de Notes sur une base distincte, préparée dans le même état. Le banc emploie le stockage de référence et contrôle le montage en lecture seule. Les états de départ et les plans admissibles sont comparés dans chaque paire.

La politique classe les plans admissibles par nombre d’actions et départage les égalités par l’ordre du catalogue. Elle exclut les plans incompatibles avec la relation de PID demandée, les écritures inutiles ou en double et l’inspection seule si le but SQLite manque. Quand les prévisions sont disponibles, la même politique prend le premier plan dont l’état projeté satisfait le but. Le premier plan admissible sert de repli. Le vérificateur commun relit la fenêtre, le focus UIA, le PID et la base SQLite après exécution, dans une commande distincte.

| Cas | Sans prédicteur | Avec prédicteur | Décision au verdict, sans / avec |
| --- | --- | --- | ---: |
| Enregistrer une note neuve | Enregistrer, note exacte | Enregistrer, note exacte | 4,867 / 4,705 s |
| Retrouver une note après relance depuis une base vide | Relancer, base vide, échec | Enregistrer puis relancer, note exacte | 4,871 / 7,899 s |
| Relancer avec une note déjà persistée | Relancer, note exacte | Relancer, note exacte | 5,169 / 5,297 s |
| Vérifier une note dans la session ouverte | Inspecter, note exacte | Inspecter, note exacte | 2,268 / 2,227 s |
| Relancer une base vide | Relancer, base vide conforme | Relancer, base vide conforme | 5,055 / 4,952 s |

Sur ces cinq cas synthétiques, les états finaux vérifiés passent de 4/5 à 5/5. Deux cas offrent plusieurs plans admissibles et le prédicteur change la décision sur un seul. Sur ce cas, les deux bras obtiennent la relance demandée et les deux critères SQLite ne passent qu’après l’enregistrement préalable. La sélection seule prend 14,9 µs sans prédicteur et 43,5 µs avec, en médiane. Du début de la sélection au relevé final, le cumul est de 22,230 s sans prédicteur et de 25,080 s avec. Le lancement et la préparation des bacs sont mesurés à part. Les cinq bacs ont été arrêtés. [Relevé des cinq paires](../../bench/results/phase5-notes-action-selection-v1.json)

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase5_notes_action_selection --runtime $pythonPortable `
    --output $dossierDeValidation
```

## Garde de transition avant suppression

Le banc prépare chaque proposition sur une copie de projet jetable, puis exécute `project.apply` et la garde Windows dans le bac. La préparation valide une seconde copie dans le même bac. Le banc observe l’ouverture du handle et compte les appels à la suppression native. Il relit les fichiers, le checkpoint d’application et le journal après chaque verdict.

Le corpus comprend les accords absents, erronés ou expirés, les modifications de la proposition et des fichiers, le remplacement de la cible à octets et date identiques, les changements injectés après le checkpoint et un fichier verrouillé. Une suppression approuvée sur un état intact sert de témoin.

Les 12 cas invalides ont été refusés avant l’appel à la suppression native. Dans chaque cas, l’état des fichiers autour du refus et la chaîne d’audit ont été vérifiés, et aucun checkpoint d’application n’est resté en attente. Le témoin approuvé a effectué une suppression native et laissé les fichiers compagnons intacts. La campagne a duré 81,5 s et le bac a été arrêté. [Relevé de la garde](../../bench/results/phase5-project-transition-guard-v1.json)

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase5_project_transition_guard --runtime $pythonPortable `
    --output $dossierDeValidation
```

## Surveillance de Notes et désactivation du prédicteur

Le banc rejoue le cas figé « retrouver la note après relance, base initialement vide », dans un même Windows Sandbox et avec une base neuve à chaque essai. Le sélecteur et le moniteur tournent sur l’hôte. Le bac exécute les actions et produit les relevés UIA et SQLite. Le seuil de 10 ms et le retard injecté de 30 ms servent à exercer l’alerte de latence.

| Essai | Action retenue | Sélection | Écarts ou alerte |
| --- | --- | ---: | --- |
| Nominal | Enregistrer puis relancer | 51,5 µs | 9/9 variables conformes |
| Stockage fautif | Enregistrer puis relancer | 47,0 µs | Écart de nombre de lignes et de présence de la note exacte |
| Ralentissement injecté | Enregistrer puis relancer | 30,418 ms | Alerte de latence, 9/9 variables conformes |
| Prédicteur désactivé | Relancer | 24,9 µs | Zéro appel au prédicteur, même choix et même état final que la référence publiée |

L’essai désactivé retrouve le verdict de référence sur ce cas. Le processus redémarre et SQLite reste vide, ce que le vérificateur signale. La campagne a duré 97,8 s et le bac a été arrêté. [Relevé des quatre essais](../../bench/results/phase5-notes-monitor-v1.json)

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase5_notes_monitor --runtime $pythonPortable `
    --output $dossierDeValidation
```
