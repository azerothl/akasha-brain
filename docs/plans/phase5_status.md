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
