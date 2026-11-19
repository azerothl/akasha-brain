# Akasha Brain — Spécification d’architecture

**Statut :** proposition de conception, v0.21\
**Date :** 2026-11-18\
**Portée :** architecture fonctionnelle et technique, sans framework ni fournisseur imposé

> **Révision v0.2 (2026-11-13) :** premier terrain arrêté (bureau & code local), compléments issus d'une recherche sourcée sur l'orchestration, les contrats, le routage local, la mémoire, les modèles du monde bureau et l'évaluation/sécurité. Voir §2.5, §6.1, §8.4, §9.7, §10.1, §11.6, §13.5, §19 révisé, les [notes de recherche](../research/research-notes.md) et le [plan de développement](../plans/development-plan.md). Les seuils chiffrés restent à mesurer en Phase 0/1 ; aucun chiffre de la littérature n'est repris comme seuil universel (§2.4).

> **Révision v0.3 (2026-11-13) :** comblement des lacunes identifiées par la revue de v0.2 — taxonomie des classes de risque (§13.6), conditions de réussite exécutables (§5.4), borne de clarification (§5.1), définition du coût en mono-poste (§15.1), environnement partagé, approbations et ordonnancement (§8.5), stockage des artefacts (§10.2), interface des compétences (§10.3), harness bureau Windows et protocole de mesure (§12.2), exceptions réseau (§13.7), compatibilité et dépréciation des versions (§16.1). Décisions ajoutées au §19 ; les seuils chiffrés restent produits par les mesures de Phase 0/1.

> **Révision v0.4 (2026-11-13, historique — remplacée en v0.8) :** aucun moteur d'inférence n'était retenu. Les poids étaient décrits en trois paliers et un moteur propre envisagé si les backends candidats ne satisfaisaient pas ce contrat. Le §6.2 et la décision 2 du §19 ont depuis été révisés en v0.8.

> **Révision v0.5 (2026-11-14) :** le bureau & code est confirmé comme banc d'essai du prototype, pas comme cible produit. Le routage nominal privilégie les petits modèles spécialisés, outils et solveurs ; un grand modèle généraliste ne peut servir que de secours ponctuel et explicitement configuré. Le modèle du monde spatial et l'action dans des environnements restent la cible de fond (§2.5, §8.4, §9.7, §17, §19).

> **Révision v0.6 (2026-11-14) :** la politique de données sépare le journal d'audit append-only, limité aux métadonnées minimales, des contenus et dérivés effaçables. L'entraînement partagé à partir de données utilisateur exige un accord explicite et une filiation permettant de reconstruire, désapprendre ou retirer un modèle concerné (§8.3, §8.5, §10, §13.3, §16.1, §19).

> **Révision v0.7 (2026-11-14) :** les appels d'inférence distante peuvent être autorisés par avance, mais seulement dans une politique explicite et bornée (fournisseur, usage, catégories de données, expiration et budget), avec journalisation de chaque appel. Le banc Windows désactive par défaut les canaux de partage et de réseau ; les téléchargements de dépendances sont séparés de leur installation hors ligne en sandbox (§8.4, §13.5-13.7, §19).

> **Révision v0.8 (2026-11-14) :** Rbitnet devient le moteur prioritaire pour les modèles GGUF compatibles ; d'autres moteurs restent accessibles par des adaptateurs spécialisés. Le gestionnaire de ressources coordonne le chargement, l'admission et le déchargement selon les capacités effectivement exposées : les transferts fins de poids sont optionnels et leur intérêt se mesure (§6.2, §8.5, §12.2, §19).

> **Révision v0.9 (2026-11-14) :** le MVP comprend les parcours code et bureau, trois rôles spécialisés préentraînés, une exécution CPU seule et une boucle d'évolution automatique bornée dès la Phase 1. Une interface desktop expose le graphe en consultation et le contrôle de l'évolution ; la fiabilité prime dans les décisions de promotion (§2.6, §11.7, §17, §19 et plan de développement).

> **Révision v0.10 (2026-11-14) :** le banc de référence retenu est une petite application de notes présentant un bug de sauvegarde. Les parcours code et bureau sont reliés par une vérification de persistance après fermeture et réouverture ; la variante de transfert reste réservée à une évaluation indépendante (§2.6 et plan de développement).

> **Révision v0.11 (2026-11-14) :** l'application de notes de référence sera créée pour le banc, avec un bug de sauvegarde volontaire et reproductible. Le dépôt initial, les tests et le vérificateur sont figés pour permettre une comparaison fiable des workflows (§2.6 et plan de développement).

> **Révision v0.12 (2026-11-14) :** la variante réservée à la mesure du transfert est une application de gestion de tâches présentant un autre bug. Son scénario précis et sa provenance sont à sélectionner en Phase 0 ; elle reste distincte des données utilisées pour optimiser les candidats (§2.6 et plan de développement).

> **Révision v0.13 (2026-11-14) :** les deux bugs et leurs vérifications sont définis : sauvegarde non persistée dans l'application de notes et filtre « À faire » incorrect dans l'application de tâches. Le protocole sépare les données d'optimisation de la variante de transfert (§12.3 et plan de développement).

> **Révision v0.14 (2026-11-14) :** l'évolution locale utilise par défaut le banc synthétique de référence et des résultats techniques minimisés. La réutilisation de contenus réels et de leurs dérivés exige un accord explicite, par projet et catégorie ; la variante de transfert et les secrets sont exclus (§8.3, §10.4, §11.1, §11.7, §19).

> **Révision v0.15 (2026-11-14) :** durées par défaut et sauvegarde locale chiffrée quotidienne définies ; accord séparé pour sauvegarder des contenus réels, effacement suivi jusqu'aux copies contrôlées et restauration empêchant leur réapparition (§10.2, §10.5, §19).

> **Révision v0.16 (2026-11-14) :** autorisations du MVP précisées : autonomie dans le banc jetable sous protections vérifiées, projet réel modifié seulement après validation de la proposition, tests isolés, approbation par téléchargement et bureau réel exclu (§6.1, §13.5-13.7, §19).

> **Révision v0.17 (2026-11-16)** — Le banc Tâches évalue une porte de décision facultative qui produit `ready`, `abstain` ou `blocked` en une passe. Le candidat épinglé est `akasha-model==0.3.0` (MIT, Path A déterministe sans torch), avec les décisions typées `Choice`, `Score` et `Noul`. Le routage déterministe est actif par défaut. L’autorisation hors modèle et les approbations humaines s’appliquent dans les deux configurations (§8.6, §17, §19).

> **Révision v0.18 (2026-11-17)** — Raccordement de la conversation au planificateur et au registre, récupération de capacités déclarées, contrat d’exécution image commun à Windows et Linux et accès MCP local. La qualification et l’export PNG sont vérifiés dans un bac headless. Les téléchargements du moteur et des poids demandent chacun un accord hors modèle (§6.3, §8.7, §11.8).

> **Révision v0.19 (2026-11-17)** — But produit figé. Agent local multi-spécialistes à domaines croissants avec abstention. Session portant des projets. Vault hybride (keystore OS pour les secrets, vault applicatif pour les handles). Cible produit = agent universel local. Piste spatiale séparée. Feuille de route post-MVP dans [product-goal-roadmap-v1.md](../plans/product-goal-roadmap-v1.md) (§2.1, §2.3, §2.4, §2.5, §17, §19).

> **Révision v0.20 (2026-11-18)** — Ajout du contrat des capacités vocales locales et de leur qualification sur le banc Windows. Les jalons G7 à G9 couvrent l’analyse d’enregistrements parlés, la lecture des réponses et les demandes vocales (§7.3.1, §17, §19).

> **Révision v0.21 (2026-11-18)** — Ajout des URL dans le contexte de conversation, d’une lecture HTTPS ponctuelle hors du bac et du contrat cible pour les connexions aux services tiers (§5.3, §8.8, §10.6, §13.7, §17).

## 1. Résumé

Akasha Brain est un système agentique composé de capacités spécialisées et hétérogènes. Une capacité peut être un petit modèle de langage, un modèle de vision ou d’audio, un modèle du monde, un outil déterministe, un moteur symbolique, une compétence procédurale, une mémoire ou un adaptateur d’environnement.

Le système représente ces capacités et leurs interactions sous la forme d’un **graphe évolutif**. Les nœuds portent les capacités; les liens décrivent les transformations de données et les relations de contrôle qui permettent de les composer. À partir des résultats, des observations et du feedback, le système apprend à choisir ou créer des chemins entre capacités. Lorsqu’une lacune récurrente est démontrée, il peut proposer un nouvel adaptateur, une compétence, un outil ou un spécialiste.

L’objectif est de faire croître les capacités par composition et apprentissage progressif, sans dépendre d’un modèle monolithique. Chaque exécution reste inspectable : le système conserve le plan, les nœuds et liens utilisés, leurs versions, les preuves disponibles, les erreurs et le résultat.

L’évolution de la structure compte autant que celle des modèles. Le système doit pouvoir sélectionner un chemin connu, composer les capacités autrement, apprendre une liaison réutilisable, détecter une lacune, évaluer une solution candidate et revenir à une version antérieure si elle régresse.

Une erreur ne signifie pas automatiquement qu’il manque un modèle. Elle peut venir d’une capacité insuffisante, d’un mauvais routage, d’un format incompatible, d’un plan inadéquat, de données manquantes ou d’une observation ambiguë.

## 2. Vision, objectifs et limites

### 2.1 Vision

Akasha Brain est un agent local multi-spécialistes. Il reçoit une demande dans une session, la décompose, l’oriente vers des capacités déclarées et vérifie le résultat dans l’environnement. Il élargit ses domaines par composition et apprentissage mesuré. Lorsqu’une capacité manque, il cherche une voie de reprise autorisée, suspend la tâche si un accord est nécessaire ou rend une issue motivée selon le §11.8.

L’analogie du cerveau décrit l’architecture. Des parties spécialisées sont reliées par des voies qui apprennent à fonctionner ensemble. Ce n’est pas une prétention à reproduire la biologie ni à garantir une intelligence générale.

Une nouvelle capacité peut être un solveur, un contrôleur, une représentation spatiale, un adaptateur, une mémoire procédurale ou une conversion de format, pas nécessairement un réseau neuronal. Une nouvelle liaison peut rendre utilisable une compétence déjà présente.

L’unité d’interaction est la **session**. Une session porte zéro ou plusieurs projets et a une mémoire de session distincte de la mémoire globale. Dès G1, les écritures de session excluent les secrets selon le §10.6. G2 ajoute un **vault hybride**. Le keystore OS détient les secrets et la mémoire opérationnelle les référence par des handles dont le vault applicatif conserve les métadonnées. Hors charge interactive, le système peut simuler des cas synthétiques admissibles sous budget, sans retarder une tâche utilisateur.

### 2.2 Principes

- Composer les capacités existantes avant d’entraîner prématurément un nouveau modèle.
- Choisir le bon type de calcul; un LLM n’est pas le choix par défaut pour un calcul exact.
- Décrire chaque capacité par des entrées, sorties, préconditions, limites et permissions explicites.
- Apprendre à partir de résultats observés; séparer les prévisions générées des faits confirmés dans l’environnement.
- Mesurer chaque évolution par rapport à une référence.
- Versionner et rendre réversibles les changements.
- Conserver la provenance des données, des modèles, des compétences et des décisions.
- Représenter l’incertitude au lieu de forcer une réponse.
- Garder les permissions indépendantes des instructions en langage naturel.
- Évaluer les évolutions dans un espace candidat avant de modifier la version active.

### 2.3 Objectifs

Le système doit :

- comprendre une demande et en préserver l’intention, les contraintes et la définition de réussite;
- isoler le travail dans une session qui peut porter des projets;
- décomposer un objectif en sous-tâches composables;
- router ces sous-tâches vers des capacités adéquates;
- exécuter des workflows séquentiels, conditionnels, parallèles et itératifs bornés;
- relier texte, code, vision, audio, image, calcul, mémoire et actions;
- observer un environnement, prédire l’effet d’actions candidates et vérifier leurs effets;
- s’abstenir ou signaler une capacité manquante plutôt que forcer une réponse;
- réutiliser des workflows et compétences validés;
- détecter les lacunes récurrentes et proposer des changements sous garde-fous;
- évaluer, versionner, surveiller et annuler les évolutions;
- conserver le contexte de session et une mémoire globale sous rétention;
- sceller les secrets dans le vault hybride et n’exposer que des handles en mémoire opérationnelle;
- simuler hors charge des cas synthétiques admissibles sans préempter une tâche interactive;
- prendre en compte latence, coût, ressources, risque et confidentialité.

### 2.4 Hors périmètre de la première version

