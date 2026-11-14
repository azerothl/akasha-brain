# Akasha Brain — Notes de recherche

**Statut :** bibliographie annotée de la spécification v0.2 (entrées 1-9 : v0.1 ; compléments : seconde passe du 2026-11-13)  
**Consultation :** 2026-11-13

Les travaux cités décrivent des approches et des démonstrations circonscrites. Ils étayent des motifs d’architecture; ils ne prouvent pas qu’une architecture donnée fonctionnera dans tous les domaines.

## Synthèse

Les recherches consultées soutiennent plusieurs choix de conception : orchestration de capacités hétérogènes, prédiction vidéo et action-conditionnée, apprentissage de compétences sans fine-tuning immédiat, et nécessité d’évaluer la communication et la contribution des agents. Elles soulignent aussi que l’orchestration peut être un goulot d’étranglement et qu’une représentation prédictive n’est pas automatiquement une géométrie explicite ou une politique d’action.

## JEPA et modèles du monde

### 1. I-JEPA

**Assran et al., 2023 — “Self-Supervised Learning from Images with a Joint-Embedding Predictive Architecture.”**

- [Page de recherche Meta](https://ai.meta.com/research/publications/self-supervised-learning-from-images-with-a-joint-embedding-predictive-architecture/)
- [Article CVPR 2023 sur arXiv](https://arxiv.org/abs/2301.08243)

I-JEPA prédit les représentations de régions cibles d’une image à partir du contexte. L’approche apprend une représentation visuelle auto-supervisée sans objectif de génération pixel par pixel.

**Implication :** une représentation latente peut être une capacité de perception et de prédiction. Elle ne livre pas automatiquement les coordonnées métriques ou repères nécessaires à une manipulation robotique; les contrats spatiaux explicites restent nécessaires lorsque le cas d’usage les exige.

### 2. V-JEPA 2

**Assran et al., 2025 — “V-JEPA 2: Self-Supervised Video Models Enable Understanding, Prediction and Planning.”**

- [Article primaire sur arXiv](https://arxiv.org/abs/2506.09985)
- [Présentation officielle Meta AI](https://ai.meta.com/blog/v-jepa-2-world-model-benchmarks/)

Les auteurs rapportent le préentraînement sur plus d’un million d’heures de vidéo et le post-entraînement de V-JEPA 2-AC, un modèle conditionné par les actions, avec moins de 62 heures de vidéos robotiques non annotées. Ils décrivent des tâches de prise et déplacement d’objets planifiées vers des objectifs visuels, avec des bras Franka dans deux laboratoires.

**Implication :** séparer représentation/prediction, dynamique action-conditionnée et adaptateur de commande. Cette démonstration ne prouve pas qu’un modèle couvre arbitrairement tous les environnements, ni que la représentation visuelle produit une carte 3D métrique. Couverture des actions, repères, incertitude et évaluation réelle restent importants.

## Orchestration et modèles spécialisés

### 3. HuggingGPT

**Shen et al., 2023 — “HuggingGPT: Solving AI Tasks with ChatGPT and its Friends in Hugging Face.”**

- [Article primaire arXiv](https://arxiv.org/abs/2303.17580)
- [Publication NeurIPS 2023](https://proceedings.neurips.cc/paper_files/paper/2023/hash/77c33e6a367922d003ff102ffb92b658-Abstract-Conference.html)

HuggingGPT utilise un modèle de langage contrôleur pour planifier, sélectionner des modèles à partir de descriptions, exécuter les sous-tâches et agréger les résultats. Le contrôleur décrit dans le travail est ChatGPT.

**Implication :** registre de capacités, dépendances et agrégation sont des motifs pertinents. Akasha Brain peut évaluer un superviseur plus petit, un moteur déterministe ou une combinaison; les résultats de HuggingGPT ne démontrent pas la performance sans grand contrôleur.

### 4. Collaboration de petits agents

**Żywot et al., 2026 — “Can Small Agents Collaborate to Beat a Single Large Language Model?”**

- [Article primaire arXiv](https://arxiv.org/abs/2601.11327)

Le travail compare un orchestrateur et des sous-agents spécialisés sur des tâches de recherche factuelle, raisonnement à plusieurs étapes, questions scientifiques et mathématiques. Il rapporte que le raisonnement de l’orchestrateur explique une part majeure des gains; activer le raisonnement des sous-agents apporte des bénéfices limités ou négatifs selon les configurations.

**Implication :** mesurer contribution de l’orchestrateur, des nœuds et des liens; ne pas augmenter uniformément tous les spécialistes. Les résultats sont conditionnels aux modèles, tâches et protocoles étudiés.

### 5. Switch Transformer et MoE

**Fedus, Zoph et Shazeer, 2022 — “Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity.”**

- [Article primaire JMLR](https://www.jmlr.org/papers/v23/21-0998.html)

Switch Transformer route des tokens vers des experts internes d’un Transformer afin d’activer une partie des paramètres. Le papier décrit les questions de communication, complexité et stabilité de ce paradigme.

**Implication :** une MoE interne n’est pas le même objet qu’un graphe de capacités indépendantes. Les deux approches peuvent coexister; un nœud externe pourrait lui-même être une MoE.

## Expérience, mémoire et compétences

### 6. Voyager

**Wang et al., 2023 — “Voyager: An Open-Ended Embodied Agent with Large Language Models.”**

- [Article primaire arXiv](https://arxiv.org/abs/2305.16291)
- [Version OpenReview](https://openreview.net/forum?id=ehfRiF0R3a)

Voyager combine curriculum automatique, bibliothèque croissante de compétences exécutables, feedback de l’environnement, erreurs d’exécution et auto-vérification. L’agent utilise le modèle comme boîte noire; la bibliothèque de compétences peut croître sans mise à jour de ses poids.

**Implication :** une trace peut être promue en compétence versionnée après vérification. Chaque compétence doit inclure préconditions, environnement et conditions d’échec.

### 7. Reflexion

**Shinn et al., 2023 — “Reflexion: Language Agents with Verbal Reinforcement Learning.”**

- [Article primaire arXiv](https://arxiv.org/abs/2303.11366)

Reflexion convertit des signaux de retour en réflexions textuelles conservées dans une mémoire épisodique, influençant les essais suivants sans mise à jour des poids.

**Implication :** la sélection, la mémoire et la réutilisation sont une première boucle d’apprentissage avant le fine-tuning. Une réflexion reste une hypothèse si elle n’est pas corroborée par un résultat.

### 8. ExpeL

**Zhao et al., 2023 — “ExpeL: LLM Agents Are Experiential Learners.”**

- [Article primaire arXiv](https://arxiv.org/abs/2308.10144)

ExpeL extrait connaissances et expériences depuis des tâches, puis les récupère pour guider les décisions ultérieures, sans exiger un fine-tuning paramétrique.

**Implication :** une mémoire d’expérience doit inclure contexte, provenance et confiance afin de distinguer un succès isolé d’une règle transférable.

## Coordination et évaluation

### 9. AgentWorld

**Shu et al., 2026 — “AgentWorld: Benchmarking Long-Horizon Collaboration of Multi-agent LLMs.”**

- [Article primaire arXiv](https://arxiv.org/abs/2609.31590)

AgentWorld étudie la collaboration multi-agent de longue durée dans un environnement de jeu avec rôles et ressources. Les auteurs rapportent des problèmes de communication, de confusion de rôles et de maintien d’un plan partagé dans les configurations étudiées.

**Implication :** plus de nœuds n’assure pas une meilleure coordination. Les contrats de messages, état partagé, attribution des sous-tâches et mesure de contribution doivent être explicitement évalués.

## Compléments v0.2 — seconde passe (2026-11-13)

Périmètre : premier terrain **bureau & code local**. Seules les sources primaires ou officielles effectivement récupérées sont citées ; les références repérées sans récupération (Prefect/Dagster, SGLang/LM Studio/TGI, Terminal-Bench, OSWorld 2.0) sont marquées « non évaluées » et ne fondent aucune décision.

### Orchestration et runtime

- **LangGraph (documentation officielle).** Graphe explicite état/nœuds/liens compilé et validé, checkpointer durable (SQLite en mono-poste), interruptions sérialisables pour l'approbation humaine, retry bornée et timeouts par nœud. [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence.md) · [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) · [Fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance) — **Implication :** satisfait les Phases 0-3 (spec §8.4) ; la limite de récursion se fige sur la version installée, les sources secondaires divergent. Aucun moteur ne fournit registre, permissions ni évolution : à construire au-dessus.
- **Temporal (documentation officielle, principes seulement).** Routeur pur et déterministe, effets en activités journalisées et idempotentes. [Workflow definition](https://docs.temporal.io/workflow-definition) · [Activity definition](https://docs.temporal.io/activity-definition) — **Implication :** retenir les principes, ne pas déployer le service en Phase 0-1 (surdimensionné pour une tâche locale courte). Le routage appris devient une activité journalisée, pas une étape du workflow.

### Contrats, registre et protocoles

- **MCP, spécification 2025-11-25.** Outils via JSON-RPC, `Tool {inputSchema, outputSchema, annotations}` ; les hints (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) sont non autoritatives. [Spécification](https://modelcontextprotocol.io/specification/2025-11-25) — **Implication :** noyau du manifeste (spec §6.1) ; permissions normatives séparées, vérifiées hors modèle. Le Registry officiel est en preview : ne pas en faire une dépendance.
- **A2A et MCP.** Protocoles complémentaires : MCP vertical (agent → outils), A2A horizontal (agent → agent opaque). [A2A et MCP](https://a2a-protocol.org/latest/topics/a2a-and-mcp/) — **Implication :** MCP intra-système par défaut, A2A différé à la bordure externe.
- **JSON Schema 2020-12, PROV-O, SLSA.** Schémas versionnés en SemVer exacte ; provenance alignée PROV (Entity/Activity/Agent) et patron SLSA (digest SHA-256, predicate typé). [JSON Schema Core](https://json-schema.org/draft/2020-12/json-schema-core) · [PROV-O](https://www.w3.org/TR/prov-o/) · [SLSA Provenance](https://slsa.dev/spec/v1.0/provenance) — **Implication :** spec §6.1. Trou connu : provenance des modèles (jeu d'entraînement, licence lisible par machine) non couverte par les sources officielles récupérées.

### Routage et petits modèles locaux

- **Ollama / llama.cpp.** Inférence locale à API compatible OpenAI (sous-ensemble à vérifier par capacité) ; le contexte par défaut et l'offload CPU/GPU conditionnent la latence. [Ollama FAQ](https://docs.ollama.com/faq) · [Quantize](https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/quantize/README.md) — **Implication :** backends candidats, pas un défaut d'architecture (spec §6.2, v0.4). À mesurer : montage et démontage des poids entre SSD, RAM et VRAM, journalisés, sans redémarrer le processus. Toute quantization reste liée à son évaluation.
- **vLLM / PagedAttention (arXiv:2309.06180).** Gain de débit en concurrence multi-requêtes. [Article](https://arxiv.org/abs/2309.06180) — **Implication :** backend candidat pour un service multi-requêtes, pas le gestionnaire de résidence du poste. Le contrat Akasha est le placement hétérogène des poids (§6.2), pas le débit d'un seul modèle servi en continu.
- **RouteLLM, FrugalGPT, cascades, speculative decoding.** Routage appris, cascade avec deferral calibré et abstention, brouillon/vérificateur intra-nœud. [RouteLLM](https://arxiv.org/abs/2406.18665) · [FrugalGPT](https://arxiv.org/abs/2305.05176) · [Cascades (Gupta et al.)](https://arxiv.org/abs/2404.10136) · [Speculative decoding](https://arxiv.org/abs/2211.17192) — **Limite :** chiffres issus de benchmarks de dialogue et d'API 2023-2025 ; aucun n'est repris comme seuil (spec §8.4). L'incertitude exige méthode de calibration et scores ECE/Brier [survey](https://arxiv.org/abs/2311.08298).

### Mémoire et compétences

- **CoALA, Generative Agents, MemGPT, mémoire épisodique.** Taxonomie travaillée/épisodique/sémantique/procédurale, journal append-only, pondération récence/importance/pertinence, paging du contexte, consolidation comme étape explicite. [CoALA](https://arxiv.org/abs/2309.02427) · [Generative Agents](https://arxiv.org/html/2304.03442v2) · [MemGPT](https://arxiv.org/abs/2310.08560) — **Implication :** spec §10.1 ; Akasha sépare le journal d'audit minimal append-only du contenu d'expérience effaçable.
- **Mem0, HippoRAG, Zep/Graphiti, A-MEM.** Extraction sélective, retrieval par graphe + PageRank, faits bi-temporels, notes liées évolutives. [Mem0](https://arxiv.org/abs/2504.19413) · [HippoRAG](https://arxiv.org/abs/2405.14831) · [Zep](https://arxiv.org/abs/2501.13956) · [A-MEM](https://arxiv.org/abs/2502.12110) — **Limite :** domaines dialogue/QA ; la réécriture de notes anciennes (A-MEM) exige versionnement pour rester compatible avec la provenance (§16).
- **SkillWeaver, TroVE, Library Drift.** Compétences comme API testées après pratiques répétées ; élagage périodique ; l'accumulation sans cycle de vie dégrade le retrieval. [SkillWeaver](https://arxiv.org/abs/2504.07079) · [TroVE](https://arxiv.org/abs/2401.12869) · [Library Drift](https://arxiv.org/abs/2605.19576) — **Limite :** web et code synthétique ; seuils de retirement à calibrer sur le terrain Akasha.
- **Non démontré :** aucun retrieval de compétences gaté par préconditions n'est validé expérimentalement contre la similarité ; c'est une hypothèse Akasha à benchmarker (Phase 2). Idem pour la suppression vérifiable et sa propagation aux dérivés.

### Modèles du monde bureau & code

- **OSWorld.** 369 tâches réelles évaluées par l'état final exécuté ; l'espace d'observation distingue screenshot, arbre d'accessibilité et combinaison. [Article](https://arxiv.org/abs/2404.07972) — **Implication :** état canonique = accessibilité/DOM + état applicatif + fichiers avant pixels (spec §9.7) ; scores de 2024 datés, à re-mesurer.
- **CUWM, GUI-JEPA, LGWM, CWM.** Prédiction de delta symbolique d'écran, scoreur latent de candidats, vérificateur de transition, prédiction d'exécution de code. [CUWM](https://arxiv.org/abs/2602.17365) · [GUI-JEPA](https://arxiv.org/abs/2610.36877) · [LGWM](https://arxiv.org/abs/2610.11942) · [CWM](https://arxiv.org/abs/2510.02387) — **Limites :** Office seul, mobile seul, diagnostic seul selon le cas ; chez GUI-JEPA, un prédicteur aléatoire égale le prédicteur pré-entraîné en ablation — exiger cette ablation avant tout crédit à une dynamique apprise. Aucun transfert direct de V-JEPA vers les écrans de bureau n'est démontré.

### Évaluation, observabilité, sécurité

- **SWE-bench, Agentless, contamination.** Tâches de code vérifiées par tests de dépôt ; une baseline fixe simple (localisation → réparation → validation) devance des agents autonomes comparés ; la mémorisation des dépôts publics impose cas réservés et tâches fraîches. [SWE-bench](https://arxiv.org/abs/2310.06770) · [Agentless](https://arxiv.org/abs/2407.01489) · [Contamination](https://arxiv.org/abs/2506.12286) — **Implication :** spec §12.1.
- **OpenTelemetry GenAI.** Spans d'agent en statut Development, en cours de déplacement vers un dépôt dédié. [Conventions GenAI](https://opentelemetry.io/docs/specs/semconv/gen-ai/) — **Implication :** couche d'adaptation épinglée, jamais de contrat public ni de prompt brut dans les traces (spec §8.4).
- **Sandbox et injection.** Isolation renforcée (noyau en espace utilisateur, microVM) selon la confiance ; la configuration officielle Windows Sandbox indique réseau, presse-papiers et entrée audio activés par défaut ; les dossiers hôtes mappés sont inscriptibles par défaut et leurs changements persistent après fermeture ; le vGPU peut accroître la surface d'attaque. L'injection indirecte via contenus parsés reste un risque majeur. [gVisor](https://gvisor.dev/docs/architecture_guide/intro/) · [Configuration Windows Sandbox](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file) · [OWASP LLM01](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) · [Argo Rollouts (canary)](https://argo-rollouts.readthedocs.io/en/stable/features/canary/) — **Implication :** spec §13.5-13.7, §11.6 ; profil durci à mesurer et ordre de force des paliers à valider sur un même modèle de menace.

## Principes proposés pour Akasha Brain

Ces principes sont une synthèse d’architecture, pas des résultats expérimentaux garantis.

1. Définir contrats et runtime versionné avant la mutation dynamique du graphe.
2. Évaluer séparément capacité, liaison, workflow et réussite de bout en bout.
3. Chercher erreurs de schéma, unités, repères et routage avant un modèle manquant.
4. Promouvoir une compétence seulement après vérification adaptée.
5. Séparer représentation visuelle, état spatial, dynamique action-conditionnée et commande.
6. Utiliser observations réelles pour vérifier les prédictions; traiter les rollouts générés comme hypothèses.
7. Promouvoir les changements avec comparaison, limites de risque et rollback.
8. Utiliser solveur ou outil déterministe lorsque son contrat répond mieux à la tâche.
9. Accepter modèles locaux, distants, génératifs, discriminatifs, prédictifs et non neuronaux.
10. Attribuer les gains aux nœuds et liens pour établir quelles connexions apportent une capacité.
11. Sur le terrain bureau/code, évaluer par l'état final exécuté contre une baseline fixe simple ; ne justifier le graphe évolutif que s'il la bat à coût mesuré.
12. Traiter tout contenu parsé (dépôt, web, fichier) comme donnée non fiable, jamais comme instruction ; déclarer le palier de sandbox au manifeste.
13. Donner à chaque compétence un cycle de vie gouverné (candidate, active, dépréciée, retirée) ; l'accumulation illimitée est un mode d'échec documenté.
14. Marquer comme hypothèses Akasha — à benchmarker, pas comme acquis — le retrieval gaté par préconditions, l'ordre de force des sandbox et tout crédit à une dynamique GUI apprise sans ablation aléatoire.
15. Ne pas figer de moteur d'inférence. Le contrat est le placement des poids en SSD, RAM et VRAM ; un moteur propre est admissible si les backends candidats ne savent pas monter et démonter ainsi.
