# Phase 6 — Évolution intégrée

## Entrée sur le banc

Les signatures Ed25519 du contrôle de phase 3 ont été revérifiées. Le retour arrière y a rétabli `notes-rbitnet-ocr` après dépassement du seuil. Le relevé de phase 4 montre le retrait du spécialiste SQL et le retour de Tâches à la référence, avec les contrôles Notes, projet et communication. Le relevé de phase 5 confirme les alertes de divergence et de latence, ainsi que le repli après désactivation. [Phase 3](../../bench/results/notes-link-monitor-v1.json) · [Phase 4](../../bench/results/phase4-tasks-routing-v1.json) · [Phase 5](../../bench/results/phase5-notes-monitor-v1.json)

## Premier cycle de promotion automatique

La route de référence sélectionne un plan Notes sans prédicteur. La route candidate utilise les prévisions de phase 5. Le registre lie la politique, les sources de l’essai et les mesures appariées aux décisions signées. La sélection active s’applique au cas synthétique qui demande de persister une note et de relancer Notes depuis une base vide. Les autres cas passent par le parent.

| Palier | Preuves sur Notes | Route active après le palier |
| --- | --- | --- |
| Replay | 1/2 états vérifiés pour le parent, 2/2 pour la candidate | Parent |
| Shadow | 3/3 états vérifiés pour chaque route | Parent |
| Exposition limitée | Une seule exécution candidate admise et vérifiée | Candidate, après signature |
| Surveillance | Succès nominal, puis deux écarts SQLite détectés avec le stockage fautif | Parent, après retour arrière signé |

Sur le cas où la décision change, enregistrer avant de relancer ajoute 2,909 s entre la décision et le verdict et permet de retrouver la note exacte. Après le retour arrière, le rejeu sélectionne de nouveau « Relancer » et constate SQLite vide, comme la référence de phase 5. Les demandes R2 et R3, l’absence de confinement, les données hors périmètre synthétique et l’exposition hors séquence ont été refusées. Le journal et les deux signatures Ed25519 ont été vérifiés après arrêt des quatre bacs. Durée totale 309,6 s. [Relevé du cycle Notes](../../bench/results/phase6-notes-evolution-v1.json)

Le registre vérifie aussi qu’un palier refusé consomme sa tentative, qu’un lot de preuves correspond aux bacs admis et que l’exposition limitée reprend l’entrée mesurée au replay. Les tests locaux couvrent ces refus. Le rejeu intégré relit les preuves signées dans de nouveaux registres.

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase6_notes_evolution --runtime $pythonPortable `
    --output $dossierDeValidation
```

## Compétences et politiques de mémoire

La compétence Notes réutilise le diff de la bibliothèque privée, déjà qualifié sur les preuves de la phase 1. La génération Rbitnet CPU et la réutilisation appliquent le même diff vérifié, exécutent les quatre tests et interrogent SQLite. Le parcours bureau vérifie aussi RapidOCR et la persistance après relance. Les bras utilisent des bacs distincts, et le registre exige le même résultat vérifié ainsi qu’un gain de 5 s sur ce banc avant de promouvoir pour le coût.

| Palier | Génération | Réutilisation | Gain mesuré |
| --- | ---: | ---: | ---: |
| Replay bureau | 116,802 s | 63,571 s | 53,231 s |
| Shadow code | 88,439 s | 39,597 s | 48,842 s |
| Exposition limitée bureau | 116,802 s, référence du replay | 70,355 s | 46,447 s |

L’exposition limitée a déclenché une promotion signée pour le seul cas bureau qualifié. Le nominal actif a réussi en 68,004 s. Une demande d’effacement a ensuite été injectée sur une source de la compétence après les sondes d’isolation. Le parcours a renvoyé `erasure_requested` avant l’application du diff. La décision signée a rétabli la génération, et le rejeu en 116,445 s a retrouvé le verdict de référence. La purge dans la copie a retiré huit objets, et la bibliothèque a cessé de proposer la compétence bureau. Les huit bacs ont été arrêtés. [Relevé de la compétence](../../bench/results/phase6-skill-evolution-v1.json)

Le classement contextuel et la similarité filtrée ont ensuite été comparés sur 17 cas chacun. Ils obtiennent tous deux 17 décisions correctes et zéro sélection invalide. Les cas supplémentaires vérifient le refus d’un descendant dès la demande d’effacement, le maintien de la compétence code indépendante, la purge et l’expiration. Sans gain de sélection observé, le registre a retenu le classement contextuel et refusé le passage en shadow. [Relevé de la politique mémoire](../../bench/results/phase6-memory-policy-v1.json)

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase6_skill_evolution --phase1 $preuvesPhase1 `
    --runtime $pythonPortable --rbitnet $moteur $gguf $tokenizer --output $dossierCompétence
.\.venv\Scripts\python.exe -m bench.run_phase6_memory_policy --phase1 $preuvesPhase1 `
    --runtime $pythonPortable --output $dossierMemoire
