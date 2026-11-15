# Mesures Phase 0 — inférence CPU

Protocole : invite fixe (« En une phrase : que doit faire une fonction
save_note ? »), `POST /api/generate` (`stream: false`,
`options: {num_gpu: 0}`), 3 passages par modèle, machine au repos relatif.
`ollama ps` confirme `100% CPU` (runner `llamacpp`) sur les deux modèles ;
le contexte effectif constaté est 8192 (contre 40 960 / 131 072 annoncés —
limite de configuration, pas du poids). La VRAM observée pendant les essais
(~5 Go) n'est pas attribuable à Ollama (affichage et autres processus).

## Ollama, profilage du 14 novembre

| Modèle | Passage | Mur (s) | Tokens | Éval (ms) | Chargt (ms) |
|---|---|---|---|---|---|
| rbitnet-bench-llama32-1b:q4_k_m (1,2 B, Q4_K_M) | 1 | 1,3 | 61 | 1189 | 7 |
| idem | 2 | 0,7 | 35 | 663 | 8 |
| idem | 3 | 0,9 | 43 | 907 | 9 |
| rbitnet-bench-qwen3-8b:q4_k_m (8,2 B, Q4_K_M) | 1 | 54,9 | 425 | 49319 | 5387 |
| idem | 2 | 45,3 | 388 | 45181 | 8 |
| idem | 3 | 50,2 | 421 | 49990 | 9 |

Données brutes : `$env:TEMP/akasha-cpu-runs.json` (session de mesure).

## Lecture (3 essais = profilage, spec §12.2)

- Le 1 B répond en ~1 s CPU : candidat rôle communication/bac.
- Le 8 B (raisonnement activé) produit ~400 tokens en ~50 s CPU : trop
  verbeux pour une boucle interactive sans consigne de concision ou
  désactivation du raisonnement ; à cadrer avant tout seuil (spec §2.4).
- Licence : `qwen2.5:0.5b` annonce Apache-2.0 ; les deux modèles candidats
  n'exposent aucune licence via `ollama show` — provenance à compléter
  avant la Phase 4 (spec §19.4).
- Moteur réel : processus `llama-server` (un par modèle), 100 % CPU.
- RAM résidente mesurée (privée) : 1,2 Go (modèle 1 B), 6,2 Go (modèle
  8 B) — compatibles mono-poste 61,6 Go ; VRAM non sollicitée (CPU seul).
- Concurrence : 2 générations 1 B en parallèle, 2/2 réussies, mur 2,3 s
  (contre ~1 s en solo) — pas de sérialisation ni d'erreur.
- Reprise : `ollama stop` unitaire (n'accepte qu'un modèle par appel),
  `ollama ps` vide vérifié, rechargement à froid 1 B en 816 ms puis
  inférence OK (mur 1,1 s). Cycle arrêt → preuve d'éviction → reprise OK.
- Ce profilage Ollama couvre jusqu'à deux requêtes simultanées.
  La campagne GPU relève de la phase 1 (spec §6.2, §12.2).


## Qualification native de Rbitnet — 15 novembre

Poste de référence Windows, Ryzen 7 9800X3D et 61,61 Gio de RAM utilisable.
Binaire `rbitnet-server.exe` identifié par SHA-256 et démarré sur loopback,
avec `RBITNET_BACKEND=cpu`, 4 admissions simultanées et le batching continu
désactivé. Les sommes de contrôle ont été relues avant le démarrage.
Le cache disque Windows est resté en place. Le démarrage du processus
sur Qwen3.5-0.8B jusqu'à `/ready` a pris **0,98 s**.

### Provenance et licences

Les SHA-256 locaux correspondent aux métadonnées LFS publiées aux
révisions ci-dessous. Les cartes des modèles et des tokenizers déclarent
Apache 2.0.

