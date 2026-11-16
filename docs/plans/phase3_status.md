# Phase 3 — Évolution des liens

Point de départ `e130dad`, jalon publié de la phase 2 et [relevé de validation](../../bench/results/memory-phase2-v1.json). Le lancement porte sur l’attribution des résultats aux liaisons du graphe Notes dans le [plan de développement](development-plan.md).

## Diagnostic des liaisons Notes

Le rapport d’exécution inclut un diagnostic versionné par liaison et par tentative. Il distingue un échec de l’étape amont, une preuve de remise absente ou invalide, un refus d’autorisation et un échec de l’étape aval. Il signale aussi une étape encore en cours. Les écarts nomment les contrôles attendus. Le diagnostic vérifie les preuves techniques du banc et conserve la distinction entre les tentatives.

Les trois rapports du cycle Notes de la phase 1 et les deux rapports de génération de la phase 2 donnent les mêmes diagnostics pour `localize → generate_diff → verify → verify_desktop`. Les contrôles de régression couvrent une reprise après échec, une preuve mal typée, un refus et l’ordre des étapes.

Le premier rejeu de la phase 3 a été exécuté dans un bac neuf avec Rbitnet CPU, graine 742. Le premier diff s’est appliqué. Le diagnostic a confirmé les trois liaisons et concorde avec les rapports archivés. Les quatre tests, le vérificateur SQLite et les contrôles RapidOCR et SQLite après relance ont réussi. Le bac s’est arrêté. Le relevé local est dans `phase3-notes-links-2ifv94rl/proof.json`.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.link_diagnostics $rapport
```

## Adaptateur du reçu Git

Le candidat `notes-rbitnet-ocr-typed-patch@1.1.0` est compilé à partir d’une copie du parent `notes-rbitnet-ocr@1.0.0`. La liaison `generate_diff → verify` passe par `adapt_patch_receipt`. L’adaptateur contrôle le reçu de Git dans le bac, le dossier de la première tentative et l’empreinte du diff préparé. Il remet le nom d’entrée et l’empreinte contrôlés au vérificateur. Le candidat a son propre journal d’expériences et ses rapports sont séparés du parent.

La comparaison utilise deux bacs neufs successifs, la graine 742, Rbitnet CPU sur huit threads, un plafond de 8 192 Mio et le protocole RapidOCR v2. Les plans sont écrits avant les essais. Les empreintes du moteur, du modèle, du protocole et du diff ainsi que les verdicts communs sont comparés par le banc.

Les durées par étape comprennent le contrôle d’autorisation et l’exécution. Le total comprend la préparation, le démarrage, les sondes d’isolation et l’arrêt du bac.

| Étape | Parent | Candidat |
| --- | ---: | ---: |
| Localisation | 13,851 s | 12,007 s |
| Génération et application du diff | 50,616 s | 50,589 s |
| Adaptation du reçu | — | 0,256 s |
| Quatre tests et vérificateur SQLite | 5,098 s | 5,223 s |
| RapidOCR et SQLite après relance | 23,623 s | 23,146 s |
| **Total** | **115,490 s** | **112,787 s** |

Dans les deux bacs, le même premier diff s’est appliqué. Les quatre tests et le vérificateur SQLite ont réussi. RapidOCR a retrouvé la note après relance et SQLite a confirmé la ligne exacte. Le candidat a vérifié quatre liaisons et le parent trois. Les deux journaux SQLite d’expériences ont passé le contrôle d’intégrité.

La conversion seule a pris 0,545 ms. L’écart total de 2,703 s est mesuré sur une seule paire, jouée parent puis candidat. [Relevé de comparaison](../../bench/results/notes-link-adapter-v1.json)

```powershell
.\.venv\Scripts\python.exe -m bench.run_notes_link_comparison --runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --output $dossierEssai
```

## Campagne de comparaison gelée

Le [manifeste de gel v1](../../akasha_brain/protocols/notes-link-adapter-v1.json) fixe les deux graphes, le code de l’adaptateur, les contrôles invités et les paramètres Rbitnet CPU. Le banc vérifie ce gel avant chaque exécution. L’ordre est parent puis candidat pour la graine 742, candidat puis parent pour 743, et parent puis candidat pour 744. Les deux bras d’une paire utilisent la même graine et chaque bras ouvre un bac neuf.

```powershell
.\.venv\Scripts\python.exe -m bench.run_notes_link_comparison `
    --campaign akasha_brain/protocols/notes-link-adapter-v1.json --runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --output $dossierCampagne
```

Les six bacs ont appliqué le même premier diff, avec vérification Git et contrôle de l’empreinte dans le bac. Tous ont passé les quatre tests et le vérificateur SQLite. RapidOCR a retrouvé la note après relance et SQLite a retrouvé la ligne exacte dans les six exécutions. Les six bacs se sont arrêtés et leurs journaux SQLite distincts ont passé le contrôle d’intégrité.

| Étape, en secondes | 742 parent | 742 candidat | 743 parent | 743 candidat | 744 parent | 744 candidat |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Localisation | 13,713 | 12,831 | 13,978 | 11,938 | 12,083 | 12,965 |
| Génération et application du diff | 51,184 | 51,084 | 54,510 | 52,199 | 51,643 | 51,446 |
| Adaptation du reçu | — | 0,271 | — | 0,258 | — | 0,257 |
| Quatre tests et vérificateur SQLite | 5,341 | 5,473 | 5,280 | 5,303 | 5,481 | 5,644 |
| RapidOCR et SQLite après relance | 25,121 | 23,808 | 23,726 | 24,195 | 24,708 | 23,824 |
| Préparation, démarrage, sondes et arrêt¹ | 22,373 | 23,659 | 22,892 | 22,123 | 23,103 | 30,199 |
| **Total** | **117,732** | **117,126** | **120,386** | **116,016** | **117,018** | **124,335** |

¹ Différence entre le total et la somme des durées des étapes tracées.

La médiane des écarts candidat moins parent est de −0,606 s pour le total. L’étape d’adaptation prend de 0,257 à 0,271 s et la conversion seule a une médiane de 0,572 ms. Pour la graine 744, 7,096 s des 7,317 s supplémentaires sont en dehors des étapes tracées. [Relevé de la campagne](../../bench/results/notes-link-adapter-frozen-v1.json)

## Prochain jalon

Les paliers de promotion, le contrôle de transition et le retour arrière font partie de la qualification de la phase 3.