- Entraîner tous les modèles à partir de zéro.
- Garantir une intelligence générale, une couverture de toute demande, ou une auto-amélioration illimitée.
- Exiger que chaque capacité soit un réseau neuronal.
- Laisser un nœud de travail modifier directement le graphe actif, les permissions ou le code de production.
- Improviser une capacité ou une permission hors registre et hors classes de risque.
- Supposer qu’un seul modèle du monde couvre tous les environnements et toutes les échelles.
- Définir des seuils universels de réussite ou de latence sans premier cas d’usage.
- Décider maintenant entre hébergement local, cloud ou hybride pour les terrains ultérieurs (le banc d'essai initial est défini au §2.5 ; les autres restent ouverts).
- Livrer la piste spatiale incarnée dans le même calendrier que l’agent universel local (§17).

### 2.5 Décision v0.5 — banc d'essai initial (révisée v0.19)

Le premier terrain implémenté est le **bureau & code local** (poste Windows d'abord), exécuté en environnement isolé, comme banc d'essai pour valider les contrats, la composition du graphe, les actions et l'évaluation reproductible. Il ne constitue pas la cible produit finale.

La **cible produit** est un agent universel local à domaines croissants, avec abstention honnête hors couverture. La perception spatiale et l’action incarnée forment une **piste de recherche séparée**, sans calendrier partagé avec les livraisons produit post-MVP (§17). Le bureau & code sert à éprouver les fondations avec des résultats vérifiables : tests du dépôt, état final des fichiers et des applications, rollback par git ou snapshot. Les décisions détaillées figurent au §19. En résumé :

- hébergement mono-poste local par défaut, modèles locaux ou distants selon le manifeste ;
- Rbitnet prioritaire pour les modèles GGUF compatibles ; d'autres moteurs sont accessibles par adaptateur et le gestionnaire de ressources coordonne leur mémoire (§6.2) ;
- graphe versionné et workflow contrôlé dès la Phase 1 ; évolution bornée sur une copie candidate dans le banc d'essai avant toute extension plus autonome (§11.7) ;
- approbation humaine interruptible sur les actions destructives ou irréversibles hors exception strictement bornée au bac jetable vérifié (§13.6) ;
- évaluation par exécution (jamais par un juge LLM seul) contre une baseline fixe et simple ;
- route nominale composée de capacités spécialisées, d'outils et de solveurs ; grand modèle généraliste réservé à un secours exceptionnel (§8.4).

### 2.6 Périmètre du MVP — décisions v0.13

Le MVP est une application desktop Windows d'abord, exécutant deux parcours dans un banc isolé. La référence est une **petite application de notes créée pour le banc**, accompagnée de son dépôt et préparée avec un bug de sauvegarde volontaire et reproductible : la note s'affiche et la sauvegarde est annoncée, mais aucune modification n'est persistée. Le comportement attendu est qu'une note sauvegardée persiste après fermeture et réouverture. Le langage, la technologie d'interface, le stockage et le détail de l'implémentation fautive restent à choisir en Phase 0 (§12.3).

Le banc fournit une version initiale figée et restaurable, une demande décrivant le symptôme, un test de régression qui échoue sur cette version et des tests de non-régression. Chaque essai repart du même état initial ; les tests et vérificateurs de référence restent protégés contre les modifications du candidat. Le parcours code reproduit l'échec, corrige le dépôt et rejoue ces contrôles ; le parcours bureau ouvre l'application corrigée, crée une note, la sauvegarde, puis vérifie qu'elle persiste après fermeture et réouverture. L'OCR fournit une observation utile du bureau, complétée par un contrôle indépendant de l'état réellement sauvegardé. Les résultats distinguent échec initial, modification proposée et vérification finale.

Une **application de gestion de tâches dont le filtre « À faire » affiche aussi les tâches terminées** constitue la variante distincte réservée à la mesure du transfert. Sa provenance, ses technologies et le détail de l'implémentation fautive sont à choisir en Phase 0 ; son état initial et ses vérificateurs doivent être reproductibles. Les jeux d'optimisation et de validation des candidats sont distincts de cette variante ; celle-ci ne sert pas à choisir ou ajuster les candidats à répétition. Tests, vérificateurs et état initial sont versionnés et protégés des candidats (§11.7, §12.3).

Trois rôles utilisent de petits modèles préentraînés : communication texte, code et vision/OCR. Rbitnet est prioritaire pour les GGUF compatibles ; un second moteur local réel sert le modèle de vision/OCR. L'OCR est une observation imparfaite : la réussite d'une tâche repose sur des vérificateurs adaptés à l'état réel, notamment tests, fichiers ou état applicatif. La création ou l'entraînement automatique de nouveaux modèles n'est pas requis pour cette première boucle.

Le fonctionnement complet est exigé en CPU seul. Les mêmes scénarios sont ensuite évalués sur la machine de référence avec la NVIDIA RTX 4080 SUPER de 16 Go, pour les moteurs et modèles compatibles ; les opérations qui restent sur CPU sont identifiées. Les besoins minimaux exacts de CPU, RAM et stockage et les seuils de performance découlent des mesures, sans promettre la prise en charge de toute machine sans GPU.

L'interface permet de formuler une demande, suivre la tâche, consulter ses résultats et la trace, et visualiser le graphe de capacités et de connexions. La vue est consultable de façon interactive : zoom, déplacement, inspection des nœuds et liens, chemins utilisés, versions candidates et actives, historique et ressources observables. Elle donne accès à la pause/reprise de l'évolution et au retour à une version précédente ; l'édition manuelle des connexions n'est pas incluse dans le MVP.

Après chaque tâche utilisateur éligible, qu'elle réussisse ou échoue, l'évolution bornée démarre en arrière-plan sans attendre l'inactivité de la machine, sous limites configurables et permissions inchangées. Elle explore de nouvelles combinaisons des capacités et outils existants, les évalue sur un graphe candidat isolé et peut activer automatiquement une version satisfaisant les critères, dans le seul banc d'essai (§11.7). Les essais internes ne déclenchent pas eux-mêmes de nouveaux essais. La fiabilité est prioritaire ; à fiabilité démontrée comparable, le temps et les ressources départagent les candidats.

## 3. Modèle du graphe de capacités

Le graphe actif G contient des nœuds versionnés, des liens versionnés, des règles d’exécution et des politiques. Un graphe candidat est une copie isolée utilisée pour essayer des évolutions.

- **Nœud :** capacité exécutable ou informationnelle.
- **Lien de données :** transporte ou transforme un artefact d’une sortie vers une entrée.
- **Lien de contrôle :** exprime dépendance, branche, condition ou boucle.
- **Workflow :** sous-graphe assemblé pour une tâche ou une famille de tâches.
- **Compétence :** procédure validée et réutilisable, représentée comme un workflow ou un programme.
- **Capacité manquante :** transformation nécessaire sans chemin acceptable après vérification des erreurs de routage et de contrat.

Un workflow est un graphe dirigé. Toute boucle possède une limite d’itérations, une échéance ou un budget. Les cycles implicites sont interdits.

### 3.1 Types de nœuds

Le graphe peut contenir :

1. modèles génératifs : dialogue, code, image, audio, résumé;
2. modèles discriminatifs : détection, classification, estimation de pose, scoring;
3. modèles prédictifs : dynamique temporelle, modèle du monde, séries temporelles;
4. moteurs symboliques et numériques : algèbre, calcul exact, géométrie, contraintes, optimisation;
5. outils et services : interpréteur isolé, recherche, bases, API ou système de fichiers limité;
6. compétences : programmes et workflows validés;
7. mémoires et index;
8. adaptateurs : interface de bureau, simulateur, jeu, robot, capteurs ou contrôleurs;
9. vérificateurs : assertions, tests, solveurs, contrôles de politique;
10. étapes humaines : clarification, annotation, correction ou approbation.

### 3.2 Contrat d’un lien

Chaque lien déclare source et cible, champs de sortie et d’entrée, schéma versionné, conversions, préconditions, postconditions, permissions, gestion d’erreur, mesures et preuves d’activation. Une liaison n’est pas utile du seul fait qu’elle existe ou qu’elle est fréquemment appelée; sa contribution est évaluée sur des tâches représentatives et comparée à une référence.

## 4. Architecture logique

~~~mermaid
flowchart TD
    U[Utilisateur] --> C[Modèle de communication]
    C --> G[Compilateur d'objectif]
    G --> P[Planificateur]
    P --> R[Runtime et routeur]
    R --> REG[Registre de capacités]
    REG --> N[Modèles, outils, solveurs, compétences]
    N --> V[Vérification et assemblage]
    V --> C

    ENV[Environnement et capteurs] --> PER[Perception et état spatial]
    PER --> WM[Modèle du monde conditionné par l'action]
    WM --> P
    P --> ACT[Adaptateur d'action]
    ACT --> ENV
    ENV --> V

    V --> LOG[Trace et mémoire d'expérience]
    LOG --> E[Évolution manager]
    E --> CG[Graphe candidat isolé]
    CG --> BENCH[Replay, évaluation et contrôles]
    BENCH -->|promotion versionnée| REG
~~~

### 4.1 Plan de données et plan de contrôle

Le **plan de données** transporte texte, images, vidéos, audio, code, valeurs numériques, états de scène, plans, actions et résultats.

Le **plan de contrôle** choisit un workflow, vérifie permissions, budgets et préconditions, détermine les branches et arrête les boucles.

Les modèles de travail ne contrôlent pas le registre actif. Le runtime vérifie contrat et permissions à chaque appel. L’évolution manager prépare les modifications dans un graphe candidat.

### 4.2 Composants

1. **Modèle de communication** — comprend la demande, pose les questions nécessaires et présente le résultat.
2. **Compilateur d’objectif** — convertit la demande en GoalSpec.
3. **Planificateur** — compose ou récupère un workflow.
4. **Registre** — décrit les nœuds, contrats, versions, ressources et évaluations.
5. **Routeur** — filtre et ordonne les capacités admissibles.
6. **Runtime** — exécute dépendances, branches, reprises, échéances et budgets, et demande au gestionnaire de ressources l'admission et la préparation d'un nœud modèle avant son appel (§6.2).
7. **Bus d’artefacts** — transmet les données intermédiaires et leur provenance.
8. **Mémoire** — gère épisodes, connaissances, compétences et résultats.
9. **Vérificateur** — contrôle contrats et réussite réelle.
10. **Système spatial** — maintient l’état, prédit et planifie les actions.
11. **Évolution manager** — formule des hypothèses et évalue des graphes candidats.
12. **Gouvernance** — applique risques, permissions et confidentialité.
13. **Observabilité** — conserve traces, métriques et versions.

## 5. Conversation, objectifs et planification

### 5.1 Modèle de communication

Le modèle de communication est spécialisé dans l’échange utilisateur : compréhension, extraction des contraintes, reformulation, clarification et compte rendu. Il ne porte pas seul les compétences détaillées en code, espace, finance ou audio. Il remet des objectifs structurés aux autres composants.

Le dialogue de clarification est borné : au plus N tours par objectif (défaut 2, politique versionnée), questions groupées en un message par tour, et seulement si la réponse peut changer le plan. Au-delà de la borne, l'objectif est sous-spécifié : soit il se poursuit avec des hypothèses explicites (`uncertainties`) et une classe de risque plafonnée à R1 (§13.6), soit il se termine par l'erreur typée `needs_clarification` (famille incertitude, §14). Aucune action R2 ou R3 n'est exécutée sur des préconditions ambiguës.

### 5.2 GoalSpec

Un objectif inclut l’intention, les entrées, les contraintes, les critères de réussite, la classe de risque, les budgets, les incertitudes et les approbations requises.

~~~json
{
  "goal_id": "uuid",
  "user_intent": "Déplacer l'objet désigné vers la zone cible",
  "inputs": ["scene://current"],
  "constraints": {
    "allowed_actions": ["observe", "move", "grasp", "release"],
    "environment_id": "environment-name"
  },
  "success_conditions": [
    {"predicate": "object_in_zone", "on": "SpatialState", "args": {"object": "target_object", "zone": "target_zone"}}
  ],
  "risk_class": "R3",
  "resource_budget": {},
  "uncertainties": [],
  "approval_requirements": []
}
~~~

La demande originale reste liée à sa représentation structurée. Les noms de champs sont illustratifs et le schéma devra être versionné. La classe de risque suit la taxonomie du §13.6 ; l'exemple (action physique irréversible) vaut R3. Les conditions de réussite suivent la forme du §5.4.

### 5.3 Planificateur

Le planificateur récupère les capacités admissibles, décompose la tâche, vérifie que les entrées peuvent être produites, ajoute des contrôles aux frontières critiques, borne les appels et choisit un chemin. Il demande clarification ou autorisation si une précondition importante manque.

Une URL explicite est une cible web distincte des chemins locaux. Dans la conversation desktop, une demande de lecture portant sur une URL autonome passe par le parcours web sans projet sélectionné. Une relance qui désigne le lien, la page ou la chaîne peut reprendre la cible précédente de la même session. Si plusieurs liens sont plausibles, le bureau demande d’en indiquer un. L’autorisation de la lecture porte sur la cible exacte (§13.7).

Le planificateur peut combiner petit modèle, règles, recherche dans le graphe et moteur de workflow. L’architecture n’impose pas un grand LLM central.

### 5.4 Conditions de réussite exécutables (v0.3)

Une condition de réussite est un prédicat typé évalué sur l’état vérifié par l’adaptateur (§9.7), jamais sur la sortie d’un modèle. La forme :

~~~json
{
  "success_conditions": [
    {"all_of": [
      {"predicate": "test_suite_passes", "on": "CodeState", "args": {"suite": "unit"}},
      {"predicate": "file_matches_regex", "on": "CodeState", "args": {"path": "src/x.py", "pattern": "^def compute"}}
    ]}
  ]
}
~~~

Règles :

- **Ensemble fermé de prédicats par adaptateur**, énuméré dans le schéma : côté code, par exemple `file_exists`, `file_matches_regex`, `git_diff_applies`, `test_suite_passes`, `process_exit_zero` ; côté bureau, `window_foreground`, `ui_element_state`, `file_hash_equals`, `registry_key_equals`, `process_running`. Un nouveau prédicat = une nouvelle version de schéma.
- **Composition bornée :** `all_of` / `any_of`, profondeur maximale 2.
- Une condition non exprimable dans l’ensemble fermé passe par un **nœud vérificateur personnalisé** (capacité testée et versionnée) ou par le prédicat `human_confirms` — jamais par un jugement libre de LLM (§12).
- Évaluation post-exécution sur l’état observé ; échec = erreur typée (§14) ; le compte rendu distingue planifié, exécuté et confirmé (§8.3).

## 6. Contrats et registre de capacités

Chaque capacité publie un manifeste comprenant :

~~~yaml
capability_id: perception.object_pose
version: 1.0.0
kind: model
description: Estime les objets visibles, leur pose et l'incertitude.
input_schema: SceneObservation/v1
output_schema: ObjectPoseSet/v1
preconditions:
  - observation_contains_calibrated_camera
postconditions:
  - each_pose_has_coordinate_frame
uncertainty:
  output_field: confidence
permissions:
  reads: [current_observation]
  writes: []
side_effects: none
resource_profile:
  device: configurable
evaluation_profile: object-pose-benchmark/v1
provenance:
  model_id: registry-id
  weights_digest: digest
  license: recorded-license
~~~

Le registre distingue capacité annoncée et capacité évaluée. Une description en langage naturel aide la recherche; le contrat structuré gouverne l’exécution.

Chaque artefact important inclut type et version de schéma, référence de contenu, date ou frame, producteur et version, provenance des entrées, incertitude, limites de confidentialité et statut : proposition, observation, résultat vérifié ou correction. Une sortie inférée reste distincte d’un fait observé.

Les contrats précisent unités, repères de coordonnées, échantillonnage, langue et conversions. Le runtime valide l’entrée avant appel et la sortie avant transmission. Toute erreur reçoit un type stable : contrat, capacité, permission, ressource, environnement, délai ou incertitude.

### 6.1 Précisions v0.2 — schémas, protocoles, profils

- **Schéma canonique :** JSON Schema 2020-12, avec `$id`/`$schema` versionnés en SemVer exacte (aucune plage `^`/`~`/`>=`). JSON Schema valide la structure ; les unités, repères et pré/postconditions métier restent validés par le runtime.
- **Noyau d'outil :** le manifeste reprend le noyau MCP `Tool {inputSchema, outputSchema, annotations}` pour les capacités-outils. Les quatre hints MCP (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) sont des indications d'interface, **non autoritatives** : les permissions normatives Akasha (`reads`, `writes`, `execute`, `network`) sont séparées et vérifiées par le runtime hors modèle. `destructiveHint=true` impose une approbation dans le GoalSpec, sauf pour une action dont le confinement dans le bac jetable et les autres conditions de l'exception R1 sont vérifiés indépendamment du modèle (§13.6).
- **Protocoles :** MCP est le contrat par défaut intra-système (Phase 0-1). A2A est différé à la bordure externe (délégation à un agent autonome), via adaptateur, sans second registre interne. OpenAPI 3.1 ne sert qu'à importer des capacités HTTP distantes. Le chargement des poids et l'API propre au moteur ne sont **pas** le contrat d'outil MCP/JSON Schema : le gestionnaire de ressources les coordonne via l'adaptateur (§6.2).
- **Provenance :** aligner l'`ArtifactEnvelope` sur le vocabulaire PROV (artefact = Entity, exécution = Activity, capacité/utilisateur = Agent) et le patron SLSA/in-toto (digest SHA-256 du contenu, predicate typé versionné, identité du producteur). Le `weights_digest` devient un digest vérifiable, signé à la promotion.
- **`resource_profile` enrichi :** `quantization`, `context_tokens`, `max_concurrent`, `draft_id` le cas échéant, identifiant/version de moteur, format et architecture du modèle, périphériques pris en charge, ainsi que stockage, RAM et VRAM prévus en distinguant poids, cache de contexte et mémoire temporaire. Chaque mesure indique sa source, son horodatage et son statut mesuré, estimé ou inconnu. `pin` est une politique de non-éviction sous réserve des budgets ; le placement hybride n'est proposé que si le backend le prend en charge (§6.2). Toute quantization est liée à son `evaluation_profile` (perplexité/KLD et tâche) ; jamais de quantization déclarée sans évaluation.
- **`uncertainty` enrichi :** méthode de calibration, jeu de calibration, scores ECE/Brier et date de recalibration. Un simple champ `confidence` ne suffit pas.

### 6.2 Décision v0.8 — moteurs et gestion des ressources

**Choix des moteurs.** [Rbitnet](https://github.com/azerothl/Rbitnet) est le moteur prioritaire pour un modèle GGUF dont l'architecture, la quantization, le tokenizer et le backend matériel sont pris en charge et validés pour l'usage considéré. Le registre distingue support annoncé et support effectivement évalué. Pour une architecture ou un format non pris en charge, ou pour une autre famille de modèles (vision, STT, TTS, génération audio/image, modèle du monde), le système peut utiliser un autre moteur local derrière un adaptateur déclaré. Un outil déterministe n'exige aucun moteur de modèles. L'adaptateur et le manifeste restent indépendants du protocole propre au moteur.

**État observé de Rbitnet à vérifier en Phase 0.** La copie examinée au commit `6a7139f` documente l'API HTTP de chargement/déchargement, une API Rust embarquée minimale, des poids GGUF mappés selon les architectures, un placement hybride CPU/GPU et un proxy multi-modèles utilisant un processus enfant par modèle. Son `ModelManager` est une structure préparatoire de profils et d'état ; sa présence ne prouve pas à elle seule un déchargement physique automatique ni une migration dynamique des poids. La couverture exacte dépend des architectures, versions et backends ; les mesures Akasha doivent épingler et vérifier la version réellement utilisée. La vision LLaVA existe sur un périmètre limité ; ne pas en déduire un support général des autres modalités. Sources : dépôt Rbitnet, `docs/ENGINE_API.md`, `docs/USAGE.md`, `docs/LIMITATIONS.md` et `crates/bitnet-core/src/model_manager.rs`.

**Frontière des responsabilités.** Akasha Brain maintient le registre, choisit les capacités, applique permissions et budgets globaux, et arbitre les accès concurrents. Son gestionnaire de ressources, également appelé gestionnaire de résidence dans les sections historiques, coordonne les adaptateurs. Chaque adaptateur de moteur traduit ce contrat vers son API et annonce ses opérations réellement disponibles. Le moteur charge et exécute ses modèles et rend compte des ressources qu'il peut observer. Rbitnet peut être utilisé par HTTP/proxy ou par son API Rust embarquée ; le choix dépend des mesures de Phase 0/1. Les autres moteurs peuvent être des bibliothèques ou des processus isolés et ne sont pas tenus d'implémenter les mécanismes internes de Rbitnet.

**Contrat minimal d'un adaptateur.** Déclarer `describe` (version, formats, architectures, modalités, périphériques et fonctions disponibles), `prepare` (vérifier l'identité et préparer/charger un modèle), `invoke` (entrées/sorties typées), `release` (fin d'utilisation), `unload` (déchargement sûr) et `status` (état, ressources, provenance des mesures et erreurs). Ces noms décrivent la sémantique de l'interface Akasha ; ils ne prétendent pas être des endpoints existants. `prepare` peut démarrer un processus contrôlé ou utiliser un moteur existant. Les états au minimum sont disponible, chargement, prêt, en cours d'utilisation, déchargement et échec. Annulation, délai dépassé ou échec de chargement libèrent les réservations associées et laissent un état observable ; une requête active ne doit pas perdre son modèle. Un backend qui ne peut pas décharger finement peut arrêter proprement son processus dédié uniquement après la fin des appels actifs.

**Sélection et échecs.** Le registre vérifie le format, l'architecture, la version, les entrées/sorties et les ressources avant de choisir l'adaptateur. Un GGUF compatible est d'abord proposé à Rbitnet ; si une combinaison n'est pas prise en charge ou ne satisfait pas les critères mesurés, un autre moteur déclaré et autorisé peut être sélectionné avec motif tracé. Si aucun ne convient, retourner une erreur typée de capacité non disponible ; un manque de budget retourne `residency_unavailable`. Aucun changement silencieux vers un grand modèle généraliste ou un service distant : le secours exceptionnel du §8.4 et le `RemoteInferenceGrant` du §13.7 restent obligatoires.

**Mémoire et admission.** Le stockage conserve les artefacts identifiés par digest ; leur éviction de la mémoire ne supprime pas les fichiers. Le mappage d'un fichier ne garantit pas que toutes ses pages résident en RAM. Les poids peuvent rester en RAM pour calcul CPU, en VRAM, ou être répartis entre les deux ; ces placements ne constituent pas une séquence obligatoire de trois étapes. Avant de charger ou d'exécuter, l'ordonnanceur tient compte des modèles déjà actifs, poids, caches de contexte/KV, activations, espaces temporaires, charge des processus et du pilote, et d'une marge réservée au système et aux autres applications. Il réconcilie budgets prévus avec mesures disponibles, distingue chiffres mesurés, estimés et inconnus, évite le double comptage des pages mappées partagées et ne traite jamais une mesure indisponible comme zéro. CPU seul est un mode valide, sans budget VRAM imposé. Si les limites ne peuvent pas être respectées ou estimées de façon suffisamment sûre, attendre, refuser ou choisir un placement CPU déclaré compatible ; ne pas provoquer de dépassement volontaire.

Les appels actifs détiennent une référence sur leur modèle et leurs ressources. Aux points sûrs, le gestionnaire peut libérer les modèles inactifs les moins récemment utilisés, selon les capacités du backend et les priorités ; `pin` ne permet pas de dépasser le budget. Le chargement, la disponibilité, les attentes, les déchargements, les erreurs, la durée et les ressources observables sont tracés, sans contenu utilisateur par défaut. La sélection, le blocage et la libération doivent rester corrects lors d'appels simultanés et d'un échec ou redémarrage de moteur. Les coûts et la mémoire des autres moteurs sont intégrés au même budget global ; pour un moteur distant, compter les ressources locales du client, puis le coût et les limites distants selon le grant applicable.

**Fonctions avancées optionnelles.** Chargement partiel, placement hybride, maintien au chaud, transfert ou rétrogradation RAM/VRAM sans redémarrage et métriques détaillées ne sont exigés que si le backend les annonce et si leur utilité est démontrée. Les évaluer par scénario avant de modifier Rbitnet ; un moteur neuf n'est pas un prérequis. Les contraintes de compatibilité, la mesure par périphérique et la couverture des autres modalités restent des travaux de Phase 0/1.

### 6.3 Exécution image commune à Windows et Linux

L’implémentation de `image.generate` utilise stable-diffusion.cpp CPU `master-955-b7a74e6` et les poids SD-Turbo Q4_0 épinglés. La découverte, les accords par artefact, la qualification et la validation du PNG sont communs aux deux OS. Le protocole `ImageBackend` expose `identity`, `execute` et `verifies`. Le backend fournit une preuve de confinement et les octets exportés au contrôleur commun.

Windows utilise Windows Sandbox sans client graphique, avec un montage en lecture seule et les canaux réseau, presse-papiers, audio, vidéo, imprimantes et vGPU désactivés. Le contrôleur associe l’instance Sandbox au système de calcul HCS et récupère le PNG par `hcsdiag.exe`. Linux utilise Bubblewrap sous un compte non privilégié, avec espaces de noms privés, réseau isolé, entrées en lecture seule et espace de travail temporaire privé. La qualification Linux publiée a été réalisée sous Ubuntu WSL2.

L’admission réserve 8 192 Mio pour l’inférence CPU. Le contrôleur vérifie le confinement, la fin du bac et une sortie PNG bornée à 2 Mio. La validation commune contrôle le décodage, les dimensions 512 × 512 et le caractère non uniforme de l’image, puis normalise en RGB et retire les métadonnées. La preuve comporte la taille et le SHA-256 du PNG normalisé, ainsi que l’empreinte du flux reçu.

Le cache est associé à `capability-recovery.sqlite`. Une qualification synthétique est réutilisée tant que l’identité du candidat et sa preuve correspondent. Une nouvelle qualification est suivie de l’exécution de la demande dans un bac neuf. Les archives Windows et Linux ont leurs propres tailles et empreintes, et les poids sont communs. La source, la licence et les SHA-256 sont épinglés dans le catalogue d’artefacts. Chaque téléchargement R3 recueille un accord spécifique avant la requête et produit un reçu à usage unique. [Parcours CLI](../../README.md#générer-une-image-sans-fenêtre-en-cli) · [Preuves MCP](../../bench/results/image-mcp-headless-v1.json)

## 7. Familles spécialisées possibles

Le registre peut grandir progressivement; toutes ces familles ne sont pas requises dans le premier prototype.

Le [registre G5](../../akasha_brain/specialists.json) déclare les capacités, la modalité, le moteur, le contrat et le budget de mémoire modèle de chaque spécialiste. Une sélection exige la capacité, la modalité et le contrat attendus. Les adaptateurs image et OCR vérifient aussi le moteur et la réservation avant l’exécution et inscrivent le choix dans la preuve. Le solveur fixe de Notes déclare PowerShell, le contrat de copie vérifiée et une réservation modèle de 0 Mio. Un rôle de secours doit être déclaré et autorisé pour la décision en cours. Le registre livré déclare uniquement des spécialistes principaux.

### 7.1 Langage et code

Le spécialiste du langage extrait et exprime les objectifs. Les spécialistes de code peuvent lire un dépôt, naviguer, diagnostiquer, proposer une modification, l’exécuter dans un bac à sable et vérifier un diff.

Un corpus de code brut apprend les motifs de code. La compréhension d’une demande en langage naturel requiert aussi un GoalSpec ou des exemples reliant consigne, contexte et code. L’exécution du code reste une capacité séparée du modèle qui le propose.

### 7.2 Vision et spatial

Détection, segmentation, suivi, profondeur, pose, reconstruction, cartes, coordonnées, relations, visibilité, affordances et anticipation du mouvement peuvent être des nœuds distincts. Une représentation latente n’est pas automatiquement une carte métrique. Les tâches géométriques vérifiables requièrent des artefacts explicites avec repère, unité et confiance.

### 7.3 Image, audio et parole

La génération d’image, d’audio ou de vidéo, le STT, le TTS, l’alignement et l’identification de locuteur peuvent être composés selon la demande. Leurs manifestes indiquent licence, mémoire, latence, langue, qualité et conservation des entrées.

#### 7.3.1 Transcription et synthèse vocale locales

Le registre expose deux capacités optionnelles derrière les adaptateurs du §6.2. Les contrats restent communs aux moteurs et leur activation dépend des preuves de qualification du profil utilisé.

| Capacité | Entrée | Résultat attendu |
| --- | --- | --- |
| `audio.transcribe` (STT / ASR) | Référence à un WAV ou FLAC dans un projet autorisé, ou à la capture temporaire de la session active pour une demande vocale | Texte UTF-8 et segments contenant le texte et les bornes de début et de fin en millisecondes. Les segments sont ordonnés et bornés par la durée du média. Le profil peut fournir la langue détectée et distinguer les locuteurs s’il a été qualifié pour ces fonctions. |
| `audio.synthesize` (TTS) | Texte destiné à l’utilisateur, langue et voix autorisée par le profil | Le bureau lit les blocs PCM mono 16 bits à 24 kHz de Vivian au fil de la synthèse (`fr-pcm-stream.v1`). Le profil de repli Piper fournit un WAV validé (`fr-wav.v1`). |

Le STT sert à deux parcours selon l’intention exprimée par l’utilisateur.

- **Analyser un enregistrement parlé.** Depuis le bureau Windows ou MCP, `audio.transcribe` fournit les segments à une capacité déclarée de résumé, d’extraction de décisions et d’actions ou de recherche d’un passage. Le résultat peut renvoyer à l’horodatage de l’extrait qui l’étaye. Les propos transcrits restent des données de l’enregistrement, même s’ils contiennent des consignes. L’analyse de musique ou d’événements sonores relève de capacités audio distinctes.
- **Formuler une demande à la voix.** Dans le bureau, l’utilisateur choisit de dicter au micro ou d’utiliser un fichier WAV ou FLAC autorisé comme demande vocale. La transcription remplit un brouillon modifiable. Après envoi explicite, le texte rejoint le même parcours de planification et d’autorisations qu’une demande écrite (§5, §13). L’origine de la demande est déterminée par cette interaction, indépendamment du contenu de la transcription.

Le moteur est chargé à la demande sous les budgets et priorités partagés (§6.2 et §8.5). Chaque artefact est identifié par sa source, sa version, sa licence et son empreinte. Chaque téléchargement requis suit l’accord par artefact et la reprise vérifiée du §11.8. L’inférence s’exécute hors ligne sur des entrées préparées et des sorties bornées. La capture et la lecture relèvent de l’application hôte. Le moteur isolé reçoit uniquement le fichier ou le texte de la demande, conformément au profil du §13.5. Les copies de travail et les résultats sont temporaires par défaut et traités selon les règles d’admission en session ou les droits d’export. Les traces conservent les mesures techniques selon les règles des §8.3, §10.6 et §13.3.

La qualification initiale se fait en CPU sur le banc Windows. En ASR, les candidats reçoivent les mêmes extraits français de référence avec noms propres, vocabulaire technique, bruit et silence. Le rapport mesure le taux d’erreur de mots, les erreurs sur les noms, la validité des horodatages, les faux textes sur le silence, le chargement à froid, le temps de traitement rapporté à la durée audio et le pic RAM. En TTS, le banc vérifie l’intelligibilité en français, notamment les acronymes et les nombres, le délai jusqu’à la lecture et le pic RAM. Les limites d’entrée, de sortie et de temps sont déclarées par profil à partir des mesures. Les rejeux couvrent également les entrées invalides, l’annulation, la restitution du résultat et la libération des ressources. Les seuils de promotion sont fixés sur le banc avant le rejeu réservé (§11.6, §12).

### 7.4 Domaines et calcul

Arithmétique, algèbre, géométrie, finance et optimisation peuvent combiner modèles, solveurs, bibliothèques et bases de données datées. Un calcul exact ou un moteur de contraintes peut être plus fiable qu’un modèle génératif; un LLM peut interpréter la demande et expliquer le résultat contrôlé.

## 8. Routage et exécution de workflows

### 8.1 Admissibilité

Une capacité est admissible si son contrat peut être satisfait, ses préconditions sont vraies, ses permissions sont suffisantes, sa version est autorisée et ses ressources conviennent. Le score peut combiner adéquation, réussite historique, incertitude calibrée, coût, latence et risque. Les seuils sont établis sur des évaluations, pas inventés en cours de tâche.

### 8.2 Composition

Un workflow peut inclure séquences, branches, appels parallèles indépendants, vérifications, contre-expertises, reprises bornées, clarification, approbation, action et observation. Les effets de bord et dépendances interdisent un parallélisme dangereux.

### 8.3 Trace

Pour une tâche importante, la trace d'exécution décrit objectif, graphe et versions, étapes considérées, nœuds/liens exécutés, provenance, vérifications, incertitude, latence, ressources — dont les transitions de résidence (§6.2) —, coût et raison d’un arrêt. Elle est distincte du journal d'audit (§10.2) ; l'accès aux contenus nécessaires à la tâche ou leur présence éventuelle dans une trace n'autorise pas leur réutilisation pour l'évolution. Par défaut, seul l'enregistrement technique minimisé défini au §10.4 est admissible à cette réutilisation. Les champs contenant des données utilisateur ou permettant de les retrouver suivent les règles d'effacement et peuvent rendre le replay indisponible. Le compte rendu distingue action planifiée, action exécutée et réussite confirmée.

### 8.4 Décision v0.5 — modes de routage, runtime, traces

Deux modes de routage sont dans la portée de la conception :

1. **Routage appris** entre capacités spécialisées (score calibré sur les évaluations Akasha, paire routée journalisée) ;
2. **Cascade spécialisée** entre capacités de coût et de portée différents, avec abstention précoce (`abstain`/escalade comme issue typée, §14). Si aucune capacité spécialisée ne convient, un grand modèle généraliste peut être un secours ponctuel. Tout appel distant — y compris ce secours — passe par une autorisation `RemoteInferenceGrant` préalablement approuvée : fournisseur exact, usage, catégories de données permises, expiration et budget. Chaque appel est évalué contre ce périmètre et journalisé ; aucune donnée hors périmètre ne part.

Un grand modèle généraliste n'est pas une étape normale de la cascade. Il ne peut pas être invoqué silencieusement à chaque tâche ni devenir la voie par défaut par apprentissage du routeur. Le speculative decoding avec un grand vérificateur est hors du routage nominal et du MVP : il ferait intervenir ce grand modèle à chaque requête. Toute expérimentation ultérieure devra être explicitement décidée et mesurée comme un cas séparé.

Le routage appris est une **activité journalisée** à l'intérieur du workflow, pas une étape du workflow déterministe lui-même : le planificateur/routeur structurel reste pur et reproductible, le choix appris est enregistré dans la trace avec ses entrées. Investir d'abord dans la capacité de l'orchestrateur/planificateur ; les sous-agents restent étroits, sans raisonnement étendu par défaut, et leur contribution est mesurée (§12).

Côté runtime, un graphe explicite état/nœuds/liens compilé et validé (orphelins rejetés), un checkpointer durable (SQLite en mono-poste Phase 1), des interruptions sérialisables pour l'approbation humaine, une politique de retry bornée **restreinte aux erreurs transitoires** et des timeouts par nœud satisfont les Phases 0-3. Chaque parcours déclare la durée de vie de ses états de reprise (§8.5, §8.7). Les clés d'idempotence `(goal_id, node, version, input_hash)` protègent écritures de fichiers et exécutions de code. Aucun moteur externe ne fournit le registre de contrats, les permissions ni l'évolution Akasha : ils se construisent au-dessus (§6, §13).

Côté traces, mapper la trace Akasha sur les spans OpenTelemetry GenAI (un span par invocation de nœud) via une couche d'adaptation épinglée : ces conventions sont en statut Development et ne doivent pas devenir le contrat public. Ne jamais logger par défaut prompts, secrets ou contenus bureau/code bruts.

### 8.5 Précisions v0.3 — environnement partagé, approbations, ordonnancement

**Lease exclusif par environnement.** Chaque adaptateur mono-instance (bureau, dépôt actif) délivre un lease exclusif par objectif. Une action à effet de bord acquiert le lease juste avant l'effet et le libère après observation ; un objectif en attente d'approbation ne détient aucun lease. Les objectifs concurrents sur un même adaptateur sont sérialisés en file d'attente, jamais entrelacés. Le parallélisme ne reste possible que sur des ressources disjointes (§8.2) ; en Phase 0-1, un seul objectif touche l'environnement à la fois. Le besoin de focus ou de clavier est déclaré au manifeste (`focus_required`) et sérialisé comme le lease ; les prises de focus sont comptées dans la trace. L'utilisateur peut préempter un objectif par un contrôle indépendant des modèles (§9.6) : pause journalisée, reprise au prochain point sûr.

**Approbations en attente.** Pour un parcours à reprise durable, le checkpointer (§8.4) enregistre la demande d’approbation avec son objectif, son nœud, son descripteur d’action, sa classe de risque (§13.6), l’aperçu du diff ou de l’effet et son échéance. Cet enregistrement suit les règles de conservation et d’effacement (§10). Le journal d’audit reçoit les métadonnées minimales de décision. Le workflow en attente libère son lease. L’expiration produit `approval_expired` (§14) et toute reprise exige une nouvelle demande avec une nouvelle échéance. Les notifications restent locales par défaut (§13.7). Pour l’image via MCP, l’attente de tâche vit dans le processus serveur et la CLI recueille les accords de téléchargement (§8.7).

**Décision signée (interprétation du §11.6).** Sur mono-poste, « signée » désigne une entrée append-only du journal d'audit : horodatage, catégorie d'acteur, classe d'action, décision, descripteur d'action expurgé si nécessaire, version de politique et de capacité exécutée, digest de l'entrée précédente. Elle n'inclut ni prompt, contenu utilisateur, identifiant direct, artefact, ni digest du contenu utilisateur. Une signature cryptographique par keystore OS peut être ajoutée sans changer le format ; aucune infrastructure PKI en Phase 0-1.

**Résidence des modèles.** La VRAM et la RAM sont des ressources louées au même titre que le lease d'environnement. Le gestionnaire de ressources (§6.2) admet le chargement et l'appel selon les budgets et les fonctions réellement exposées par chaque moteur. Il ne décharge ou ne déplace un modèle qu'aux points sûrs ; un calcul en cours n'est pas interrompu pour libérer de la VRAM, sauf arrêt d'urgence (§9.6).

**Ordonnancement multi-objectifs.** File par priorité (interactif > maintenance), FIFO par défaut, repriorisation utilisateur journalisée. Un objectif démarre si ses ressources sont disponibles — lease, résidence des modèles demandés (§6.2), limites `max_concurrent` des `resource_profile` (§6.1) — sinon il attend. Préemption seulement aux points sûrs : entre nœuds, après flush des artefacts, checkpoint pris. Un effet en cours n'est jamais interrompu, sauf arrêt d'urgence indépendant des modèles (§9.6). Les budgets du GoalSpec (temps mur, coût, appels) sont vérifiés aux frontières de nœuds ; un dépassement produit l'erreur typée `budget_exceeded` (famille ressource, §14) et un résultat partiel.

### 8.6 Décision v0.17 — Porte de décision outillée (akasha-model)

Une porte de décision est un composant sans effet de bord qui évalue en une passe un appel ou un choix de routage. Elle produit `ready` pour une proposition admissible, `abstain` si une clarification est requise et `blocked` en cas de refus. L’hôte gère l’exécution et les leases d’environnement (§8.5). Le bac du pilote désactive le réseau. L’hôte lui fournit la roue approuvée et les signaux nécessaires à l’évaluation.

Le contrat distingue trois décisions typées. `Choice` choisit parmi les outils proposés, `Score` évalue un signal gradué et `Noul` applique un seuil binaire. L’hôte fournit les signaux et les seuils. Le pilote évalue le risque à partir de la classe déclarée et contrôle l’admissibilité de la proposition.

Le contrat est indépendant du paquet. La version, l’empreinte, la licence et la provenance sont épinglées (§6.1). Les seuils s’appuient sur les évaluations Akasha (§8.1, §12). Le workflow journalise la décision et ses entrées pour permettre le rejeu (§8.4). Les contrôles comptent séparément les verdicts `ready`, `abstain` et `blocked` erronés. L’abstention produit une demande de clarification typée (§14).

Le pilote du MVP couvre le Path A de `akasha-model==0.3.0` (MIT) sur le banc Tâches CPU. Après accord de téléchargement (§13.5.1), le bac vérifie l’empreinte de la roue et l’installe hors ligne. L’option `--gate-request` active le pilote pour évaluer la proposition produite par le routeur.

L’hôte conserve la responsabilité des autorisations (§13), des classes de risque (§13.6), des approbations humaines, des `RemoteInferenceGrant` (§8.4) et des permissions du GoalSpec. Après un verdict `ready`, il revérifie le GoalSpec et la décision du registre avant l’exécution. Une promotion exige les preuves du §11.6, dont un gain attribué face au routage déterministe et les contrôles de non-régression des autres familles. Le pilote a obtenu 12/12 comme la référence sur la matrice et a augmenté le temps du rejeu apparié. Le routage déterministe est donc actif par défaut. [Résultats du pilote](../plans/phase4_status.md#porte-de-décision-tâches-avec-akasha-model-030)

### 8.7 Accès MCP local

Le serveur stdio `scripts/akasha-mcp.py` expose les outils Notes, la préparation de projet lorsque `--project` est configuré et la génération d’images. Notes et les propositions relisent leurs rapports durables. Le registre persistant des images conserve la qualification et les décisions techniques. Le processus MCP conserve en mémoire la demande, l’état d’attente, le résultat et l’identifiant de la tâche image.

Le parcours image expose `image_start(prompt)`, `image_status(task_id)`, `image_resume(task_id)` et `image_result(task_id)`. Le serveur fait passer une tâche par `waiting`, `running`, puis `passed`, `failed` ou `awaiting_download_approval`. L’attente décrit l’artefact manquant et ses références de provenance. L’opérateur utilise la CLI interactive `image_cli --prepare` avec le même cache pour donner chaque accord. `image_resume` revérifie le cache et reprend la description conservée avec le même identifiant. Si un artefact manque toujours, la tâche reste en attente de son accord. La réussite restitue le verdict structuré et le PNG dans un contenu MCP `image/png`.

Après un redémarrage du serveur, l’ancien `task_id` est inconnu. Le client soumet de nouveau la demande avec `image_start` et reçoit un nouvel identifiant. Le serveur vérifie les artefacts présents et réutilise la qualification compatible. Tout téléchargement nécessaire suit l’accord par artefact. La réouverture d’une session G1 restaure le contexte durable admis de la conversation (§10.6).

`--runs` choisit le stockage des essais Notes et des propositions de projet. `--image-runs` choisit le registre et le cache des images. Les tâches MCP passent par la file desktop partagée du serveur pour sérialiser l’accès au bac. Les réservations d’inférence coordonnent le moteur d’image avec les autres modèles locaux. [Configuration et outils](../../README.md#utiliser-akasha-brain-depuis-un-agent)

### 8.8 Collecte web et connexions aux services tiers

**Lecture web publique.** Le parcours desktop reçoit une URL, demande un accord pour une lecture HTTPS et renvoie l’adresse effectivement consultée, l’heure du relevé, un extrait textuel et son éventuelle troncature. Il traite une URL à la fois. Le HTML statique et les réponses texte ou JSON forment le premier périmètre. Les scripts et chargements secondaires sont désactivés. Les réponses web restent des données externes et ne peuvent déclencher une action ou élargir les permissions. L’adresse peut être reprise dans le tour suivant, avec un nouvel accord avant la prochaine requête.

**Cadre cible de connexion.** Déclarer les services et leurs opérations dans le registre de capacités avec un adaptateur versionné. Envisager des adaptateurs HTTP décrits par OpenAPI et des clients MCP explicitement configurés. Le runtime examine l’identité du service, la destination, le schéma d’entrée et de sortie, la classe d’effet, les données transmissibles, le budget et les permissions par opération. Il transmet au service les seules données autorisées et restitue des résultats structurés avec provenance. Un fournisseur absent ou une opération hors périmètre produit un diagnostic typé.

Les connexions authentifiées associent explicitement une identité et des portées à un service, au moyen d’OAuth à portée minimale ou d’une clé API dans le vault selon le fournisseur. La résolution des secrets est réservée à l’adaptateur autorisé. Prévoir l’état de connexion, le renouvellement, l’expiration et la révocation. Les opérations qui modifient ou publient des données passent par une approbation d’effet distincte de l’accès en lecture. Qualifier le cadre avec deux services de test de profils différents. YouTube reste un scénario d’usage pour les liens publics et son éventuel connecteur dédié est différé.

Le pilote G11 charge un manifeste JSON choisi par l’opérateur et expose ses opérations en ligne de commande. Il couvre les services publics et les clés API Bearer conservées dans le coffre Windows. La durée renouvelable porte sur l’accord local. Le banc vérifie aussi une révocation après établissement de TLS, avant l’émission de la requête HTTP. OAuth reste une extension du contrat. [Rejeu Windows](../../bench/results/service-connections-g11.json)

## 9. Système spatial et modèle du monde

### 9.1 Quatre fonctions distinctes

1. **Perception** : convertir images, vidéos et capteurs en observations.
2. **État spatial** : maintenir objets, repères, géométrie, relations, visibilité et incertitude.
3. **Dynamique prédictive** : prévoir l’évolution sous l’effet d’actions candidates.
4. **Planification et contrôle** : choisir, transmettre et vérifier les actions.

JEPA peut contribuer aux représentations et à la prédiction; Akasha Brain ne suppose pas qu’un unique modèle assure toute la géométrie, la planification, la commande et la sécurité.

### 9.2 État spatial

L’état peut associer représentation latente, entités identifiées, positions, orientations, tailles, repères, cartes d’occupation, relations, état cinématique, visibilité, fraîcheur, incertitude et objectifs. Chaque donnée géométrique indique repère, unité, source et confiance.

### 9.3 Dynamique conditionnée par l’action

Un modèle du monde orienté vers la planification reçoit état initial, représentation d’action et séquence ou politique candidate. Il prédit des états futurs, l’incertitude, les contraintes potentiellement violées et les coûts. Le planificateur compare plusieurs futurs, exécute une action limitée, observe le résultat réel et recalcule.

Des vidéos passives enseignent des régularités temporelles. La prédiction des conséquences d’interventions demande des données reliant actions et transitions : trajectoires, simulation ou interaction contrôlée.

### 9.4 Adaptateurs d’environnement

Chaque interface — bureau, simulateur, jeu, robot, capteur — déclare observation normalisée, actions possibles, paramètres, préconditions, limites, contrôles, arrêt d’urgence et résultats d’action. Une représentation d’objectif peut être commune; les modèles de dynamique et actions restent adaptés au domaine.

### 9.5 Écart entre prévision et résultat

Après l’action, comparer état prévu et observé, mesurer l’erreur par variable et horizon, détecter dérive, capteur dégradé ou nouveau domaine, réduire la confiance si nécessaire et enregistrer la transition observée. Une prédiction du modèle ne devient pas une observation du monde réel.

### 9.6 Contrôle sûr

Les actions importantes utilisent permissions explicites, préconditions et limites. Les horizons d’action sont plus courts avec l’incertitude ou le risque. Un mécanisme d’arrêt est indépendant des modèles. Les tâches irréversibles suivent leur classe d’approbation. Lorsque c’est possible, les politiques sont évaluées dans un simulateur avant l’environnement réel.

### 9.7 Banc d'essai bureau & code du prototype

Sur le banc d'essai bureau/code, l'état est discret et largement observable (arbre d'accessibilité, DOM, fenêtre/focus, système de fichiers, diff git, processus, état applicatif) et les transitions sont rejouables (snapshot, git, bac à sable) — à mesurer, non à supposer : les environnements réels restent fragiles. Ce banc valide des mécanismes réutilisables ; son état symbolique ne représente pas à lui seul la perception spatiale et l'action incarnée visées à long terme. Les quatre fonctions du §9.1 sont conservées, traduites ainsi :

- **5a État explicite versionné** (`DesktopState`/`CodeState` : provenance, fraîcheur, incertitude) avant tout pixel ; le screenshot ne vient qu'en appoint, et un latent n'est jamais un état vérifiable.
- **5b Prédicteur de transition symbolique** : prédire le delta d'état structuré (élément, focus, contenu, état applicatif) ; la synthèse d'écran est différée. Un scoreur latent rapide de candidats est admissible, à condition d'une ablation « prédicteur aléatoire » avant de croire à la dynamique apprise.
- **5c Prédiction d'exécution de code** subordonnée à l'interpréteur et aux tests réels, qui restent l'oracle exact (§9.5).
- **5d Vérificateur de transition** comme garde supplémentaire avant envoi, suppression ou commit — jamais comme gate unique : un score probabiliste ne remplace ni le vérificateur déterministe ni l'approbation humaine (§11.5, §13).

Différés **sur ce banc d'essai** : reconstruction 3D métrique, profondeur/pose, contrôle continu, entraînement d'un encodeur visuel général from scratch. Ces sujets appartiennent à la piste spatiale séparée (§17) ; ils demanderont un plan dédié aux environnements spatiaux et à l'action. Métriques du banc : succès vérifié par l'état final, exactitude du delta d'état par horizon, gain de sélection d'action à politique figée, faux-acceptés du vérificateur, écart prévu/observé par variable, latence/coût par décision, taux de rollback réussi. Le prédicteur du banc s'entraîne sur les transitions (état, action, état) collectées en Phases 1-3 ; elles ne suffisent pas à valider un modèle spatial général.

## 10. Mémoire et compétences

Types de mémoire :

- tâche : GoalSpec, plan, artefacts, résultat, feedback et trace;
- épisode : expériences contextualisées;
- procédure : workflows ou programmes vérifiés;
- sémantique : faits et relations avec provenance et date;
- capacités : résultats par nœud et lien;
- préférences : choix utilisateur explicites et portée.

Les mémoires et expériences utilisateur ont des politiques distinctes de conservation, partage, correction et suppression, séparées du journal d'audit. Par défaut, aucune donnée utilisateur ne sert à entraîner un modèle partagé. Un tel usage exige un accord explicite, limité à une finalité et à un périmètre documentés, ainsi qu'une filiation entre les données et les versions entraînées.

Une expérience ne devient compétence qu’après définition des préconditions, validation du résultat, méthode d’échec/refus, provenance, version, tests de réutilisation et permissions. Toute récupération vérifie que le nouveau contexte correspond aux préconditions.

### 10.1 Précisions v0.2 — dynamiques, retrieval, cycle de vie

- **Trois dynamiques séparées**, chacune avec contrat et métriques propres : formation (capture d'expériences dans un stockage effaçable, extraction sélective), évolution (consolidation épisode → sémantique/procédure, versionnée avec provenance et rollback), retrieval. Seul le journal d'audit minimal est append-only ; il ne contient pas les épisodes ni leur contenu (§10.2).
- **Mémoire de travail explicite** distincte des archives : fenêtre de contexte paginée, politiques d'éviction écrites dans l'`ExperienceRecord`. Les faits sémantiques sont bi-temporels (`valid_from`/`valid_to`, `recorded_at`) pour corriger l'historique ; une demande d'effacement prévaut sur la conservation historique et retire le contenu ainsi que ses dérivés.
- **Retrieval combiné**, pas seulement similarité cosinus : récence/importance/pertinence journalisées, graphe + PageRank personnalisé en complément. Le **filtre dur de préconditions** (§10) est une hypothèse Akasha à benchmarker en Phase 2 (A/B contre la similarité), non un acquis de la littérature.
- **Cycle de vie des compétences :** `candidate → active → dépréciée → retirée`, plafond de compétences actives, score de contribution par compétence, retirement piloté par les résultats avec rollback (§11). Une compétence naît de pratiques répétées et testées (API exécutable), jamais d'un seul succès. L'accumulation illimitée dégrade le retrieval : c'est une contre-indication directe à « toute expérience devient compétence ».
- **Rétention et effacement :** le score de rétention et la courbe d'oubli ne retardent jamais une demande d'effacement. Celle-ci couvre le contenu source et ses dérivés retrouvables (résumés, faits sémantiques, index, graphes, artefacts et jeux d'entraînement). Le journal d'audit append-only ne conserve qu'un événement minimal de traitement et son résultat, sans contenu utilisateur ni empreinte du contenu. L'effacement est confirmé seulement après traitement des copies contrôlées et des dérivés ; les limites et critères de preuve doivent être spécifiés avant la Phase 2 (§19).

### 10.2 Stockage et cycle de vie des artefacts (v0.3)

Racine de données unique (`AKASHA_HOME`, défaut sous le profil utilisateur) : `registry/`, `runs/`, `artifacts/`, `memory/`, `journal/`, `config/`. Les artefacts sont adressés par contenu (digest = adresse, alignement §6.1) ; le SQLite du checkpointer (§8.4) vit dans la racine. Les identifiants et index d'artefacts dérivés de données utilisateur sont eux-mêmes soumis à l'effacement. Le journal d'audit est une piste append-only distincte, sans contenu utilisateur ni digest permettant de tester ou retrouver ce contenu.

- **Rétention par défaut**, versionnée et configurable : données temporaires de travail jusqu'à la fin de la tâche, sauf conservation autorisée ; résultats techniques minimisés 90 jours ; copies de contenus réels autorisés pour l'évolution et leurs dérivés 30 jours ; captures d'écran réelles et texte OCR associé 7 jours. Les scénarios synthétiques du banc et leurs versions sont conservés tant qu'utiles, avec la variante de transfert toujours séparée de l'optimisation. Le journal d'audit minimal append-only n'a pas d'expiration automatique ; ses métadonnées restent protégées et ne sont pas réputées anonymes.
- **Calcul et portée :** chaque échéance court à partir de la création de la copie ; une consultation ne la renouvelle pas. Un dérivé expire au plus tard à la première échéance applicable à ses sources et à sa propre classe. Les autorisations d'utilisation ont leur échéance propre et ne prolongent pas les données déjà créées. Ces durées s'appliquent aux copies et dérivés gérés par Akasha, pas aux fichiers d'origine du projet ; les résultats visibles de la tâche suivent leur propre politique et ne sont pas assimilés automatiquement à des copies pour l'évolution. L'utilisateur peut ajuster les valeurs et demander une suppression anticipée ; l'élargissement d'une durée ou des catégories de données réelles exige un accord explicite dans le périmètre concerné. L'expiration déclenche l'arrêt d'utilisation et l'effacement selon le §10.5 ; une demande d'effacement prévaut sur une rétention ou un besoin de replay.
- **Effacement et garbage collection :** l'effacement ciblé contourne la règle ordinaire des références : il retire ou expurge le contenu demandé et tous ses dérivés recensés, puis ajoute un événement de résultat minimal au journal d'audit. Les sauvegardes doivent appliquer les mêmes suppressions et ne jamais réintroduire un objet effacé lors d'une restauration. Aucune suppression n'est déclarée terminée tant qu'une copie contrôlée ou un dérivé demeure lisible. Le GC ordinaire peut aussi retirer les artefacts non référencés après leur fenêtre de rétention ; toutes les opérations sont tracées sans réintroduire le contenu supprimé.
- **Budget disque :** plafond configurable ; en dépassement, éviction des non-référencés les plus anciens d’abord, alerte. L'effacement explicite reste prioritaire sur le budget et les besoins de replay.

### 10.3 Interface des compétences (v0.3)

Une compétence est un nœud comme les autres : manifeste complet (§6, `kind: skill`), surface d’appel MCP (`inputSchema`/`outputSchema`), implémentation exécutable (programme ou workflow), suite de tests, provenance des épisodes motivateurs. Aucun chemin d’exécution spécial dans le runtime.

- **Tests :** tests de contrat en entrée/sortie, plus au moins un test bout-en-bout par épisode motivateur, rejoués à la construction et à chaque promotion. Un échec rejette le candidat, il ne le déprécie pas.
- **Versionnement :** selon le §16.1 ; tout changement de comportement exige de rejouer la suite de tests et les épisodes motivateurs.
- **Contribution et retirement :** score de contribution calculé sur les résultats post-promotion (§10.1) ; le retirement retire la compétence du registre actif mais conserve l’artefact et ses tests pour le replay (§16.1).

### 10.4 Données autorisées pour l'évolution locale (v0.14)

**Distinction d'usage.** L'autorisation de lire ou traiter une donnée pour exécuter la tâche courante ne vaut pas accord pour la conserver ou la réutiliser ensuite dans l'évolution. L'interface continue de présenter le résultat de la tâche selon sa politique de rétention propre ; la politique d'évolution s'applique séparément à toute copie, extraction ou réutilisation pour préparer, évaluer ou promouvoir un workflow candidat.

**Admis par défaut.** L'évolution locale peut utiliser les scénarios synthétiques autorisés du banc de référence et leurs données de développement/validation, ainsi que des résultats techniques minimisés : catégorie de tâche prédéfinie, versions de capacités et de workflow, étapes utilisées, durées, ressources, compteurs, statut des vérifications et codes d'erreur typés. Ces résultats ne sont pas réputés anonymes : ils sont protégés, soumis à une durée de rétention et effaçables selon leur classe. La variante de gestion de tâches réservée au transfert, son dépôt, ses détails et ses résultats sont exclus de l'optimisation (§12.3). Une donnée dite synthétique produite à partir d'un contenu réel conserve la filiation de ce contenu et ne devient pas automatiquement admissible.

**Contenus réels sur accord explicite.** Par défaut, les demandes et réponses textuelles, fichiers et extraits de code, diffs, sorties détaillées de tests, captures d'écran, contenus OCR et commentaires libres de l'utilisateur ne sont pas réutilisés pour l'évolution. Leurs résumés, embeddings, exemples ou autres dérivés suivent la même règle ; une dépersonnalisation non démontrée ne suffit pas à les autoriser. Le filtrage des résultats techniques utilise une liste de champs autorisés et des codes d'erreur structurés, sans noms ni chemins de fichiers, URL, texte libre, captures, sorties brutes ou empreintes de contenus réels. Si la sûreté d'un champ est incertaine, le retirer ; un masque automatique n'est pas une garantie de suppression des secrets.

L'utilisateur peut donner **avant réutilisation** un accord explicite pour un projet et les catégories précises de contenus concernés, à la seule finalité d'évolution locale des workflows. La politique indique au minimum projet, catégories, finalité, date, durée ou échéance selon la politique de rétention, et état de révocation ; elle est consultable et modifiable dans l'interface. Sans accord valide, ou si le projet, la catégorie ou la provenance sont inconnus, la réutilisation est refusée. Une tâche impliquant plusieurs projets exige l'accord correspondant pour chacun ; une autorisation d'accès à un dépôt ne vaut pas accord d'évolution. Les secrets, clés, mots de passe et jetons sont exclus de l'évolution, même en présence d'un accord ; les mécanismes d'isolement et de minimisation ne reposent pas seulement sur leur détection.

**Révocation et suppression.** Révoquer l'accord bloque les nouvelles utilisations et les travaux en attente ; les essais en cours s'arrêtent au prochain point sûr et leurs candidats ne sont pas promus sur des données devenues interdites. L'utilisateur peut demander séparément la suppression des données et de leurs dérivés contrôlés par Akasha : appliquer la filiation, invalider ou reconstruire les candidats et versions dépendants lorsque nécessaire, traiter les sauvegardes et ne confirmer la suppression qu'après vérification (§10.1-10.2). Cette suppression ne supprime pas les fichiers du projet d'origine. Les contenus et dérivés effaçables restent hors du journal d'audit append-only ; son événement minimal ne contient aucun contenu réel.

**Frontières.** Pour le MVP, cette politique ne concerne que l'amélioration des workflows et de leurs connexions : aucun entraînement des poids n'en découle. L'accord local ne donne ni droit d'accès supplémentaire aux outils ou fichiers, ni autorisation d'envoyer les données à un moteur distant, ni accord pour un entraînement partagé. Ces usages conservent leurs permissions et accords propres (§13.3, §13.7). Les valeurs par défaut et les obligations de sauvegarde sont définies aux §10.2 et §10.5 ; leurs mécanismes et critères de preuve restent à concevoir et vérifier en Phases 0 à 2 (§19.6).

### 10.5 Sauvegarde locale et non-résurrection (v0.15)

**Politique par défaut.** Une sauvegarde automatique locale chiffrée est prévue chaque jour ; les sauvegardes sont conservées pendant une fenêtre glissante de 7 jours, sans envoi vers le cloud par défaut. Elles peuvent contenir la configuration, les versions du graphe, le journal d'audit minimal et les résultats techniques admissibles. Les copies de contenus réels d'un projet et leurs dérivés ne sont incluses qu'après un accord distinct et explicite de sauvegarde pour ce projet et les catégories concernées ; l'accord d'évolution seul ne suffit pas. Les fichiers originaux du projet ne sont pas inclus par cette option. Les secrets restent exclus ; les exports ou sauvegardes externes que l'utilisateur contrôle lui-même sont hors du périmètre d'effacement d'Akasha et doivent être signalés comme tels.

**Expiration et suppression.** Une sauvegarde ne prolonge jamais la durée de vie d'une donnée : son échéance d'origine et celle de ses sources accompagnent chaque copie, y compris après restauration. À l'échéance ou sur demande de suppression anticipée, bloquer la réutilisation et engager sans délai le traitement des copies, caches, fichiers temporaires, checkpoints, index, dérivés et sauvegardes contrôlés par Akasha. Invalider, reconstruire ou retirer les candidats et versions dépendants si nécessaire ; le besoin de replay ne crée pas d'exception. La suppression n'est confirmée qu'après traitement et vérification de toutes les copies et de tous les dérivés contrôlés. Si une sauvegarde ne peut être traitée immédiatement, afficher un état « en attente » et son motif jusqu'à vérification, sans annoncer de succès. L'effacement cryptographique ne vaut preuve que si les clés appropriées et toutes leurs copies contrôlées ont été détruites ; aucune réécriture physique n'est présumée.

**Restauration.** Conserver hors de la version à restaurer un registre minimal et protégé de marqueurs de suppression, distinct du journal d'audit, aussi longtemps qu'une sauvegarde susceptible de réintroduire les données existe. Avant toute exposition ou utilisation d'une restauration, appliquer les marqueurs et les échéances ; si ce registre est absent ou invérifiable, refuser la restauration ou son exposition jusqu'à résolution. Aucun contenu brut ni empreinte de contenu utilisateur ne figure dans le journal d'audit immuable. Le choix du chiffrement, le stockage et la récupération des clés, le mécanisme de suppression dans les sauvegardes et les preuves associées restent à spécifier et tester en Phases 0 à 2 ; ces exigences décrivent le MVP à construire, pas des capacités déjà implémentées.

### 10.6 Sessions et protection des secrets dès G1

Avant toute écriture durable de session, un contrôle hors modèle vérifie les champs et les valeurs selon un schéma fermé. Il admet les identifiants internes, les références de projets autorisés, les métadonnées de rétention et les faits structurés dont l’admissibilité est établie. Les demandes et réponses en texte libre, les pièces jointes et les valeurs dont l’admissibilité reste indéterminée demeurent en mémoire volatile. Les fichiers de session, mémoires, traces, journaux et sauvegardes contrôlés excluent les secrets et leurs empreintes, y compris dans les dérivés et les diagnostics de refus. Les liens vers la mémoire globale suivent les mêmes contrôles et la politique de réutilisation du §10.4.

G1 permet de rouvrir les faits admis d’une session après redémarrage, sous réserve des échéances et de l’effacement (§10.2, §10.5). Son critère de sortie vérifie l’isolation entre deux sessions ouvertes sur un même projet et l’absence d’un secret synthétique et de son empreinte dans les copies contrôlées, avant et après redémarrage. G2 ajoute le scellage dans le keystore OS, le stockage des métadonnées de handle dans le vault applicatif et la résolution par une action autorisée et journalisée.

La cible web précédente et l’extrait collecté restent volatils et propres à la conversation desktop. Ils disparaissent au redémarrage. L’historique durable et les sauvegardes excluent les URL complètes et les réponses web.

## 11. Boucle d’auto-évolution

### 11.1 Cycle de changement

1. **Observer** : recueillir les éléments nécessaires à la tâche et consigner pour l'évolution les résultats techniques minimisés ; toute réutilisation de demande, état, sortie ou autre contenu réel suit l'accord par projet et catégorie du §10.4.
2. **Attribuer** : localiser l’erreur ou le gain par étape et par liaison.
3. **Formuler** : proposer sélection, nouveau lien, adaptateur, compétence, changement de règle ou spécialiste.
4. **Construire** : modifier une copie isolée du graphe.
5. **Évaluer** : rejouer les cas historiques, tester des cas réservés et comparer avec la référence.
6. **Promouvoir** : activer une version après satisfaction des critères de risque et de qualité.
7. **Surveiller** : suivre résultats et régressions réels.
8. **Annuler** : revenir à la version antérieure si les limites sont dépassées.

### 11.2 Niveaux d’évolution

- A : sélectionner un autre chemin validé;
- B : ajuster lien, conversion ou ordre;
- C : enregistrer une compétence;
- D : ajuster prompt, règle, paramètre ou adaptateur;
- E : intégrer, entraîner ou affiner un modèle spécialisé;
- F : améliorer un modèle du monde avec des données d’interaction validées.

Les niveaux supérieurs exigent davantage de preuves, ressources, droits de données et contrôles.

### 11.3 Détecter une lacune

Avant de proposer un modèle, vérifier dans l’ordre : qualité et complétude de l’entrée, contrat et repères, routage, dépendances du workflow, disponibilité des données, répétition de l’échec dans des contextes distincts et possibilité de le résoudre par outil déterministe ou adaptateur.

Une lacune devient candidate lorsqu’un sous-problème récurrent demeure non résolu et qu’une mesure peut distinguer le candidat de la référence. Le seuil dépend de la classe de risque et du coût d’erreur.

### 11.4 GapReport

Le rapport de lacune contient la famille de tâches, exemples dépersonnalisés, graphes essayés, résultats et erreurs, causes écartées, transformation attendue, proposition de changement, jeu d’évaluation, données et droits nécessaires, coût, risques, permissions et rollback.

### 11.5 Promotion

Comparer réussite, contraintes, robustesse, calibration, sécurité, ressources, coût, latence, contribution des nœuds/liens et effets sur les autres tâches. Les critères sont propres au domaine. Une moyenne favorable ne compense pas une violation critique. Les candidats peuvent fonctionner en replay ou en mode observation avant toute action. Conserver l’artefact, l’évaluation, la décision et le parent de version.

### 11.6 Précisions v0.2 — promotion par paliers

La promotion suit des paliers explicites : **replay (0 %) → observation/shadow → exposition limitée → actif**, chaque palier avec durée d'observation, métriques comparées à la référence, décision signée conservée (§16) et rollback vers la version parent. L'unité d'exposition sur le terrain local (types de tâches, dépôts, applications) est définie par Akasha ; la mécanique de trafic réseau des outils de déploiement continu n'est pas transposable telle quelle. Un graphe candidat est une **nouvelle version compilée et checkpointée**, testée en replay avant promotion : jamais de mutation du graphe actif par un nœud de travail. La gouvernance (qui promeut, qui annule, registre des risques par `risk_class`) suit le §13.4.

### 11.7 Auto-évolution bornée du MVP

- **Déclenchement et ressources :** à la fin de chaque tâche utilisateur éligible selon la politique de confidentialité, réussite ou échec, lancer les essais en arrière-plan sans attendre l'inactivité ; sans accord sur les contenus réels, utiliser uniquement le banc synthétique admissible et les résultats techniques minimisés du §10.4. Les essais internes ne déclenchent pas d'autres essais. Si un budget ou une capacité manque, la demande reste en attente avec motif visible. Limites configurables de CPU, RAM, VRAM lorsqu'elle est utilisée, durée, concurrence et nombre d'essais ; une nouvelle tâche interactive est prioritaire aux points sûrs. L'utilisateur peut suspendre et reprendre les essais et demander le retour à une version précédente.
- **Portée :** recombiner, sélectionner ou réordonner des nœuds, liens et outils déjà déclarés et compatibles, sans créer de nouvelle implémentation de capacité, entraîner ou créer un modèle, modifier les permissions, élargir les données accessibles ni sortir du banc isolé. Le spécialiste de code peut toujours produire et tester les modifications demandées dans le dépôt du banc. Les actions candidates sont limitées aux classes R0/R1 autorisées ; une action de classe supérieure reste soumise à la politique du §13.6.
- **Évaluation :** construire un graphe candidat versionné dans un environnement isolé ; vérifier ses contrats et préconditions ; exécuter replay, observation et exposition limitée dans le banc avant activation (§11.6). La suite de tests, ses vérificateurs et ses références sont fixés en dehors du candidat ; celui-ci ne peut ni les modifier ni choisir seul une condition qui le ferait réussir. Les tâches de développement et validation servent à la comparaison ; la variante de transfert reste réservée à une évaluation indépendante et doit être renouvelée si des usages répétés risquent de la contaminer.
- **Décision :** les critères critiques de sécurité, de permissions et de correction ne sont jamais compensés par une économie de ressources. Privilégier une fiabilité supérieure démontrée ; à fiabilité démontrée comparable, préférer une latence ou une consommation plus faible, dans les budgets fixés. Seuils, méthode statistique et niveau de preuve sont définis après les mesures de Phase 0/1 ; trois essais sont du profilage, pas une preuve de gain ou d'équivalence. Données insuffisantes, échec d'un contrôle ou résultat ambigu : le candidat n'est pas activé.
- **Activation et retour :** la politique, hors modèle de travail, peut promouvoir automatiquement la version candidate validée pour le banc R0/R1. La décision, les versions, les évaluations et le motif sont journalisés sans contenu utilisateur brut ; une exécution déjà commencée garde sa version. Sur régression ou demande utilisateur, retour sûr à une version antérieure et suivi de l'état. Aucun recours distant ou grand modèle n'est déclenché hors de la politique et du grant applicables.

### 11.8 Récupération des capacités déclarées

La conversation transmet les demandes libres au planificateur et au registre. Lorsqu’une capacité manque, le contrôleur recherche les artefacts des fournisseurs déclarés et consigne la lacune dans `capability-recovery.sqlite`. Les fournisseurs intégrés couvrent la lecture d’image avec RapidOCR et la génération locale d’images avec SD-Turbo. Une capacité dépourvue d’adaptateur compatible reste en attente avec un motif.

RapidOCR est qualifié sur des images synthétiques avant la lecture demandée. Le parcours image suit les accords, l’identité et la qualification du §6.3. Le contrôleur reprend la demande après activation, réutilise les preuves compatibles et retire l’activation si le contrôle de sortie échoue. La reprise emploie les implémentations déclarées et les autorisations vérifiées hors modèle. Les candidats de workflow continuent de suivre les paliers du §11.7. [Reprise RapidOCR](../../bench/results/conversation-capability-recovery-v1.json) · [Reprise image à cache vide](../../bench/results/image-mcp-cold-cache-v1.json)

G3 ordonne les démarches possibles pour une demande. Le planificateur vérifie d’abord les préconditions et les permissions, puis cherche un chemin déclaré et une reprise locale autorisée. Si cette reprise exige un accord, la tâche attend la décision dans le parcours prévu (§8.5, §8.7). Une fois le prérequis vérifié, elle reprend la demande initiale. Si aucun chemin déclaré ni reprise locale ne convient, G3 évalue les voies A–D admissibles sur un graphe candidat isolé. Une proposition de niveau E exige un `GapReport` et l’accord correspondant (§11.2, §11.4). Le runtime applique les règles de promotion et d’autorisation (§11.6, §13). Le §14 définit les issues utilisateur.

## 12. Évaluation

Évaluer aux niveaux capacité, liaison, workflow, système de bout en bout, transfert longitudinal, environnement et évolution. Mesurer plusieurs signaux :

- réussite vérifiable et respect des contraintes;
- succès observé dans l’environnement;
- tests, assertions, solveurs et vérificateurs;
- feedback utilisateur;
- incertitude calibrée;
- coût, latence, appels, reprises et ressources;
- sécurité et régressions.

Un jugement du même modèle qui a produit la sortie ne suffit pas comme preuve unique.

Les ensembles versionnés contiennent références, contre-exemples, variations, cas réservés de promotion, scénarios simulés et séquences temporelles. Les sources, droits et transformations de données sont consignés. Les cas de validation réservés ne servent pas automatiquement à entraîner le candidat évalué.

### 12.1 Précisions v0.2 — jeux d'évaluation du premier terrain

- **Code :** tâches type SWE-bench sur le dépôt cible (issues réelles, tests `FAIL_TO_PASS`/`PASS_TO_PASS`), harness figé et versionné (image, commit, tests) tracé dans l'`ExperienceRecord`.
- **Bureau :** sous-ensemble type OSWorld réduit et hermétique, évaluation par l'état final exécuté (fichier, registre, application), jamais par transcript ni similarité d'écran ; snapshot d'état initial et restauration.
- **Références :** baseline humaine sur les mêmes tâches et baseline fixe simple de type pipeline déterministe (localisation → réparation → validation) ; le graphe évolutif ne se justifie que s'il la bat à coût mesuré.
- **Anti-contamination :** cas réservés jamais entraînés, tâches fraîches ou privées, rotation des dépôts, écart tâches vues/inédites rapporté. Les scores publics datés (2023-2024) servent de contexte, jamais de seuils : ils sont re-mesurés sur les modèles et le matériel du projet en Phase 0/1.

### 12.2 Précisions v0.3 — harness bureau Windows et protocole de mesure

**Harness bureau.** OSWorld étant Linux, le terrain Windows retient deux mécanismes complémentaires, choisis par la tâche :

1. **Windows Sandbox jetable** (configuration `.wsb` durcie, réseau désactivé explicitement, §13.5) pour les tâches à session unique sans état préparé persistant ; l'état final est capturé avant fermeture, car l'environnement ne survit pas à la fermeture.
2. **Checkpoint de VM** (Hyper-V ou équivalent) pour les tâches exigeant un état bureau préparé et restauré entre les essais ; image et checkpoint versionnés et consignés dans l'`ExperienceRecord`.

Le choix entre les deux est une hypothèse de faisabilité à trancher en Phase 0 : couverture UIA et comportement UAC dans chaque palier — angle mort connu (§19.10). L'évaluation reste par l'état final exécuté (§12.1) : capture standardisée avant/après par un script versionné — arbre d'accessibilité, fenêtres et focus, hashes des fichiers du périmètre, export des clés de registre scopées, état des processus — jamais par transcript ni similarité d'écran.

**Protocole de mesure des modèles (Phase 0/1).** Conditions figées et consignées : machine, système, versions des moteurs, modèles et quantizations, charge de fond et gestionnaire de ressources. Utiliser au moins deux spécialistes GGUF préentraînés compatibles Rbitnet pour la communication et le code, et un modèle préentraîné de vision/OCR avec un second moteur local réel, choisi pour le banc bureau/code. Mesurer le démarrage à froid, les appels à chaud, les changements de modèle, le déchargement, la concurrence, la saturation et la reprise ; rapporter réussite par exécution (§12.1), temps mur, latence, RAM/VRAM crêtes, erreurs et provenance des mesures. Trois essais par tâche constituent seulement un premier profilage : augmenter l'échantillon selon la variabilité et rapporter l'incertitude avant toute décision de promotion ou fixation de seuil. Comparer à une baseline fixe, et à une baseline humaine sur le même échantillon. Ne pas présenter une estimation comme une mesure ni importer des seuils de la littérature (§2.4).

**Shortlist des candidats.** Critères : licence vérifiée et compatible, poids disponibles localement, contexte suffisant pour l'artefact représentatif le plus long, quantization avec évaluation mesurable, empreinte compatible avec les budgets du matériel visé. Rbitnet est prioritaire pour les GGUF compatibles ; la prise en charge effective de chaque couple modèle/moteur/matériel est vérifiée et consignée. Les autres familles utilisent un adaptateur compatible évalué contre le contrat minimal (§6.2).

### 12.3 Scénarios de référence et de transfert (v0.13)

**Conditions communes.** Les deux applications, leurs versions initiales, données, tests et vérificateurs sont identifiés et restaurables dans des environnements isolés. Chaque essai repart de son état initial propre ; les données utilisées sont fictives. Le dépôt à corriger est accessible dans le bac, mais les tests et l'oracle de référence sont contrôlés hors de la portée d'écriture du candidat. Pour chaque scénario, vérifier que le test de régression échoue sur la version fautive et réussit sur une correction de référence contrôlée, sans fournir cette correction à l'agent. Rapporter séparément échec initial, diff produit, résultats des tests, observations bureau et résultat final. Aucun résultat textuel d'un modèle ne suffit comme oracle.

**Référence — application de notes, sauvegarde non persistée.** La version fautive accepte le texte d'une note et, après « Enregistrer », affiche la note et annonce une sauvegarde réussie, mais la modification reste en mémoire et n'atteint pas le stockage durable. Après arrêt et relance de l'application, la note a disparu. Le parcours code reçoit le symptôme, reproduit l'échec puis corrige le dépôt. Le parcours bureau saisit une note, déclenche la sauvegarde, ferme réellement le processus et rouvre l'application sur le même stockage de test. Le test de régression vérifie que le contenu exact réapparaît après relance ; les tests de non-régression vérifient que deux notes distinctes, dont une avec accents et plusieurs lignes, sont toutes deux conservées. Le parcours invoque réellement le modèle de vision/OCR pour une observation utile ; un contrôle indépendant de l'état persisté et de l'application détermine la réussite.

**Variante réservée — application de gestion de tâches, filtre incorrect.** L'état initial contient « Préparer la réunion » à faire et « Envoyer la facture » terminée. La version fautive affiche les deux éléments lorsque le filtre « À faire » est sélectionné. Le test de régression attend uniquement « Préparer la réunion » sous ce filtre ; les tests de non-régression attendent uniquement « Envoyer la facture » sous « Terminées », puis les deux éléments sous « Toutes », sans modification des états des tâches lors des changements de filtre. Le parcours bureau sélectionne les filtres et vérifie les éléments visibles par un moyen indépendant de l'OCR, par exemple l'arbre d'accessibilité ou un vérificateur d'état adapté. Les noms, statuts, état initial et vérificateurs sont figés pour l'essai ; le détail technique et la provenance de l'application sont choisis en Phase 0.

**Isolation du transfert.** La variante, ses données, son dépôt et ses vérificateurs sont séparés des jeux servant à générer, calibrer, sélectionner ou promouvoir les workflows. Pendant cette optimisation, aucun de ces éléments, ni le détail de la variante présent dans la présente spec, n'est fourni au modèle ou au graphe candidat ; les montages et accès sont contrôlés. Lors de l'évaluation de transfert, une version active préalablement figée reçoit seulement les entrées nécessaires à la tâche, dans un bac distinct ; l'auto-évolution et l'utilisation des résultats pour sélectionner ou entraîner les candidats sont désactivées pour cet essai. Les résultats servent au compte rendu humain. Signaler toute exposition antérieure connue et la contamination éventuelle des modèles préentraînés comme limites de l'évaluation ; si la variante est utilisée de façon répétée pour ajuster le système, la considérer exposée et prévoir une nouvelle variante réservée.

## 13. Sécurité, permissions et confidentialité

### 13.1 Permissions

Accès minimal par capacité : lire, écrire, exécuter, communiquer, modifier une ressource, agir physiquement ou modifier le registre. La présence d’un outil ne lui accorde pas de permission.

### 13.2 Isolation et provenance

- Code dans un bac à sable avec limites CPU, mémoire, temps et réseau.
- Séparation entre graphe actif, candidat et environnement d’entraînement.
- Filtrage des secrets; journalisation configurée.
- Dépendances, versions, licences et empreintes des poids enregistrées.
- Sortie libre de modèle jamais transformée directement en permission ou appel arbitraire.

### 13.3 Données

Minimiser les données d’expérience, séparer contenu utilisateur, dérivés et métadonnées d'audit, appliquer l'effacement à toutes les copies contrôlées et prévenir la résurrection depuis les sauvegardes. Aucune donnée utilisateur n'alimente un entraînement partagé sans accord explicite. Chaque accord, jeu de données et version entraînée doit être relié par une filiation permettant, sur demande d'effacement, une reconstruction sans les données concernées, un désapprentissage validé ou le retrait du modèle si l'effacement ne peut pas être démontré.

### 13.4 Gouvernance

Le modèle de travail ne peut pas se promouvoir, changer ses permissions ou modifier seul le code actif. L’évolution manager prépare; le validateur et la politique de déploiement décident. Les actions physiques et irréversibles ont des contrôles adaptés à leur risque.

### 13.5 Décision v0.7 — sandbox gradué et injection

Le niveau d'isolation est **déclaré au manifeste** (`sandbox_tier`, limites CPU/mémoire/temps/réseau) et choisi selon la confiance, pas par habitude. Pour le banc Windows, le profil durci désactive explicitement réseau, redirection du presse-papiers, entrée audio et vidéo, imprimantes et vGPU par défaut ; le vGPU ne s'active que si une tâche le requiert et après mesure de compatibilité. Aucun dossier hôte inscriptible n'est monté : les entrées passent par un espace de préparation en lecture seule et les sorties sont récupérées par un courtier d'export contrôlé. Aucun secret n'est monté. Ces précautions sont nécessaires car Windows Sandbox active le réseau, le presse-papiers et l'entrée audio par défaut ; un dossier mappé est inscriptible par défaut et ses modifications persistent après fermeture ; le vGPU peut accroître la surface d'attaque ([configuration officielle](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file)).

Paliers disponibles sur le premier terrain : conteneur rootless durci (`--network none`, système de fichiers en lecture seule, capacités retirées) ; Windows Sandbox configuré comme ci-dessus ; isolation renforcée type noyau en espace utilisateur ou microVM sur hôte Linux/KVM pour les candidats non fiables et le replay. L'ordre de force entre ces paliers est une hypothèse à valider sur un même modèle de menace, pas un fait établi. Dans tous les cas : egress direct refusé par défaut et secrets hors sandbox. La fermeture d'un bac jetable ne prouve pas l'absence d'effets persistants dans les dossiers hôtes partagés ; aucun partage inscriptible n'est admis dans le profil durci.

Les contenus de dépôt, web ou fichiers sont des **données non fiables, jamais des instructions** : la suite d'acceptation sécurité inclut des cas d'injection indirecte (README, issue, commentaire piégés). Les contrôles sont nommés au manifeste (allowlist d'outils, classe d'action, approbation requise) et les décisions d'autorisation sont journalisées dans la trace.

### 13.5.1 Autorisations d'action du MVP (v0.16)

**Banc jetable.** Dans une copie de travail du banc, Akasha peut lire, créer, modifier et supprimer des fichiers, lancer les applications et les tests, puis recommencer depuis un état initial restaurable sans approbation à chaque étape. Cette autonomie n'est accordée que si le confinement effectif et la restauration sont vérifiés, qu'aucun projet d'origine ni autre dossier hôte n'est accessible en écriture et que tests, vérificateurs et références sont protégés contre le candidat. Les contrôles d'accès et d'effets sont appliqués par le runtime, hors jugement du modèle ; si une condition manque ou est incertaine, arrêter l'action et l'expliquer. L'évolution reste limitée aux actions R0/R1 et ne peut modifier ces permissions (§11.7).

**Projet réel.** L'utilisateur ouvre explicitement le projet à traiter. Akasha lit le périmètre autorisé, prépare ses modifications dans une copie isolée et présente la proposition exacte, les suppressions ou déplacements distinctement et les résultats de vérification disponibles. Il ne modifie le projet d'origine qu'après validation de cette proposition ; les suppressions et déplacements exigent en plus un accord explicite au cas par cas. Vérifier juste avant application que le projet et les fichiers concernés correspondent encore à la proposition approuvée ; en cas de changement ou d'incertitude, ne pas appliquer et présenter une proposition actualisée pour nouvelle validation. Une approbation est limitée à la proposition et ne vaut ni permission d'autres opérations ni accord de réutilisation pour l'évolution (§10.4). En cas d'application incomplète ou d'échec, ne pas annoncer de réussite et signaler l'état constaté.

**Tests et bureau.** Les tests nécessaires peuvent être lancés automatiquement dans la copie isolée, réseau désactivé, sans secrets ni accès en écriture au projet d'origine. Si ces conditions ne peuvent être garanties, arrêter et expliquer ; ne pas contourner l'isolation en exécutant les tests sur l'hôte. L'application du diff approuvé n'autorise pas les commandes sur l'hôte. Pour le MVP, les actions bureau et la saisie restent dans l'environnement isolé ; Akasha ne manipule pas les applications de la session Windows réelle. Les téléchargements de dépendances suivent l'accord par téléchargement du §13.7.

### 13.6 Décision v0.7 — taxonomie des classes de risque

Quatre classes, attribuées structurellement — depuis les classes d'actions déclarées par l'adaptateur et le manifeste, jamais par le jugement d'un modèle (§13.4). La classe porte sur l'effet réel et sa frontière de persistance, pas uniquement sur le nom du verbe ; en cas d'incertitude, retenir la classe supérieure.

- **R0 — observation :** lecture seule, sans effet de bord (observer, rechercher, lire). Contrôles : journalisation seule.
- **R1 — effet borné et réversible :** écriture dans un environnement jetable ou changement local dont le rollback a été démontré. Contrôles : validation de contrat, périmètre borné, rollback disponible et journalisation. Une suppression dans le bac jetable est R1 si elle n'atteint aucun état hôte ou persistant.
- **R2 — effet persistant ou rollback non démontré :** fichiers ou état applicatif persistants, écriture dans un environnement partagé sans snapshot prouvé, commit local hors branche de test isolée. Contrôles : vérificateur de transition en garde (§9.7), approbation par défaut en Phase 0-1, sandbox gradué (§13.5).
- **R3 — effet irréversible ou transfert hors du périmètre local :** suppression durable de données utilisateur, envoi/publication, push, installation sur l'hôte, ou transfert réseau. Contrôles : approbation humaine obligatoire, préconditions strictes et dry-run quand il existe. Pour l'inférence distante uniquement, un `RemoteInferenceGrant` explicitement approuvé constitue l'autorisation bornée ; chaque appel doit correspondre au grant (§13.7).

Règles : la classe d'un workflow est la classe maximale de ses nœuds ; `destructiveHint=true` vaut au minimum R2 et R3 si l'effet est durable, irréversible ou traverse une frontière ; exception R1 uniquement si le runtime vérifie que l'action est confinée à la copie de travail jetable restaurable, sans effet hôte ou persistant et sans accès en écriture aux références protégées (§6.1, §13.5.1). En cas de doute ou d'échec d'une vérification, l'exception ne s'applique pas et l'action n'est pas exécutée ; une classe absente ou inconnue vaut R3 ; un objectif sous-spécifié (§5.1) ne peut exécuter aucune action R2/R3 avant clarification ; une promotion ne peut pas abaisser la classe déclarée d'une capacité sans ré-évaluation. Les actions R3 exigent une approbation humaine. Exception bornée : les appels d'inférence distante couverts par un grant sont approuvés au niveau du grant, puis vérifiés et journalisés à chaque appel ; tout appel hors périmètre est bloqué et requiert un nouveau grant (§13.7). La politique est versionnée, durcie en Phase 0-1 et relaxée seulement avec preuves (§11.6).

### 13.7 Décision v0.7 — grants réseau

Egress direct depuis le bac refusé par défaut (§13.5). L'exception générale est déclarée par un grant réseau : hôtes exacts sans joker large, finalité, catégories de données permises, durée, limites et approbateur. Un nœud de travail ne peut ni créer ni élargir ce grant (§13.4). Toute tentative autorisée ou refusée est journalisée en métadonnées minimales.

**Collecte HTTPS publique.** L’accord R3 est ponctuel, à usage unique et valable cinq minutes. L’interface affiche l’adresse exacte qui sera envoyée. Le processus de collecte hors du bac effectue un seul GET vers cet hôte sur le port HTTPS standard, sans cookie ni en-tête d’authentification. Il vérifie les adresses DNS publiques et utilise directement l’une des adresses validées avec vérification TLS du nom approuvé. Les redirections, identifiants dans l’autorité de l’URL et destinations non publiques sont refusés. L’appel a un délai maximal de 15 secondes et la lecture du corps est bornée à 256 Kio plus un octet pour détecter la troncature. Le journal local consigne l’identifiant de l’accord, l’heure et l’issue. L’adresse, ses paramètres et le contenu restent exclus de ce journal. [Protection des destinations réseau](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)

**Inférence distante.** `RemoteInferenceGrant` borne au minimum le fournisseur/endpoint, la finalité, les catégories de données pouvant être transmises, l'expiration, le budget de coût/appels, l'approbateur et la révocation. Le courtier d'inférence réside hors du bac réseau-isolé. Avant chaque appel, le runtime vérifie le grant, la classe des données, l'absence de secrets interdits, l'expiration et le budget ; il refuse par défaut en cas de doute. Chaque appel inscrit dans l'audit un identifiant de grant, le fournisseur et la version du modèle, la finalité, les catégories de données, le motif de routage, le coût et le résultat — jamais le prompt, la réponse ou leur empreinte. L'accord de partage de données utilisateur (§10, §13.3) reste distinct du grant réseau. Un grant ne donne aucun droit d'entraînement partagé.

**Installation de dépendances.** Le bac n'accède pas directement aux registres. Avant chaque téléchargement nécessaire, présenter la dépendance, sa version et sa source et obtenir un accord explicite pour ce téléchargement ; aucun accord général de téléchargement n'est déduit de l'ouverture du projet. Un résolveur hors bac récupère alors la version exacte vers un cache d'artefacts, vérifie son empreinte et sa licence, puis remet l'artefact au bac par l'espace de préparation. Les demandes nouvelles ou modifiées exigent un nouvel accord ; en cas de refus ou de prérequis manquant, arrêter le téléchargement concerné et expliquer la limite. L'installation hors ligne dans un bac jetable est R1 ; une installation sur l'hôte reste R3 et exige une approbation distincte.

## 14. Résilience et erreurs

Le runtime doit typer les erreurs, interrompre les workflows dont un contrat essentiel échoue, n’utiliser que des fallbacks déclarés, préserver les états partiels, éviter de répéter les effets de bord, borner les boucles, retourner une réponse partielle incertaine et distinguer échec du nœud, du lien, du plan, du modèle du monde ou de l’environnement. Le résultat utilisateur sépare action planifiée, exécutée et confirmée.

Après le diagnostic de G3, `missing` signale qu’aucune capacité admissible ne couvre le besoin. `abstain` clôt une demande pour laquelle les preuves restent insuffisantes pour agir dans le périmètre autorisé. `needs_clarification` demande une information susceptible de changer le plan. L’accord requis est un état suspendu du parcours, avec reprise après vérification du prérequis. Les refus d’autorisation conservent leur code de permission. Une proposition de construction décrit le candidat et ses conditions d’évaluation. Le verdict interne `abstain` de la porte du §8.6 est traduit en demande de clarification dans ce pilote.

## 15. Exigences non fonctionnelles

Les valeurs numériques seront établies après le choix d’environnement et matériel.

- Extensibilité des nœuds sans réécriture du runtime.
- Schémas stables et versionnés.
- Reconstruction de la provenance d’une sortie critique.
- Rollback de modèle, graphe, workflow et politique.
- Modèles coûteux appelés seulement selon un seuil de qualité justifié.
- Parallélisme sans conflits de ressources ou fuite d’état.
- Tolérance aux pannes et reprise déterministe lorsque possible.
- Mesure de latence, ressources, erreurs et contribution.
- Permissions appliquées hors des instructions en langage naturel.
- Portabilité locale, distante ou hybride.
- Transport, stockage et entraînement configurables et auditables.

### 15.1 Définition du coût en mono-poste (v0.3)

Métrique primaire : temps mur par tâche, sur matériel figé et machine au repos — la ressource réellement rare et partagée avec l'utilisateur. Il inclut les attentes, chargements, changements de modèle et déchargements réellement nécessaires (§6.2) ; les transferts fins ne sont mesurés que s'ils sont disponibles. Métriques secondaires : RAM/VRAM crêtes avec source et qualité de mesure, temps GPU actif par nœud, et, pour l'inférence distante, tokens et montant à prix consigné. Le temps mur est mesuré de bout en bout ; les durées de nœuds et d'occupation des ressources sont rapportées séparément car des opérations peuvent se chevaucher. Toute comparaison candidat/référence se fait dans des conditions consignées, avec dispersion et incertitude (§12.2). Les seuils découlent des mesures Phase 0/1 (§2.4).

## 16. Registre et versionnement

Chaque version comprend identifiant, parent, description, auteur du changement, expériences sources, code/prompt/poids/contrats concernés, licence, provenance, évaluations, critères de promotion, activation, état et rollback. Les anciens workflows sont reproductibles si les dépendances, droits et politiques de conservation le permettent.

### 16.1 Compatibilité et dépréciation (v0.3)

- **Schémas :** changement cassant — champ retiré ou renommé, validation durcie, sémantique d'enum — = majeur ; champ optionnel ajouté = mineur. Le runtime tolère les champs inconnus en entrée et conserve les parseurs des majeurs supportés ; la fenêtre de support (nombre de majeurs) est fixée en politique avant le gel des schémas en Phase 0.
- **Replay :** toute trace retenue reste rejouable pendant sa rétention (§10.2), sauf si l'expiration ou un effacement demandé supprime ou expurge une de ses entrées. Dans ce cas, la trace devient `redacted_by_deletion`, cesse d'être rejouable sur les données supprimées et ne conserve que les métadonnées non sensibles autorisées ; l'effacement prévaut sur la conservation des poids ou artefacts référencés.
- **Capacités :** un nœud est épinglé à une version exacte ; deux majeurs d'une même capacité coexistent dans le graphe actif seulement si leurs schémas d'entrée/sortie diffèrent, sinon le nouveau remplace l'ancien à la promotion.
- **Dépréciation :** déprécié ≠ retiré ; le retrait exige aucun workflow actif référencé, aucune trace rejouable qui l'exige encore, et une note de retrait au registre. Les compétences suivent le cycle du §10.1 et l'interface du §10.3.

## 17. Phasage recommandé

### Phase 0 — Contrats et tâches représentatives

Utiliser le bureau & code comme banc d'essai initial, définir GoalSpec, CapabilityManifest, ArtifactEnvelope et ExperienceRecord, sélectionner tâches, vérificateurs, ressources, confidentialité et permissions. Confirmer que les critères d'évaluation mesurent les fondations réutilisables et ne présentent pas ce banc comme la cible produit.

### Phase 1 — MVP et évolution bornée

Registre, compilation d’objectif, graphe versionné et runtime avec contrats et traces ; rôles préentraînés communication, code et OCR, deux moteurs locaux, parcours bureau/code et interface desktop. Chaque exécution utilise une version stable du graphe ; après une tâche utilisateur éligible, la boucle du §11.7 teste et peut promouvoir une nouvelle version dans le banc. But : prouver la composition, la vérification et une première évolution automatique réversible en CPU seul, puis mesurer le profil GPU.

### Phase 2 — Mémoire et réutilisation

Journal d’expériences, bibliothèque de workflows validés, récupération par préconditions, replay des variantes de routage.

### Phase 3 — Évolution des liens étendue

Étendre les diagnostics de liens et les adaptateurs candidats au-delà de la boucle bornée de Phase 1, avec graphes isolés, évaluations, promotion versionnée et rollback.

### Phase 4 — Spécialistes

Rapports de lacunes récurrentes, intégration ou fine-tuning candidat, droits des données, benchmarks, déploiement contrôlé et surveillance. Le pilote de porte de décision évalue en option une proposition du routeur Tâches et relève les verdicts et les temps de décision (§8.6).

### Phase 5 — Prédicteur d'état/action sur le banc d'essai

États bureau/code explicites, transitions observées, prédiction conditionnée par les actions, planification bornée et replay. Cette phase valide le protocole de prédiction et de vérification sur le banc ; elle ne valide pas la perception spatiale ni l'action dans un monde physique.

### Phase 6 — Évolution intégrée

Apprentissage des routes spécialisées, compétences, nœuds et politiques de mémoire; attribution des gains, détection de dérive et niveaux d’autonomie adaptés aux preuves. Le recours au grand modèle généraliste demeure un secours ponctuel et ne devient pas la norme apprise.

### Post-MVP produit — agent universel local

Après les phases 0 à 6, le produit vise l’agent universel local décrit au §2.1. L’ordre opérationnel (sessions, vault hybride, remplissage de lacunes, rêve hors charge, registre multi-spécialistes) figure dans [product-goal-roadmap-v1.md](../plans/product-goal-roadmap-v1.md). Les domaines s’élargissent par capacités déclarées et preuves. Hors couverture, le système s’abstient ou propose une construction. Il ne garantit pas toute demande.

G1 applique la protection des secrets avant la persistance de session. G2 ajoute le vault et G3 s’appuie sur les reprises locales déjà qualifiées. Pour la mesure à froid du spécialiste image en G5, le chronomètre part de `image_resume`, avec les artefacts déjà vérifiés et une qualification à effectuer, et s’arrête au PNG reçu et vérifié. Le temps complet, accords compris, reste une mesure du parcours à cache vide. [Relevé à cache vide](../../bench/results/image-mcp-cold-cache-v1.json)

G7 à G9 étendent le registre et les parcours d’interaction à la voix dans l’ordre transcription et analyse d’enregistrements parlés, lecture à la demande, puis demandes vocales. La qualification de chaque profil repose sur le contrat du §7.3.1. [Jalons voix locale](../plans/product-goal-roadmap-v1.md#prochains-jalons--voix-locale)

G10 qualifie les URL dans la conversation et la lecture HTTPS publique hors du bac. G11 qualifie les connexions HTTPS par registre d’adaptateurs avec le coffre G2 et le registre G5. [Clôture G10](../plans/product-goal-roadmap-v1.md#clôture-g10-sur-windows) · [Clôture G11](../plans/product-goal-roadmap-v1.md#clôture-g11-sur-windows)

### Piste séparée — modèle du monde spatial et agent incarné

Un plan distinct traitera la perception spatiale, les états dynamiques, la prédiction conditionnée par les actions et l’interaction avec des environnements simulés puis réels selon des garanties adaptées au risque. Cette piste n’est pas couverte par la Phase 5. Elle ne partage pas le calendrier produit post-MVP.

Ces phases réduisent les risques. Elles ne définissent pas de calendrier. Le détail opérationnel (entrée, sortie, validation, risques, rollback par phase) figure dans le [plan de développement](../plans/development-plan.md). Le bureau & code reste un banc d’essai. La cible produit est l’agent universel local (§2.1). La piste spatiale reste séparée.

## 18. Critères d’acceptation de l’architecture

- Nœuds, liens, workflows et environnements ont des contrats versionnés.
- Une trace explique le chemin de chaque tâche.
- Une inférence ne devient pas silencieusement une réussite observée.
- Boucles, ressources et actions sont bornées.
- Erreurs de capacité, lien, planification et environnement sont distinguées.
- Un graphe candidat est évalué sans changer l’actif.
- Toute promotion est versionnée et réversible.
- Une lacune est étayée par répétition et mesure discriminante.
- Confidentialité et droits d’usage sont documentés.
- Environnement de départ et autonomie sont décidés avant les actions réelles.

## 19. Décisions — état v0.21

Décisions enregistrées pour le prototype, le banc d'essai et le but produit :

1. **Banc d'essai initial :** bureau & code local, poste Windows d'abord, en environnement isolé. La référence est une application de notes créée exprès, qui annonce une sauvegarde sans la persister ; le parcours code corrige le bug et le parcours bureau vérifie la persistance après réouverture. Une application de gestion de tâches dont le filtre « À faire » affiche aussi les tâches terminées sert de variante indépendante pour mesurer le transfert (§12.3). Le banc valide les fondations. La cible produit est l’agent universel local (§2.1, §2.5, §17). La piste spatiale est séparée.
2. **Hébergement, inférence et recours aux grands modèles :** mono-poste local par défaut ; Rbitnet prioritaire pour les GGUF compatibles, autres moteurs par adaptateur pour les formats, architectures ou modalités non couverts (§6.2). La route nominale privilégie les petits modèles spécialisés, outils et solveurs. Un grand modèle généraliste est réservé à un secours ponctuel après abstention ou insuffisance documentée des capacités spécialisées. Tout appel distant requiert un `RemoteInferenceGrant` préalablement approuvé et limité au fournisseur/endpoint, à la finalité, aux catégories de données, à une expiration et à un budget ; chaque invocation est contrôlée et journalisée en métadonnées minimales, hors contenu. Un grant n'autorise que les appels couverts et n'autorise pas l'entraînement partagé. Le speculative decoding avec grand vérificateur est hors MVP. La compatibilité effective, la qualité et le budget mémoire sont mesurés en Phase 0/1.
3. **Autorisations MVP :** autonomie dans la copie du banc jetable sous conditions de confinement et de restauration vérifiées, y compris les suppressions R1 ; tests de projet réel dans une copie isolée ; diff exact soumis à validation avant application au projet, suppressions et déplacements explicitement approuvés au cas par cas ; accord avant chaque téléchargement de dépendance ; bureau réel exclu. Les permissions sont appliquées hors modèle (§13.5.1-13.7).
4. **Modèles :** version exacte, digest, quantization et évaluation liée exigés au manifeste (§6.1). Licences et provenance des jeux d'entraînement restent à documenter par modèle.
5. **Communication et superviseur :** MCP intra-système par défaut, A2A différé à la bordure externe ; chaque workflow s'exécute sur une version stable du graphe, tandis que des versions candidates peuvent évoluer de façon bornée dès le MVP (§6.1, §8.4, §11.7).
6. **Mémoire et données utilisateur :** pour l'évolution locale, banc synthétique admissible et résultats techniques minimisés par défaut ; contenus réels et dérivés seulement après accord explicite par projet et catégorie (§10.4). La variante de transfert et les secrets sont exclus. Contenu utilisateur et dérivés sont effaçables et filiationnés ; journal d'audit append-only limité aux métadonnées minimales et au résultat d'effacement, sans contenu utilisateur ni empreinte de celui-ci. Aucun usage dans un entraînement partagé sans accord explicite et spécifique ; l'accord local ne donne aucun droit réseau ni d'accès supplémentaire. **Valeurs par défaut décidées :** durées par classe et sauvegarde locale chiffrée quotidienne (§10.2, §10.5). **À définir en Phase 0 :** mécanismes et critères de preuve ; **à valider avant la fin de Phase 2 :** tests bout-en-bout de suppression et de non-résurrection.
7. **Validation :** jeux du §12.1, cas réservés anti-contamination, baseline fixe et baseline humaine.
8. **Promotion :** paliers du §11.6 ; fiabilité prioritaire et critères critiques jamais compensés par une moyenne. À fiabilité démontrée comparable, temps et ressources servent de départage. Les seuils et la méthode de preuve se fixent par domaine après mesures (§11.5, §11.7).
9. **Compétences exécutables :** API testée après pratiques répétées, cycle de vie complet (§10.1) ; limites d'écriture et de revue à fixer par classe de risque.
10. **Capteurs du premier prototype :** état bureau/code explicite (accessibilité/DOM, fichiers, git, processus), complété par un modèle de vision/OCR préentraîné sur un second moteur local. L'OCR ne constitue pas l'unique vérificateur (§2.6, §9.7). **Angle mort connu :** couverture native Windows (UI Automation, focus, UAC) non sourcée, à vérifier en Phase 0.
11. **Évolution automatique :** dès la Phase 1, candidats limités à la recomposition des capacités existantes ; essais lancés en arrière-plan après chaque tâche utilisateur éligible, sans déclenchement récursif par les essais, avec budgets configurables, critères de fiabilité et promotion automatique limitée au banc R0/R1. Jamais de mutation directe du graphe actif ; versionnement et retour arrière obligatoires (§11.7).
12. **Classes de risque :** taxonomie R0-R3 (§13.6), attribution structurelle depuis les manifestes, classe inconnue = R3 ; les grants ne peuvent autoriser que l'inférence distante dans leur périmètre (§13.7).
13. **Coût :** métrique primaire = temps mur par tâche sur matériel figé au repos ; secondaires = temps GPU actif, tokens et montant pour l'inférence distante ; seuils dérivés des mesures Phase 0/1 (§15.1).
14. **Stockage :** racine de données unique ; journal d'audit append-only limité aux métadonnées minimales et jamais supprimé ; contenus, identifiants dérivés, artefacts et mémoires effaçables même s'ils sont référencés ; sauvegarde locale chiffrée quotidienne conservée 7 jours, inclusion des données réelles sur accord séparé par projet et catégorie, propagation aux sauvegardes avant confirmation et garde à la restauration (§10.2, §10.5).
15. **Approbations :** échéance = pause typée, jamais d'auto-approbation ; « décision signée » = entrée append-only chaînée par digests, signature cryptographique optionnelle (§8.5).
16. **Harness bureau :** profil Windows Sandbox durci sans réseau, presse-papiers, audio/vidéo ni dossiers hôtes inscriptibles ; échange de fichiers par préparation/import et export contrôlés. La compatibilité et le recours à un checkpoint de VM restent à mesurer en Phase 0 (§12.2, §19.10).
17. **Ressources des modèles :** gestion globale RAM/VRAM tenant compte des poids, caches, allocations temporaires et marges ; chargement, utilisation et déchargement sûrs via les adaptateurs ; éviction des seuls modèles inactifs aux points sûrs (§6.2, §8.5). La migration fine entre RAM et VRAM est facultative et mesurée. L'échec d'admission est `residency_unavailable`.
18. **Interface MVP :** application desktop avec conversation, progression, résultats et graphe consultable de façon interactive ; inspection, historique, pause/reprise de l'évolution et retour arrière, sans édition manuelle du graphe (§2.6).
19. **Matériel MVP :** parcours et évolution utilisables en CPU seul ; deuxième campagne sur la machine équipée de la RTX 4080 SUPER 16 Go, en activant le GPU là où les moteurs le prennent en charge. Configuration minimale chiffrée et limites par défaut établies après mesure (§2.6, §12.2).
20. **Porte de décision outillée (v0.17)** — Le routage déterministe est actif par défaut. Sur le banc Tâches, le Path A de `akasha-model==0.3.0` (MIT) peut évaluer en option une proposition avec `Choice`, `Score` et `Noul` et journaliser le verdict `ready`, `abstain` ou `blocked`. L’hôte applique les autorisations et les approbations. La promotion suit les paliers et critères du §11.6 (§8.6, §17).
21. **Exécution image et MCP (v0.18)** — Le parcours CPU emploie une logique commune de découverte, qualification et validation PNG et un backend isolé propre à Windows ou Linux. L’opérateur donne les accords du moteur et des poids séparément. Le client MCP suit puis reprend sa tâche avec le même identifiant et récupère le verdict et le PNG vérifié (§6.3, §8.7, §11.8).
22. **But produit (v0.19)** — Agent universel local à domaines croissants avec abstention, organisé en sessions portant des projets. G1 filtre la persistance de session dès l’entrée. G2 ajoute le vault hybride avec keystore OS et handles applicatifs. La piste spatiale suit son propre plan (§2.1, §10.6, §17). [Feuille de route](../plans/product-goal-roadmap-v1.md)
23. **Voix locale (v0.20)** — Transcription et synthèse sont des capacités optionnelles avec contrats versionnés. Le premier profil de chaque capacité est choisi après qualification en français sur CPU. Le STT alimente l’analyse d’enregistrements et les demandes vocales. Une demande vocale rejoint le planificateur après l’envoi du brouillon par l’utilisateur (§7.3.1, §17).
24. **Collecte web et services tiers (v0.21)** — Une URL peut être réutilisée pendant la session courante. La collecte HTTPS publique passe par un accord ponctuel et un processus hors du bac. Les services tiers suivent un contrat d’adaptateur versionné, avec permissions par opération et résolution des secrets hors modèle (§5.3, §8.8, §10.6, §13.7, §17).

## 20. Glossaire

- **Capacité :** fonction d’un modèle, outil, solveur, mémoire ou adaptateur.
- **Nœud :** instance versionnée d’une capacité dans le graphe.
- **Lien :** relation de données ou de contrôle entre deux nœuds.
- **Workflow :** graphe d’exécution pour une tâche.
- **Compétence :** workflow ou programme vérifié avec préconditions définies.
- **Graphe actif :** version utilisée par le runtime.
- **Graphe candidat :** copie isolée pour les essais.
- **État du monde :** meilleure estimation datée d’un environnement avec provenance et incertitude.
- **Modèle du monde :** modèle qui prédit l’évolution d’un état sous l’effet du temps ou d’actions.
- **GapReport :** dossier de preuve sur une capacité manquante potentielle.
- **Promotion :** activation versionnée d’un changement ayant satisfait les critères.
- **Rollback :** restauration d’une version antérieure.
- **Classe de risque :** niveau R0-R3 d’une action, attribué structurellement depuis les manifestes (§13.6).
- **Lease d’environnement :** droit exclusif temporaire d’un objectif sur un adaptateur mono-instance (§8.5).
- **Condition de réussite :** prédicat typé de l’ensemble fermé, évalué sur l’état vérifié (§5.4).
- **Journal d’audit :** journal append-only chaîné de métadonnées minimales sur les décisions, autorisations et résultats d'effacement ; il exclut les contenus utilisateur, les artefacts et les empreintes de ces contenus (§8.5, §10.2).
- **Résidence d'un modèle :** état et emplacement observables de ses ressources, éventuellement réparties entre stockage, RAM et GPU ; un mappage n'implique pas que toutes les pages soient en RAM (§6.2).
- **Gestionnaire de ressources :** composant Akasha qui coordonne les budgets, l'admission, l'utilisation et la libération entre adaptateurs, selon les capacités réellement exposées par chaque moteur (§6.2).
- **Porte de décision** — Composant sans effet de bord qui évalue en une passe un appel ou un choix de routage et produit `ready`, `abstain` ou `blocked` (§8.6).

## Annexe A — Exemple de tâche

**Demande :** « Place la tasse bleue dans la zone marquée et dis-moi si elle y est bien. »

1. Communication extrait objet, cible et demande de confirmation.
2. Le compilateur crée l’objectif et ses permissions.
3. La perception estime tasse, zone, coordonnées, repères et confiance.
4. Le vérificateur d’état évalue si la pose est assez fiable.
5. Le modèle du monde prédit des actions candidates et leurs incertitudes.
6. Le planificateur choisit une action selon contraintes et limites.
7. L’adaptateur exécute une action bornée et reçoit une observation.
8. Le système compare résultat et prédiction, puis replannifie.
9. Le vérificateur confirme le succès depuis l’état observé.
10. La communication distingue action faite et résultat confirmé.
11. La trace peut alimenter une évaluation ultérieure selon la politique de confidentialité.

**Diagnostic :** si la pose est correcte mais transmise dans le mauvais repère, proposer d’abord une conversion ou un lien. N’entraîner un nouveau modèle spatial qu’après avoir exclu cette incompatibilité.

## Annexe B — Questions obligatoires pour toute évolution

1. Quel problème observé est résolu?
2. Quelle preuve montre sa récurrence?
3. Où dans le graphe apparaît-il?
4. Un routage, lien, adaptateur, workflow ou outil existant suffit-il?
5. Le candidat a-t-il des entrées et sorties vérifiables?
6. Quel protocole le compare à la référence?
7. Quelles règles de risque, données et coût s’appliquent?
8. Comment surveiller le changement et l’annuler?

Une proposition sans réponse testable reste une hypothèse, pas une capacité active.