| Usage | Artefact et révision vérifiée | Licence |
| --- | --- | --- |
| Communication, 0,8B | [Unsloth Qwen3.5-0.8B Q8_0, révision 6ab4614](https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/blob/6ab461498e2023f6e3c1baea90a8f0fe38ab64d0/Qwen3.5-0.8B-Q8_0.gguf) | Apache 2.0 |
| Communication, comparaison 2B | [Unsloth Qwen3.5-2B Q8_0, révision f6d5376](https://huggingface.co/api/models/unsloth/Qwen3.5-2B-GGUF/revision/f6d5376be1edb4d416d56da11e5397a961aca8ae?blobs=true) | Apache 2.0 |
| Code, 8B | [Unsloth Qwen3-8B Q4_K_M, révision a6adef1](https://huggingface.co/unsloth/Qwen3-8B-GGUF/blob/a6adef130ffb23ddaf1a62fec9dced968c9bc482/Qwen3-8B-Q4_K_M.gguf) | Apache 2.0 |
| Tokenizer partagé des Qwen3.5 | [Qwen3.5-0.8B, révision 2fc0636](https://huggingface.co/Qwen/Qwen3.5-0.8B/blob/2fc06364715b967f1860aea9cf38778875588b17/tokenizer.json) · [Qwen3.5-2B, révision 15852e8](https://huggingface.co/api/models/Qwen/Qwen3.5-2B/revision/15852e8c16360a2fea060d615a32b45270f8a8fc?blobs=true) | Apache 2.0 |
| Tokenizer Qwen3-8B | [Qwen3-8B, révision b968826](https://huggingface.co/api/models/Qwen/Qwen3-8B/revision/b968826d9c46dd6066d109eabc6255188de91218?blobs=true) | Apache 2.0 |

Le fichier Cargo `.d` du binaire pointe vers le checkout local Rbitnet.
La version Cargo relevée est **0.2.0**, sous **MIT**. Le journal Git situe
`d8b1da630eacefb183bd846abef77916278a8265` à la tête du checkout près de
l'heure du build et le cache Cargo indique `rustc 1.94.1`. Le lien entre
ce commit exact et les octets du binaire reste une inférence.
[Sources et licence Rbitnet](https://github.com/azerothl/Rbitnet) · [Empreintes locales](../docs/plans/phase0_status.md#inférence-cpu-et-réparation-des-notes)

### Communication en français

Avec un format de chat sans raisonnement, le 0,8B produit des phrases
exploitables. Sur six demandes en texte libre avec consigne de rôle, il
a préservé tous les faits dans deux cas. Les autres réponses inversent
les rôles, reformulent la consigne, modifient l'objet ou omettent la
question attendue. [Format de chat Qwen3.5](https://huggingface.co/Qwen/Qwen3.5-0.8B/blob/main/chat_template.jinja)

Sur six fiches distinctes à champs explicites et avec des exemples
génériques dans la consigne, le 0,8B réussit **3/6** et le 2B **4/6**.
Relecture selon les faits présents, l'auteur des actions et l'intention
attendue. Les deux modèles posent les questions de clarification et
d'autorisation et attendent la décision de l'utilisateur. Les deux
omettent un élément du compte rendu chiffré et un élément de l'avis
d'échec. Seul le 2B conserve l'ordre et l'auteur des deux actions dans
le dernier cas. Temps mur **8,00–9,53 s** pour le 0,8B et
**14,65–15,93 s** pour le 2B sur ces fiches. La qualification du
spécialiste communication reste ouverte.

#### Candidats supplémentaires sur les six fiches

Spark-X2.5-1.7B et Llama 3.2 1B Instruct ont chargé leur GGUF Q4_K_M
et produit six réponses sur le même binaire Rbitnet en CPU. Les fiches,
la consigne système, la température 0, la graine 773 et la limite de
64 jetons sont celles de la comparaison Qwen. Chaque architecture
utilise son format de conversation et ses marqueurs de fin de tour.

| Modèle | Fiches validées | Temps mur par fiche | Licence vérifiée |
| --- | ---: | ---: | --- |
| Spark-X2.5-1.7B Q4_K_M | **1/6** | 20,02–22,32 s | Apache 2.0 |
| Llama 3.2 1B Instruct Q4_K_M | **0/6** | 4,27–5,29 s | Llama 3.2 Community License |

Spark valide la question de clarification. Les six générations atteignent
la limite. Le compte rendu chiffré et l'ordre des actions commencent
correctement puis continuent avec du texte hors consigne. La réponse
d'attente répète sa phrase et la demande d'accord devient une question
sur la date. Llama transforme plusieurs fiches en demandes d'autorisation.
Sa question d'export est précédée d'un exemple recopié, étranger à la
fiche. L'évaluation porte sur la réponse complète, avec conservation
des faits et de l'auteur des actions.

Les empreintes des deux GGUF et de leurs tokenizers concordent avec
les métadonnées des révisions suivantes. Pour Spark, la configuration
du tokenizer correspond également au blob Git publié.

| Artefact | Source épinglée | SHA-256 local |
| --- | --- | --- |
| Spark 1,7B Q4_K_M | [XHToken, révision 1f7fa33](https://huggingface.co/api/models/XHToken/Spark-X2.5-1.7B-GGUF/revision/1f7fa33b1245c14730da39e125714ad3a327901b?blobs=true) | `902bde2522394954ac17821b3e5fd0df02defbc6944f122253f2580acf0503f4` |
| Tokenizer Spark | [XHToken, révision 14d6e83](https://huggingface.co/api/models/XHToken/Spark-X2.5-1.7B/revision/14d6e83c13c7add2b62a7c39b2131f4ed1cddcf8?blobs=true) | `710cce15cf3565674c499f9413997c6e8101f2bdd96245cff8f0311fb501248c` |
| Llama 3.2 1B Instruct Q4_K_M | [Unsloth, révision b69aef1](https://huggingface.co/unsloth/Llama-3.2-1B-Instruct-GGUF/blob/b69aef112e9f895e6f98d7ae0949f72ff09aa401/Llama-3.2-1B-Instruct-Q4_K_M.gguf) | `3f5a22426976ab26cfe84dba63c1d08391717abb1af893e10f1b2968d862dcc1` |
| Tokenizer Llama | [Unsloth, révision 5a8abab](https://huggingface.co/api/models/unsloth/Llama-3.2-1B-Instruct/revision/5a8abab4a5d6f164389b1079fb721cfab8d7126c?blobs=true) | `6b9e4e7fb171f92fd137b777cc2714bf87d11576700a1dcd7a399e7bbe39537b` |

[Licence du modèle Spark](https://huggingface.co/XHToken/Spark-X2.5-1.7B) ·
[Licence et langues prises en charge par Llama](https://huggingface.co/meta-llama/Llama-3.2-1B-Instruct)

Les sorties et les invites sont dans `rbitnet-communication-alternative/spark.json`
et `rbitnet-communication-alternative/llama.json`, sous le dossier de
preuves de la phase 0. Le choix du spécialiste communication reste ouvert.

#### Ajustement de la consigne de Qwen3.5-2B

Le bilan initial indiquait la durée de 7,4 secondes et omettait les
3 réussites sur 3. L'avis initial sur la note mentionnait le risque de
perte et omettait l'échec de la sauvegarde. La consigne révisée demande
de conserver le score et la durée, puis de nommer l'opération qui a
échoué et d'indiquer sa conséquence éventuelle. Deux exemples sur les
capteurs et l'agenda illustrent ces règles.

La première révision valide **5/6** fiches en **25,41–26,72 s** par
fiche. Elle rapporte l'échec de la sauvegarde et le risque de perte.
Le bilan attribue le score aux notes avec « 3 notes sur 3 en 7,4
secondes ». La seconde révision précise que le score
porte sur l'opération évaluée et illustre la forme « X réussites sur Y ».

La seconde révision valide **6/6** fiches en **27,49–28,36 s** par fiche
et **170,46 s** en incluant le démarrage et l'arrêt du serveur. Les six
requêtes renvoient HTTP 200 et s'arrêtent avant la limite de génération.

- Bilan corrigé « Les tests locaux des notes ont donné 3 réussites sur 3 en 7,4 secondes. »
- Avis corrigé « La sauvegarde de la note a échoué et la note peut être perdue. »

Les quatre autres réponses sont identiques à celles du premier rejeu
et satisfont toujours les critères de leur fiche.

Les deux rejeux utilisent les six fiches d'origine, les mêmes empreintes
du GGUF, du tokenizer et du binaire Rbitnet en CPU, le format sans
raisonnement, la température 0, la graine 773 et la limite de 64 jetons.
Le score mesure la correction sur les fiches qui ont servi à ajuster
la consigne.
Les consignes complètes, sorties, journaux et le script de rejeu sont
dans `rbitnet-communication-prompt/` sous le dossier de preuves de la
phase 0. Le rapport de la seconde révision est `revised-qwen-2b-score.json`.

#### Validation de la consigne figée sur six nouvelles fiches

La [consigne v1](communication/qwen35-2b-fr-v1.json) reprend le texte
système exact du 6/6, avec son SHA-256 et ses paramètres d'inférence.
Les [fiches et critères](communication/cases-fr-validation-v1.json)
ont été fixés avant l'exécution. Chaque requête contient la consigne
système et une fiche. Le même binaire Rbitnet charge les mêmes poids et
le même tokenizer sur CPU. Le temps par fiche va de l'envoi de la
requête HTTP à la lecture de la réponse complète.

Qwen3.5-2B Q8_0 valide **3/6** nouvelles fiches. Les six requêtes
renvoient HTTP 200 et s'arrêtent normalement. La série dure **175,70 s**
de bout en bout, démarrage et arrêt du serveur compris.

| Fiche | Verdict | Temps mur | Observation |
| --- | --- | ---: | --- |
| Attente | Réussite | 28,28 s | L'utilisateur relit le sommaire. L'assistant attend sa décision avant publication. |
| Clarification | Échec | 29,12 s | Demande la date de rendez-vous reprise d'un exemple. Le dossier à archiver reste indéterminé. |
| Résultat chiffré | Réussite | 29,72 s | Attribue 7 réussites sur 9 aux tests de connexion au serveur local et conserve les 11,8 secondes. |
| Avis d'échec | Échec | 28,65 s | Reprend mot pour mot l'exemple de l'agenda et omet l'échec d'impression ainsi que le risque de retard d'expédition. |
| Demande d'accord | Réussite | 28,27 s | Demande l'autorisation de déplacer les photos du projet vers Archives. |
| Ordre des actions | Échec | 28,71 s | Laisse la vérification des montants à l'utilisateur et attend sa validation. Omet la transmission du devis. |

Les réponses intégrales, les relevés HTTP, le journal et le script sont
dans `rbitnet-communication-holdout/` sous le dossier de preuves de
la phase 0. Le rapport est `qwen35-2b-fr-validation-v1.json`.

### Chargement, changements et reprise

- Six changements dans le même PID. Le modèle attendu est visible
  dans les mappages Windows et répond après chaque changement.
  `POST /v1/admin/reload` puis `/ready` prend **1,00–1,19 s**
  vers le 8B, et **1,30–1,44 s** vers le 0,8B. La première réponse
  suivante prend respectivement **3,26–4,10 s** et **0,93–1,03 s**.
- Déchargement contrôlé du 8B en **0,55 s**. Son mappage GGUF disparaît.
  Après 500 ms sans sonde, le working set passe de **6 833 à 19 Mio**
  et la mémoire privée engagée de **2 380 à 13 Mio**. Un appel ultérieur
  à `/ready` a rechargé le **0,8B initial** en **0,36 s**, avec HTTP 200.
  Dans ce profil, `/ready` peut rétablir la résidence du modèle initial.
  L'intégration doit vérifier l'identité du
  modèle actif après la sonde.
- Un chemin invalide lors d'un rechargement à chaud donne HTTP 500
  `LoadFailed` et le 8B actif continue à répondre. Au démarrage avec un
  fichier absent, `/health` donne 200. `/ready` et l'inférence donnent
  503 `LoadFailed`. Un rechargement valide rétablit la disponibilité
  en **0,82 s** sur le même PID, puis une réponse valide en **0,87 s**.

### Concurrence, saturation et mémoire

Trois rafales à chaque niveau et pour chaque modèle, déclenchées par une
barrière. Invites synthétiques d'environ 30 jetons, sortie plafonnée à
8 jetons avec vérification d'un marqueur de réponse. Durée mesurée du
lancement de la rafale à la dernière réponse.

| Requêtes par rafale | 0,8B, durée | 8B, durée | Résultat dans chacune des 3 rafales, pour les deux modèles |
| ---: | ---: | ---: | --- |
| 1 | 1,15–1,21 s | 3,53–3,58 s | 1 réponse |
| 2 | 2,18–2,23 s | 6,97–7,33 s | 2 réponses |
| 4 | 4,19–4,23 s | 13,87–14,28 s | 4 réponses |
| 8 | 4,21–4,28 s | 14,63–15,01 s | 4 réponses, 4 refus 503 `rate_limit_error` |

Les refus arrivent en **1,25 à 18,65 ms** dans les deux profils cumulés.
Le temps de rafale croît presque avec le nombre de réponses admises
dans ces conditions. Ces chiffres caractérisent le plafond d'admission
configuré et la charge courte testée.

| Mesure Windows sous charge | 0,8B | 8B |
| --- | ---: | ---: |
| Pic échantillonné du working set | 1 115 Mio | 6 858 Mio |
| Pic échantillonné de mémoire privée engagée | 342 Mio | 2 407 Mio |
| RAM disponible minimale sur l'hôte | 22,31 Gio | 16,76 Gio |

Échantillonnage toutes les 100 ms par Windows PSAPI et
`GlobalMemoryStatusEx`. Les crêtes agrègent poids résidents, caches et
allocations temporaires du processus. Le compteur WDDM n'a exposé aucune
instance pour le PID lors des relevés. Les journaux confirment le backend
CPU. La VRAM par PID reste indisponible pour cette campagne.

Rapports et scripts locaux dans `rbitnet-qualification-cpu/` sous le
[dossier de preuves indiqué dans le statut](../docs/plans/phase0_status.md#inférence-cpu-et-réparation-des-notes).
`qualification.json` contient les relevés et les sorties des requêtes.
`unload-only.json` contient les mappages et la mémoire avant et après
`/ready`. Les deux comparaisons de communication à fiches structurées
sont dans `structured-communication.json` et `structured-communication-2b.json`.
