# Statut de la phase 0 — 15 novembre 2026

**Phase 0 validée pour le banc Windows CPU.** Le parcours code des
notes satisfait le contrôle de répétabilité. La v2 avec deux gabarits
est retenue pour la communication. Le contrat de restauration est
défini. Les essais de confinement et leur portée sont consignés
ci-dessous.
[Critères du plan](development-plan.md#phase-0--contrats-et-tâches-représentatives)

## Contrats et banc figé

- Dix schémas JSON Schema 2020-12 sont versionnés en `1.0.0`, avec une
  fenêtre de compatibilité d'un majeur. Les dix schémas, les deux exemples
  `GoalSpec` et les **44 tests de contrats** passent. La suite couvre
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
- Le contrat de rétention définit le consentement de sauvegarde distinct,
  les échéances par filiation, la récupération des clés, les états
  d'effacement et la barrière de restauration. `BackupConsent` et
  `RetentionCopy` ont des schémas et des tests. Le coffre et sa validation
  bout en bout sont prévus aux phases 1 et 2.
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
- La sonde de canaux ne détecte ni route par défaut, ni caméra
  présente, ni entrée audio active, ni imprimante redirigée.
  Avec `ClipboardRedirection=Disable`, un marqueur texte synthétique
  a été écrit et relu localement de chaque côté. Les deux transferts
  sont bloqués dans le profil nominal et dans le profil demandant
  Protected Client. Les huit formats initiaux du presse-papiers hôte
  ont été restaurés après chaque essai.
- Le parcours clavier avec garde de focus UIA et Win32 a été joué
  sur les deux copies. Après fermeture, une lecture SQLite
  indépendante retrouve la note synthétique dans la copie
  corrigée et une table vide dans la copie fautive. La mise au
  premier plan a demandé de reconnecter la session. Le vGPU
  désactivé permet ce parcours. Le profil définit aussi le périmètre
  du courtier MVP pour les rapports JSON et les diffs unifiés.
  [Profil et parcours clavier](../../bench/harness/sandbox_profile.md)
- Le profil avec `ProtectedClient=Enable` a démarré. L'import en
  lecture seule et le parcours clavier passent, avec la note présente
  dans SQLite sur la référence corrigée et absente sur le témoin.
  Le jeton du processus client externe est hors AppContainer.
  La frontière interne reste non attestée et le profil nominal
  s'appuie sur les contrôles de confinement vérifiés.
  [Essai Protected Client](../../bench/harness/sandbox_profile.md#essai-protected-client)
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
La [consigne v2 sans exemples](../../bench/communication/qwen35-2b-fr-v2.json)
valide **4/6 en 18,20–19,07 s par fiche** sur ces mêmes six fiches.
Elle corrige l'avis d'échec. La clarification et l'ordre des actions
échouent encore. [Comparaison v1 et v2](../../bench/measurements_phase0.md#rejeu-avec-la-consigne-v2-sans-exemples)
La [consigne v3](../../bench/communication/qwen35-2b-fr-v3.json) obtient
**2/6 en 21,04–26,34 s par fiche**. Elle rétablit les deux actions
ordonnées et leur condition. La clarification reste déclarative.
L'attente, l'avis d'échec et la demande d'accord régressent.
[Comparaison v2 et v3](../../bench/measurements_phase0.md#rejeu-avec-la-consigne-v3-sans-exemples)
La [consigne v4](../../bench/communication/qwen35-2b-fr-v4.json) obtient
**2/6 en 20,73–21,43 s par fiche**. La clarification et l'ordre des
actions restent en échec. L'attente et la demande d'accord régressent
par rapport à la v2.
[Comparaison v2 et v4](../../bench/measurements_phase0.md#rejeu-de-la-v4-à-partir-de-la-v2)
La v2 avec [deux gabarits locaux](../../bench/communication/templates.py)
valide **6/6** sur les mêmes fiches. Les quatre sorties Rbitnet sont
identiques à celles de la v2. Les gabarits valident la clarification
et l'ordre. La série dure **74,29 s**, contre 114,94 s en v2 seule.
[Comparaison par fiche](../../bench/measurements_phase0.md#communication-v2-avec-deux-gabarits-déterministes)
La v2 et les deux gabarits sont retenus pour le parcours courant.
Après passage du 2B au 0,8B dans le processus dédié, `/ready` rend
toujours HTTP 200 et `/v1/models` conserve le même identifiant logique.
Le mappage GGUF distingue les deux modèles.
Après déchargement, `/ready` recharge le 2B initial. L'adaptateur
doit lier l'admission à la version des poids.
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
Le rejeu v2 des mêmes fiches est dans
`rbitnet-communication-v2/qwen35-2b-fr-validation-v2.json`.
Le rejeu v3 est dans
`rbitnet-communication-v3/qwen35-2b-fr-validation-v3.json`.
Le rejeu v4 est dans
`rbitnet-communication-v4/qwen35-2b-fr-validation-v4.json`.
Le rejeu v2 avec gabarits est dans
`rbitnet-communication-hybrid/qwen35-2b-fr-hybrid-v1.json`.
Les preuves de canaux, de focus et d'identité du GGUF sont dans
`phase0-closure/`. Le témoin fautif après reconnexion est dans
`notes-faulty-reconnected.json`.
Les essais de presse-papiers sont dans `clipboard-nominal-active.json`
et `clipboard-disabled-active.json`. Les autres relevés sont dans
`protected-client.json`, `protected-faulty.json`,
`protected-import.json` et `protected-client-token.json`.

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

## Entrée en phase 1

Le banc Notes utilise le profil durci avec vGPU désactivé. La
compatibilité d'un profil avec vGPU activé reste à mesurer si une
tâche le requiert. Une preuve de la frontière Protected Client
devient nécessaire si un profil choisit de s'appuyer sur elle.
L'adaptateur de communication, l'export de diff et l'intégration
OCR du formulaire relèvent du parcours de phase 1. Le coffre et la
restauration sont à implémenter sur le contrat versionné et à éprouver
pendant les phases 1 et 2.
[Plan de développement](development-plan.md#phase-1--parcours-bureaucode-et-évolution-bornée-mvp)
