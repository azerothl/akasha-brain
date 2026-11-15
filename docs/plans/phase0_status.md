# Statut de la phase 0 — 15 novembre 2026

**Phase 0 ouverte.** Le parcours code des notes satisfait le contrôle
de répétabilité dans Windows Sandbox. La qualification du spécialiste
communication, les preuves restantes du bac et le contrat de restauration
conditionnent le passage en phase 1.
[Critères du plan](development-plan.md#phase-0--contrats-et-tâches-représentatives)

## Contrats et banc figé

- Les huit schémas JSON Schema 2020-12 sont versionnés en `1.0.0`, avec une
  fenêtre de compatibilité d'un majeur. Les 8 schémas, les 2 exemples
  `GoalSpec` et les **37 tests de contrats** passent. La suite couvre
  notamment l'autorisation R0–R3, la clarification avant action R2/R3,
  la vérification du fournisseur et de l'endpoint effectifs du grant,
  et le refus typé d'une expiration invalide ou sans décalage UTC.
  [Contrats](../../contracts/README.md) · [Tests d'autorisation](../../contracts/tests/test_authz.py) · [Tests des grants](../../contracts/tests/test_grants.py)
- Le banc figé reproduit **3 échecs attendus et 4 succès**. Les deux
  scénarios ont été validés sur des copies corrigées séparées. Pour les
  notes, la baseline fixe localise les deux échecs puis passe **4/4** et
  le vérificateur SQLite. Dernier relevé sur l'hôte **1,4 s** de bout en
  bout et **9,1 s** dans le bac. Les tests du candidat s'exécutent
  dans le bac, avec les fixtures et le vérificateur en lecture seule.
  [Banc](../../bench/README.md) · [Baseline fixe](../../bench/run_baseline.py)
- Rétention à 90/30/7 jours, sauvegarde chiffrée quotidienne sur 7 jours,
  consentement par projet et catégorie, effacement vérifié et registre
  de marqueurs hors de la version restaurée sont documentés. Le contrat
  de restauration et de récupération des clés reste à compléter.
  [Conception rétention et sauvegarde](../../contracts/retention_design.md)

## Windows Sandbox et observation

- Le profil durci a démarré une session depuis l'hôte. Hyper-V était actif
  et l'inventaire ne comptait aucune VM pour le repli par checkpoint.
  **Windows Sandbox est le banc retenu pour les essais actuels des notes.**
  [Profil du banc](../../bench/harness/sandbox_profile.md)
- L'import en lecture seule a été exercé avec l'application et une donnée
  synthétique. Le bac a refusé l'ouverture en écriture du témoin et la
  création d'un fichier dans le dossier mappé. L'empreinte du fichier
  hôte est restée identique. Le prototype d'export a rapatrié le rapport
  JSON borné via les codes de sortie de la CLI Windows Sandbox. Il a
  refusé un `.exe`, un chemin remontant vers le parent et une partie de
  rapport inconnue.
- La sonde UIA managée dans le bac a reconnu **Notes — banc Akasha**, le
  focus et **14 descendants**. Elle a trouvé zéro contrôle éditable et
  zéro motif `TextPattern` ou `ValuePattern`. Le bouton **Enregistrer**,
  la liste et la note témoin étaient absents de l'arbre exploitable.
  La sonde générique sur l'hôte avait déjà confirmé que
  `UIAutomationClient` managé fonctionnait et que la voie COM
  `CUIAutomation` n'était pas enregistrée sur ce poste.
  [Sonde et relevé antérieur](../../bench/harness/uia_coverage.md)
- RapidOCR ONNX 1.4.4 sur ONNX Runtime 1.32.0 fonctionne en CPU. Sur
  l'image synthétique, les mots attendus sont retrouvés en **0,6 à
  0,8 s** après normalisation des accents. Une lecture indépendante
  de l'état décide de la réussite du parcours.
  [Configuration et mesure OCR](../../bench/vision_ocr_selection.md)

## Inférence CPU et réparation des notes

Les premiers essais Ollama couvrent un prompt fixe, la concurrence à deux
appels et un cycle arrêt, éviction et reprise. Ces chiffres décrivent
Ollama. La campagne native Rbitnet en CPU a ensuite mesuré six changements
entre **Qwen3-8B Q4_K_M** et **Qwen3.5-0.8B Q8_0**, le déchargement,
la concurrence, la saturation, la reprise et la mémoire. Le format sans
raisonnement permet des réponses françaises courtes. En communication
structurée, **Qwen3.5-0.8B** réussit 3/6 cas et **Qwen3.5-2B** 4/6
avec la consigne initiale. Sur les mêmes fiches, **Spark-X2.5-1.7B**
réussit 1/6 et **Llama 3.2 1B Instruct** 0/6. Qwen3.5-2B atteint
**6/6 en 27,49–28,36 s par fiche** après deux ajustements de la consigne.
Le rejeu de cette [consigne figée](../../bench/communication/qwen35-2b-fr-v1.json)
sur six fiches inédites donne **3/6 en 28,27–29,72 s par fiche**.
Deux réponses reprennent un exemple hors sujet et une omet la seconde
action. [Détail par fiche](../../bench/measurements_phase0.md#validation-de-la-consigne-figée-sur-six-nouvelles-fiches)
[Mesures CPU et provenance](../../bench/measurements_phase0.md#qualification-native-de-rbitnet--15-novembre) · [Contrat minimal des adaptateurs](../architecture/brain-system-spec.md#62-décision-v08--moteurs-et-gestion-des-ressources)

Campagne du 15 novembre sur le même poste Windows (Ryzen 7 9800X3D),
avec Qwen3-8B Q4_K_M en CPU et un processus Rbitnet par essai. Le temps
mur commence avant le démarrage du moteur et se termine au retour de
pytest et du vérificateur dans Windows Sandbox. Les délais jusqu'à
`/ready` étaient de 0,51 à 1,31 s, avec le cache du système laissé en
place. Chaque essai repart de `notes_store.py` figé. Les essais 1 à 3 fournissent un extrait
de la méthode fautive au modèle et demandent un diff unifié. Les essais
4 et 5 demandent une méthode et calculent le diff à partir du texte
produit. Au cinquième, le modèle reçoit aussi le diagnostic du test
précédent. [Poste de mesure](../../bench/environment_report.md)

| Essai | Proposition | Diff | Tests | Vérificateur SQLite | Temps mur |
| --- | --- | --- | --- | --- | ---: |
| 1 | Diff direct, graine 731 | Rejeté par Git | 2/4 sur le témoin fautif | Échec attendu | 69,2 s |
| 2 | Diff direct, graine 732 | Rejeté par Git | 2/4 sur le témoin fautif | Échec attendu | 66,6 s |
| 3 | Diff direct, graine 733 | Rejeté par Git | 2/4 sur le témoin fautif | Échec attendu | 65,6 s |
| 4 | Méthode convertie en diff, graine 734 | Appliqué | 1/4 | Réussi | 47,8 s |
| 5 | Méthode avec retour de tests, graine 735 | Appliqué | **4/4** | **Réussi** | **49,1 s** |

Les trois diffs directs ont atteint la limite de 280 jetons et ont été
rejetés comme mal formés. L'essai 4 écrit et valide la transaction,
puis ferme la connexion trop tôt. L'essai 5 conserve la connexion pour
l'appelant. Sa docstring décrit encore le bug initial. Les deux essais
avec conversion en diff ont pris **96,8 s cumulées**, hors intervalle
de diagnostic entre les deux. Le profilage documente un cycle réussi
avec retour de tests. La répétabilité de ce cycle reste à mesurer.

Les GGUF et les tokenizers ont été rapprochés des SHA-256 publiés à
leurs révisions de distribution sous Apache 2.0. Le projet Rbitnet
est sous MIT. Le commit exact du binaire local reste une inférence
à partir des traces de compilation et du journal Git.
[Révisions sourcées](../../bench/measurements_phase0.md#provenance-et-licences)

| Fichier | SHA-256 |
| --- | --- |
| `rbitnet-server.exe`, build local `rbitnet-i2s-batch-target/release` | `80cd4e7f7c39b1facb4073915253965c60f85fd936d08c242221acb2cae1f49c` |
| `Qwen3-8B-Q4_K_M.gguf` | `120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4` |
| Tokenizer Qwen3-8B | `aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4` |
| `Qwen3.5-0.8B-Q8_0.gguf` | `0ad885ffd4bb022fc4f0d33a3308fa108ef8613159d3b3a67e23abca056b7a6c` |
| `Qwen3.5-2B-Q8_0.gguf` | `1b04acba824817554f4ce23639bc8495ff70453b8fcb047900c731521021f2c1` |
| Tokenizer commun Qwen3.5 0,8B et 2B | `5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42` |

Preuves locales sous
`%USERPROFILE%/.codex/visualizations/2026/11/15/01a1dc82-efbe-7b81-9b0d-a54ba7e6a006/`.
Le dossier `rbitnet-notes-cpu/` contient `report.json`, les invites, les
sorties du moteur et `trial-5/proposal.diff`. Le rapport du bac et de
l'UIA est dans `validation-notes-wsb/report.json`.
Les relevés natifs et les comparaisons de communication sont dans
`rbitnet-qualification-cpu/`.
Le rejeu des six fiches avec Spark et Llama est dans
`rbitnet-communication-alternative/`.
Les deux rejeux de Qwen3.5-2B et leurs consignes sont dans
`rbitnet-communication-prompt/`.
L'évaluation sur les six nouvelles fiches est dans
`rbitnet-communication-holdout/qwen35-2b-fr-validation-v1.json`.

## Baseline humaine (relevée par l'utilisateur, 2026-11-14)

`bench/baseline_human.md` : notes 23:33→23:46 (**13 min, réussite partielle** —
notes persistées mais contenu non ré-affichable dans l'UI), transfert
23:50→23:53 (**3 min, réussite**), conditions consignées (cette machine,
YouTube Studio, Cursor, consoles Python, menu flottant ouvert).

Deux suites, traitées le 2026-11-14 :

- **Contamination du gel** : la correction avait été appliquée en place
  (`notes_store.py` et `tasks_store.py` fautifs remplacés — suite passée à
  6/6, variante de transfert compromise). Versions fautives **restaurées à
  l'identique**, signature 3 échecs / 3 succès vérifiée. Effet positif :
  la correction humaine faisait passer toute la suite — seconde preuve
  indépendante (avec le témoin scratch) que les tests caractérisent bien
  la faute. Règle rappelée : toute correction se fait sur copie jetable,
  jamais sur le banc gelé.
- **Trou UI réel** : sans gestionnaire de sélection, `notes_app.py`
  n'affichait que les titres — contenu non vérifiable par l'UI. Ajout de
  `on_select` (titre + contenu ré-affichés) et d'un test maintenu
  (`test_ui.py`, PASS sans `skip` sur ce poste). Re-gel validé : suite
  3 échecs / 4 succès, baseline regélée PASS (1,9 s), vérificateur PASS.
  Le doute de la baseline (« persistance ou simple affichage ? ») est
  tranché : la persistance est prouvée par les tests + le vérificateur
  indépendant, jamais par l'affichage seul.

Le test renforcé initialise deux notes en SQLite, place une saisie
différente dans le formulaire et déclenche deux événements réels de
sélection Tk. Il vérifie le remplacement du titre et du contenu,
y compris les accents et les retours à la ligne. Retirer la liaison
de l'événement sur une copie fait échouer le test.
[Test UI](../../bench/notes/tests/test_ui.py)

## Premiers seuils proposés

Ces seuils portent sur le poste, les modèles et les fixtures ci-dessus.
Les plafonds de temps servent au prochain lot d'essais. Confirmer les
conditions, le nombre de répétitions et la dispersion avant de fixer
un seuil de fiabilité ou de promouvoir une capacité.
[Protocole de mesure](../architecture/brain-system-spec.md#122-précisions-v03--harness-bureau-windows-et-protocole-de-mesure) · [Critères de sortie](development-plan.md#phase-0--contrats-et-tâches-représentatives)

| Contrôle | Proposition | Justification locale |
| --- | --- | --- |
| Réparation des notes | Diff applicable et limité au périmètre, **4/4 tests**, aucun saut et vérificateur SQLite au vert. Le témoin fautif doit rester à 2/4 et être rejeté par le vérificateur. | L'essai 4 montre que la persistance seule peut passer avec trois régressions. |
| Refus de sécurité et faux acceptés | **0 cas négatif accepté** sur le corpus contrôlé. Inclure grants hors périmètre, écriture sur l'hôte, exports interdits et état final fautif. | Les refus testés et le témoin fautif donnent des résultats vérifiables sur ces cas. |
| Reproductibilité du parcours Rbitnet | Premier contrôle à **3 cycles indépendants sur 3 réussis** sur le banc notes, avec le même protocole figé et au plus un retour de tests par cycle. | Le profilage initial avait produit un seul cycle réussi avec retour de tests. |
| Temps mur CPU de ce parcours | **60 s par tentative** et **120 s par cycle**, du premier lancement du moteur à la dernière validation, retour de tests compris. | 47,8 s puis 49,1 s pour les deux tentatives structurées, soit 96,8 s mesurées hors diagnostic. |
| Baseline fixe des notes sur l'hôte | **3 s** au plus sur le même poste et avec le même périmètre de mesure. | 1,4 s au dernier essai, avec un maximum observé de 2,6 s après l'ajout du test UI. |
| OCR CPU, image synthétique | Tous les mots attendus après normalisation des accents, **1 s** au plus pour l'inférence après initialisation. | 0,6 à 0,8 s sur l'image actuelle. |

Une comparaison de coût avec la baseline humaine ou fixe exige les
mêmes tâches, conditions et critères de succès. Le temps humain des
notes correspond à une réussite partielle. La baseline fixe a été
chronométrée dans le même bac que la campagne Rbitnet.

## Rejeu du protocole guidé v1

Le 15 novembre, la baseline fixe et les trois cycles ont été exécutés
dans la même session Windows Sandbox. La baseline fixe passe les quatre
tests et le vérificateur SQLite en **9,1 s**, traversée de la CLI comprise.
La baseline sur l'hôte a passé son plafond de 3 s en **1,4 s**.
[Protocole v1](../../bench/guided_repair_protocol.md)

| Cycle | Première tentative | Tentative après retour des tests | Temps du cycle | Seuils |
| --- | ---: | ---: | ---: | --- |
| 1 | 43,8 s | 45,0 s | 88,9 s | Respectés |
| 2 | 43,9 s | 46,4 s | 90,3 s | Respectés |
| 3 | 45,1 s | 45,6 s | 90,7 s | Respectés |

Les six diffs s'appliquent. À chaque premier essai, la persistance
passe alors que deux tests échouent à cause de la fermeture prématurée
de la connexion. Les trois seconds essais passent **4/4 tests sans
saut** et le vérificateur. Le témoin fautif est rejeté. Les correctifs
validés conservent la docstring décrivant le bug initial.
Le rapport détaillé et les six propositions sont sous
`rbitnet-guided-v1/` dans le dossier de preuves locales indiqué plus haut.

## Conditions restantes pour entrer en phase 1

1. **Qualifier le spécialiste communication.** Avec la consigne v1,
   Qwen3.5-2B valide les six fiches de réglage et trois des six fiches
   inédites. Les échecs concernent la clarification, l'avis d'échec et
   l'ordre des actions. À l'intégration, vérifier le modèle actif après
   `/ready`, qui peut recharger le modèle initial après déchargement.
2. **Compléter la preuve du banc durci.** Vérifier dans le bac l'effet
   des désactivations réseau, presse-papiers, imprimantes et entrées
   audio/vidéo, puis consigner la compatibilité de vGPU et Protected
   Client pour les tâches retenues. Le prototype d'export couvre le
   rapport JSON. Définir le périmètre des fichiers que le courtier doit
   prendre en charge pour le MVP. Pour le parcours des notes, assurer
   le focus via UIA et spécifier un moyen complémentaire d'action et
   d'observation, avec contrôle indépendant de la persistance.
3. **Compléter le contrat de rétention et de restauration.** Spécifier
   la récupération des clés, la liaison des échéances aux copies et à
   leur filiation, le consentement de sauvegarde distinct et les états
   d'effacement. L'implémentation et la validation de la restauration
   bout en bout suivent le découpage des phases 1 et 2.
   [Plan de développement](development-plan.md#questions-ouvertes-à-trancher-avant-la-phase-concernée)