```

## Repli intégré au niveau de phase 3

Le contrôleur ouvre les trois registres liés au même ensemble de politiques. Le rejeu relit le journal et les preuves signées de la route et de la compétence, ainsi que le refus de promotion mémoire. Au départ, la route utilise le prédicteur, la compétence utilise la réutilisation qualifiée et la mémoire conserve le classement contextuel.

Dans un bac neuf, le stockage fautif provoque les deux écarts SQLite sur la route active. Le retour arrière signé ramène l’autonomie effective au niveau de phase 3 et suspend les nouvelles promotions automatiques. Dans un autre bac, la compétence repart en génération Rbitnet CPU et reproduit le verdict du parent en 114,912 s, avec les quatre tests, RapidOCR et SQLite après relance. La mémoire conserve le classement contextuel. Le contrôle R3 est refusé. La réouverture des registres après suppression de la clé de test restitue le même état effectif. Les deux bacs sont arrêtés. [Relevé du repli intégré](../../bench/results/phase6-integrated-v1.json)

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase6_integrated --route $preuvesRoute --skill $preuvesCompétence `
    --memory $preuvesMemoire --phase1 $preuvesPhase1 --runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer --output $dossierIntegre
```

Les trois dossiers de qualification contiennent le rapport et le registre SQLite de l’exécution correspondante.

## Raccordement à l’interface desktop

Une session intégrée se prépare dans un dossier local neuf à partir des trois qualifications et du journal synthétique de phase 1. La clé Ed25519 locale signe les décisions de la session. Le lanceur utilise la file desktop existante, qui donne la priorité aux tâches utilisateur à la prochaine libération du bac. La pause conserve la file dans SQLite pour une reprise au prochain lancement. Le bouton « Retour à la référence » signe une demande distincte des alertes de dérive et rétablit les politiques parentes. Les tâches de projet réel gardent leur propre parcours d’approbation.

```powershell
.\.venv\Scripts\python.exe -m bench.run_phase6_desktop prepare --route $preuvesRoute --skill $preuvesCompétence `
    --memory $preuvesMemoire --phase1 $preuvesPhase1 --key $cleLocale --output $sessionIntegree
.\.venv\Scripts\python.exe -m akasha_brain.desktop --integrated-session $sessionIntegree `
    --integrated-key $cleLocale --runs $historique --python-runtime $pythonPortable `
    --rbitnet $moteur $gguf $tokenizer
```

Les dix contrôles du lanceur sont passés en 242,360 s. Une tâche Notes a utilisé la compétence qualifiée en 71,937 s pendant la pause du suivi. Un nouveau processus a repris la file et détecté les deux écarts SQLite injectés dans un autre bac. Le retour automatique signé a ramené le lanceur à la génération Rbitnet CPU, vérifiée en 116,979 s. Les deux tâches ont passé les quatre tests et les contrôles RapidOCR et SQLite après relance. L’historique contenait dans les deux cas le diff dont l’empreinte avait été vérifiée dans le bac. Les trois bacs ont été arrêtés.

Le retour demandé depuis l’interface a été exercé dans une session distincte. Les deux signatures Ed25519 ont été vérifiées et la réouverture indépendante des registres a confirmé les politiques parentes. [Relevé du lanceur et de la reprise](../../bench/results/phase6-desktop-restart-v1.json)

## Audit des preuves des phases 0 à 6

