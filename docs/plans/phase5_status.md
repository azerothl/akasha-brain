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
