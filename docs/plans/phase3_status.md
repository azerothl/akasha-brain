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

## Qualification de la promotion

Le banc utilise les graphes du [jalon figé](https://github.com/azerothl/akasha-brain/commit/e868607076e42ed81d81e6d6c63df916e84989e6) et un registre SQLite jetable. Le replay compare le candidat à la référence publiée pour la graine 742. En shadow, le parent puis le candidat exécutent la même entrée, graine 743, dans deux bacs. Le palier limité autorise une seule exécution candidate du banc Notes, graine 744. Les contrôles vérifient aussi le routage vers le parent hors cohorte et après épuisement du quota.

Les décisions sont signées avec une clé Ed25519 de test. La signature lie les plans, le gel, la référence publiée et les preuves de chaque palier. Le banc exerce ensuite le routage actif et le routage après retour arrière, chacun dans un bac neuf.

| Exécution | Graphe | Graine | Durée |
| --- | --- | ---: | ---: |
| Replay | Candidat | 742 | 121,259 s |
| Shadow | Parent | 743 | 120,738 s |
| Shadow | Candidat | 743 | 122,496 s |
| Limité | Candidat | 744 | 115,279 s |
| Après promotion | Candidat | 744 | 117,210 s |
| Après retour arrière | Parent | 744 | 118,941 s |

Les six bacs ont validé le premier diff, les quatre tests et SQLite. RapidOCR a retrouvé la note après relance et SQLite a confirmé la ligne exacte. Le replay a reproduit le verdict de référence et les deux exécutions shadow ont produit le même verdict.

Le registre a refusé la promotion avant les preuves et rejeté la décision altérée. La décision valide a sélectionné `notes-rbitnet-ocr-typed-patch`. Le retour arrière signé a rétabli `notes-rbitnet-ocr`, confirmé par la dernière exécution. Les deux signatures ont été revérifiées avec la clé publique après suppression de la clé de test. La chaîne d’audit et le refus d’effacer ses entrées ont été contrôlés. [Relevé et décisions signées](../../bench/results/notes-link-promotion-v1.json)

```powershell
.\.venv\Scripts\python.exe -m bench.run_notes_link_promotion `
    --lock akasha_brain/protocols/notes-link-adapter-v1.json `
    --reference bench/results/notes-link-adapter-frozen-v1.json --runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --output $dossierEssai
```

## Vérificateur de transition avant suppression

L’empreinte de la proposition lie désormais l’identité du fichier et ses métadonnées de révision à son contenu. Après les accords et juste avant l’effet, le vérificateur rouvre le fichier sans partage d’écriture ou de suppression. Il contrôle son identité et son empreinte, puis utilise ce même handle pour la suppression. Les propositions existantes sont vérifiées avec leur empreinte de contenu approuvée et la révision observée au début de l’application. [Partage des fichiers Windows](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew) · [Disposition d’un fichier par handle](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_disposition_info)

Sur un projet jetable, Windows Sandbox a validé la proposition de suppression. La CLI a ensuite refusé l’application sans accord explicite de suppression, avec un contenu modifié et après remplacement du fichier par un autre aux mêmes octets et à la même date de modification. Le dernier cas a été bloqué par le vérificateur de transition. Les fichiers sont restés intacts lors des refus et aucun effet n’est resté en attente après le refus du vérificateur. [Relevé de validation](../../bench/results/project-delete-transition-v1.json)

## Qualification de la liaison sur des remises invalides

Le corpus réservé fixe trois défauts et un témoin valide avant exécution. Après le retour réussi de Git dans le bac, le lanceur retire l’empreinte du reçu, substitue le nom d’une autre tentative ou modifie les octets de la copie préparée du diff. Chaque cas est exécuté sur les deux graphes, à graine identique, avec Rbitnet CPU dans un bac neuf. Le lanceur vérifie les empreintes du gel, du corpus et du code du banc. [Corpus et ordre des cas](../../bench/notes-link-handoff-reserved-v1.json)

La validité de la remise est déterminée à partir des empreintes observées et du nom de la tentative. Une acceptation à tort correspond à un appel effectif au vérificateur invité avec une remise invalide, y compris quand un contrôle ultérieur fait échouer le parcours. Une reprise correspond à une nouvelle génération du diff pendant l’exécution. Les traces mesurent séparément le temps total et le temps passé dans les deux étapes de vérification en aval.

```powershell
.\.venv\Scripts\python.exe -m bench.run_notes_link_handoff --runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --output $dossierEssai
```

Les deux graphes ont appliqué le même premier diff avec Git dans les huit bacs de la campagne. Rbitnet a généré les diffs sur le CPU de l’hôte, comme dans la comparaison figée. L’application, les tests et les contrôles SQLite et RapidOCR ont eu lieu dans les bacs sans réseau.

| Remise | Graine | Acceptations à tort parent / candidat | Reprises parent / candidat | Total parent | Total candidat |
| --- | ---: | ---: | ---: | ---: | ---: |
| Empreinte absente | 742 | 1 / 0 | 0 / 0 | 208,040 s | 150,761 s |
| Mauvais nom de tentative | 743 | 1 / 0 | 0 / 0 | 209,483 s | 149,573 s |
| Copie préparée du diff modifiée | 744 | 1 / 0 | 0 / 0 | 203,771 s | 158,063 s |
| Témoin valide | 742 | — | 0 / 0 | 190,014 s | 207,508 s |

Le candidat a refusé les trois remises à la liaison `generate_diff → verify`. Sur ces cas, l’étape d’adaptation a pris de 0,412 à 0,458 s et a évité les deux étapes aval, qui ont pris une médiane de 51,971 s chez le parent. La réduction médiane du temps total par paire est de 57,279 s. Le protocole RapidOCR v2 fixe une seule tentative de génération par exécution.

Chez le parent, le cas de l’empreinte absente a abouti. Le reçu de la mauvaise tentative a passé les quatre tests et le vérificateur SQLite, puis le contrôle après relance a échoué. La copie modifiée du diff a passé les quatre tests et les contrôles SQLite et RapidOCR après relance, puis le contrôle final d’intégrité de la copie hôte a fait échouer le parcours.

Les deux bras du témoin valide ont franchi la liaison et passé les quatre tests et le vérificateur SQLite. Le parent a retrouvé la note après relance avec RapidOCR et SQLite. Les deux contrôles après relance ont échoué au premier passage du candidat. Un rejeu séparé de ce bras dans un bac neuf, avec le même gel et la graine 742, a réussi les quatre tests et les vérifications RapidOCR et SQLite après relance en 188,871 s. Les deux mesures du candidat figurent dans le relevé.

Les neuf bacs se sont arrêtés et les neuf journaux d’expériences ont passé le contrôle d’intégrité SQLite. [Relevé par cas et par étape](../../bench/results/notes-link-handoff-reserved-v1.json)