| Phase | Preuves de sortie vérifiées |
| --- | --- |
| 0 | Contrats et refus typés, bancs Notes et Tâches, baseline chronométrée, confinement, import/export et blocage du presse-papiers. [Statut](phase0_status.md) |
| 1 | Graphes et interface, Notes et transfert réservé sur CPU et CUDA, projet réel avec accords, évolution bornée et traces OTLP. [Audit](phase1_status.md#audit-des-critères-de-sortie) |
| 2 | Gain de réutilisation, filtrage, cycle des compétences, effacement et non-résurrection sur plusieurs sauvegardes. [Relevé](../../bench/results/memory-phase2-v1.json) |
| 3 | Gain de la liaison Notes, promotion par paliers et retour au parent vérifié avec signatures. [Surveillance](../../bench/results/notes-link-monitor-v1.json) |
| 4 | Spécialiste SQL évalué sur les cas réservés, retrait et non-régression. Path A qualifié comme option et référence déterministe par défaut. [Routage](../../bench/results/phase4-tasks-routing-v1.json) · [Porte](../../bench/results/phase4-tasks-gate-v1.json) |
| 5 | États bureau et code, gain à politique figée, zéro faux accepté sur le corpus de garde, alertes et désactivation du prédicteur. [Clôture](phase5_status.md#clôture-sur-le-banc) |
| 6 | Gains attribués pour la route et la compétence, arbitrage mémoire, promotions bornées et signées, refus R2/R3 sur le banc, reprise du suivi desktop et retours signés au niveau de phase 3. [Repli intégré](../../bench/results/phase6-integrated-v1.json) · [Lanceur desktop](../../bench/results/phase6-desktop-restart-v1.json) |

La qualification porte sur le MVP local Windows bureau et code, sur le matériel et les scénarios mesurés.

## Interfaces et capacités livrées après la qualification du banc

La conversation Windows transmet les demandes libres au planificateur et au registre des capacités. Elle peut examiner un projet Python ou npm, comparer des documents et lire une sélection du code pour produire un résumé détaillé. Sur Documentalist, l’analyse en lecture seule a consulté 49 sources et vérifié 12 références. Les 163 empreintes comparées et l’état Git étaient identiques après le rejeu. [Résumé du code](../../bench/results/documentalist-code-summary-v1.json)

Le serveur MCP local expose le plan, le lancement et le résultat Notes. Pour un projet configuré, il prépare une proposition dans Windows Sandbox et restitue le diff vérifié. Le parcours projet a exercé l’approbation dans l’interface Windows avant application. [Notes via MCP](../../bench/results/windows-interface-mcp-notes-v1.json) · [Projet via MCP](../../bench/results/mcp-real-project-v1.json)

Une capacité manquante déclenche une découverte des fournisseurs déclarés et un relevé technique. RapidOCR est qualifié sur des images synthétiques avant la reprise de la lecture demandée. SD-Turbo utilise l’archive CPU et les poids épinglés après les accords correspondants, puis une qualification synthétique et un nouveau bac pour la demande. [Reprise RapidOCR](../../bench/results/conversation-capability-recovery-v1.json) · [CLI Windows et Linux](../../bench/results/image-windows-linux-v1.json)

### Génération d’images headless via MCP

Le client suit `image_start` par `image_status` et récupère le PNG avec `image_result`. Lorsqu’un artefact manque, l’opérateur donne l’accord dans la CLI interactive, puis `image_resume` reprend la description avec le même identifiant de tâche. Les identifiants image et les PNG restent accessibles pendant la durée de vie du serveur.

| Parcours MCP | Windows Sandbox | Ubuntu WSL2 avec Bubblewrap |
| --- | ---: | ---: |
| Moteur déjà qualifié, jusqu’au PNG reçu et vérifié | 50,224 s | 29,683 s |
| Cache vide, deux accords et qualification inclus | 100,923 s | 63,877 s |
| Après les deux accords, de la reprise au PNG | 95,664 s | 57,611 s |

Les rejeux à cache vide ont refusé le moteur, puis accepté le moteur et refusé les poids, puis accepté les poids. Les réponses d’accord ont été simulées dans la CLI. Le transport des artefacts a utilisé une source locale contenant les fichiers épinglés déjà approuvés. Chaque rejeu a vérifié deux reçus distincts, une seule demande initiale et la reprise du même `task_id`.

Les rendus et les qualifications ont été exécutés dans les bacs réels sans fenêtre, hors ligne et avec les entrées en lecture seule. Le client a obtenu `passed`, décodé le PNG 512 × 512 et recalculé son SHA-256. Les empreintes correspondent à celles du selfie déjà mesuré sur chaque OS. Les preuves confirment l’arrêt des bacs. [MCP avec qualification en cache](../../bench/results/image-mcp-headless-v1.json) · [MCP à cache vide](../../bench/results/image-mcp-cold-cache-v1.json)

La suite applicative Windows et les contrats ont passé 264 tests au jalon MCP image. Les tests ciblés MCP et image Linux en ont passé 10. Les trois échecs des versions fautives figées de Notes et Tâches ont été reproduits sur le commit parent. Le périmètre Linux mesuré porte sur les images en CLI et MCP sous Ubuntu WSL2. [Validation du jalon MCP](../../bench/results/image-mcp-headless-v1.json)
