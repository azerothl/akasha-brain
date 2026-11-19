# Akasha Brain — Plan de développement

**Statut :** plan v0.20, issu de la spécification v0.20\
**Date :** 2026-11-18\
**Banc d'essai initial :** bureau & code local (poste Windows d'abord, environnement isolé). La cible produit est l’agent universel local à domaines croissants. La piste spatiale est séparée.

## Objectif

Construire progressivement le système décrit par la [spécification d'architecture](../architecture/brain-system-spec.md), en prouvant à chaque phase une capacité mesurable contre une baseline fixe, avant d'ajouter la suivante. Fondements et limites : [notes de recherche](../research/research-notes.md).

## État livré au 18 novembre 2026

Les phases 0 à 6 ont leurs preuves de qualification sur le banc bureau et code Windows. L’application desktop expose la conversation, les tâches et l’évolution intégrée. Les extensions livrées depuis cette qualification comprennent la planification des demandes libres, le résumé détaillé du code, l’accès agent via MCP et la récupération de capacités déclarées. [Audit et extensions livrées](phase6_status.md)

Le parcours image dispose d’une exécution commune sur CPU avec deux backends headless, Windows Sandbox et Bubblewrap sous Linux. La conversation Windows, la CLI et MCP utilisent la même chaîne de découverte, d’accord par artefact, de qualification et de validation du PNG. Le serveur MCP a été vérifié avec le moteur déjà qualifié et à cache vide. Les deux rejeux à cache vide ont exercé des accords distincts et la reprise du selfie sous le même identifiant. Les réponses d’accord étaient simulées dans la CLI, avec des sources locales pour les artefacts approuvés. [Rejeux MCP](../../bench/results/image-mcp-headless-v1.json) · [Cache vide](../../bench/results/image-mcp-cold-cache-v1.json)

La qualification Linux publiée couvre les images en CLI et MCP sous Ubuntu WSL2 avec un compte non privilégié. Les parcours Notes, projet et interface desktop ont été qualifiés sur Windows.

Les jalons post-MVP **G1 à G6 sont clôturés sur `main`**. La révision finale `02b0447` a passé **297 tests en 2 min 17 s** sur les suites `tests` et `contracts`. [Clôture et résultats](product-goal-roadmap-v1.md#clôture-sur-main)

## Périmètre et critères du MVP

Le MVP est une application desktop Windows d'abord, composée de deux parcours et d'une évolution automatique limitée au banc isolé. Le périmètre est décrit dans la spec §2.6 et §11.7. La cible produit post-MVP est l’agent universel local. La piste spatiale est séparée.

- **Banc de référence — notes :** créer une petite application réelle et son dépôt avec un bug volontaire : « Enregistrer » affiche la note et annonce le succès, mais ne la persiste pas ; après fermeture et relance, la note a disparu. Le langage, l'interface, le stockage et le détail de l'implémentation fautive sont choisis en Phase 0 ; état initial, données et vérificateurs sont figés et restaurables.
- **Vérifications notes :** reproduire l'échec, corriger dans le bac, puis vérifier que la note réapparaît avec son contenu exact après arrêt et relance. Les non-régressions vérifient deux notes distinctes, dont une avec accents et plusieurs lignes. Présenter diff et résultats ; les tests et l'oracle sont protégés contre les modifications du candidat.
- **Variante de transfert — tâches :** deux tâches initiales, « Préparer la réunion » à faire et « Envoyer la facture » terminée. Le bug fait apparaître les deux sous le filtre « À faire ». Le test de régression attend seulement la première ; les non-régressions attendent seulement la seconde sous « Terminées », puis les deux sous « Toutes », sans changer leurs états. Provenance, technologies et détail de l'implémentation fautive sont choisis en Phase 0.
- **Indépendance du transfert :** la variante et ses vérificateurs sont séparés des jeux d'optimisation. Pendant la construction et la promotion des candidats, le modèle et le graphe candidat ne reçoivent ni le dépôt ni les détails du scénario de transfert présents dans ces documents. Lors de l'évaluation, figer la version active, isoler les entrées nécessaires et désactiver la réutilisation des résultats pour l'auto-évolution. Signaler toute exposition connue et renouveler la variante si elle sert à ajuster le système.
- **Parcours bureau :** ouvrir l'application de notes corrigée, saisir et sauvegarder une note, fermer puis rouvrir l'application et vérifier la persistance ; sur la variante, utiliser les filtres et vérifier les éléments visibles. Le modèle de vision/OCR est réellement invoqué pour une observation utile ; l'état persisté et les éléments visibles sont vérifiés par des contrôles indépendants adaptés au stockage ou à l'accessibilité. L'OCR ne constitue pas l'unique preuve de réussite.
- **Modèles et moteurs :** au moins deux petits modèles préentraînés GGUF compatibles avec Rbitnet pour la communication et le code, plus un modèle préentraîné léger de vision/OCR exécuté par un second moteur local. Versions, formats, licences, périphériques et résultats sont épinglés et vérifiés ; aucun entraînement automatique des poids n'est requis dans le MVP.
- **Matériel :** les deux parcours, les trois rôles et l'évolution fonctionnent d'abord en CPU seul : GPU désactivé pour l'inférence et les essais du système, avec configuration et mesures consignées ; l'affichage Windows peut rester accéléré. Relever temps, RAM, erreurs et réussite. Rejouer ensuite les mêmes scénarios sur la machine équipée d'une RTX 4080 SUPER 16 Go, en vérifiant qu'au moins un modèle compatible utilise effectivement le GPU et en indiquant les composants restés sur CPU. Les minima RAM/CPU/stockage et budgets par défaut sont fixés après mesure.
- **Interface :** conversation et lancement des tâches, progression, modifications et résultats vérifiés ; graphe visuel consultable avec zoom/déplacement, inspection des capacités et connexions, chemin exécuté, versions actives et candidates, historique, état et ressources observables. L'utilisateur peut suspendre/reprendre l'évolution, revenir à une version antérieure et consulter, accorder ou révoquer la réutilisation locale des données par projet et catégorie ; le graphe ne s'édite pas manuellement dans le MVP.
- **Évolution :** à la fin de chaque tâche utilisateur éligible selon la politique de confidentialité, succès ou échec, démarrer des essais en arrière-plan sans attendre l'inactivité, dans les limites configurables de CPU, RAM, GPU utilisé, durée, concurrence et nombre d'essais. Les essais internes ne déclenchent pas de nouveaux essais. Afficher attente, progression, motif d'arrêt et éventuelle promotion ; une tâche interactive reprend la priorité aux points sûrs. Si un budget manque, conserver une attente explicite plutôt que dépasser la limite.
- **Données de l'évolution locale :** par défaut, utiliser le banc synthétique de référence admissible et les résultats techniques minimisés, jamais la variante de transfert. Les contenus réels et leurs dérivés ne sont réutilisables qu'après accord explicite par projet et par catégorie ; les secrets sont exclus. L'accès nécessaire pour exécuter la tâche n'est pas un accord pour réutiliser ses contenus, et l'accord local n'autorise ni accès supplémentaire ni envoi distant ni entraînement partagé (§10.4).
- **Conservation et sauvegarde :** temporaires jusqu'à la fin de la tâche, résultats techniques minimisés 90 jours, contenus réels autorisés et dérivés 30 jours, captures réelles et OCR associé 7 jours ; échéances à partir de la création, sans renouvellement par consultation. Sauvegarde chiffrée locale quotidienne, conservée 7 jours ; copie des contenus réels seulement sur accord distinct par projet et catégorie. L'effacement et la restauration respectent les échéances et interdictions (§10.2, §10.5).
- **Autorisations d'action :** dans le banc jetable restaurable et confiné, permettre sans approbation par action les lectures, modifications, suppressions et tests de la copie de travail, avec références protégées. Pour un projet réel ouvert, préparer et tester dans une copie isolée, puis présenter le diff exact avant toute application au projet : validation obligatoire, accord explicite au cas par cas pour chaque suppression ou déplacement et nouvelle validation si le projet a changé. Tests sans réseau ni secrets et sans écriture sur le projet d'origine ; chaque téléchargement de dépendance nécessite un accord préalable. Le bureau réel reste hors périmètre (§13.5.1-13.7).
- **Changements admissibles :** produire et tester des variantes de workflow en recomposant les capacités et liens déclarés, sur une copie versionnée isolée, sans modifier les permissions, créer de nouvelle implémentation de capacité ni entraîner ou créer de modèle. Le parcours code reste autorisé à modifier le dépôt du banc. L'activation automatique ne concerne que le banc R0/R1 ; chaque exécution garde la version démarrée et le retour arrière reste possible.
- **Critère de promotion :** aucune violation critique ni régression interdite ; privilégier la fiabilité démontrée. À fiabilité démontrée comparable selon un protocole et des seuils fixés après les mesures initiales, départager par temps et ressources. Les tests de développement/validation sont distincts de la variante réservée au transfert, qui ne sert pas à optimiser les candidats à répétition. Si les résultats sont insuffisants ou ambigus, conserver la version active.

La sortie du MVP doit démontrer les deux parcours sur CPU, une évolution automatiquement promue sur preuves dans le banc et un retour arrière exercé, la vue du graphe et ses commandes, les deux moteurs locaux et une campagne GPU documentée. Si aucun candidat ne satisfait les critères de promotion, l'absence d'une promotion démontrée est rapportée comme critère encore ouvert ; les résultats ne sont pas fabriqués.

## Critères de réussite globaux

- Chaque phase se termine par une validation **par exécution** (tests, état final), jamais par un juge LLM seul.
- Toute promotion suit les paliers replay → shadow → exposition limitée → actif, avec rollback vers la version parent (spec §11.6, §16).
- Aucun seuil chiffré n'est figé avant les mesures locales de la Phase 0/1 sur le matériel cible.
- Une trace complète explique chaque tâche : objectif, graphe et versions, nœuds/liens, vérifications, coût, latence, erreurs typées (spec §8.3, §18).

## Hypothèses et décisions de départ

- Runtime : graphe explicite compilé et validé, checkpointer durable SQLite en mono-poste, interruptions pour l'approbation humaine, retry bornée aux erreurs transitoires (spec §8.4).
- Contrats : JSON Schema 2020-12 versionné, noyau d'outil MCP, permissions normatives séparées des hints (spec §6.1).
- Inférence : Rbitnet prioritaire pour les modèles GGUF compatibles et évalués ; autres moteurs par adaptateur pour les formats, architectures ou modalités non couverts (spec §6.2). Un gestionnaire global coordonne les budgets et les cycles de vie selon les capacités de chaque moteur. La route nominale privilégie les petits modèles spécialisés, les outils et solveurs ; un grand modèle généraliste est uniquement un secours ponctuel, s'il est autorisé par la politique de déploiement et après insuffisance documentée des capacités spécialisées. Son invocation est visible, justifiée, journalisée et soumise aux règles de confidentialité. Sur le banc Tâches, le routage déterministe est actif par défaut. La porte de décision facultative évalue la proposition et journalise le verdict (spec §8.6).
- Sandbox déclaré au manifeste, egress refusé par défaut, secrets hors sandbox (spec §13.5).

## Phase 0 — Contrats et tâches représentatives

**Entrée :** décisions §19 v0.16 enregistrées pour le banc d'essai initial.

**Livrables :**

- Schémas versionnés `GoalSpec`, `CapabilityManifest`, `ArtifactEnvelope`, `ExperienceRecord`, `SuccessPredicate` (spec §5-6, §6.1, §5.4) ; taxonomie R0-R3 encodée dans les manifestes et le GoalSpec (spec §13.6) ; provenance et filiation des données ; périmètre de consentement explicite ; distinction de schéma entre journal d'audit minimal et contenus effaçables ; validateur d'entrée/sortie au runtime ; bibliothèque fermée de prédicats de réussite par adaptateur ; erreurs typées.
- Définir avant collecte durable les contrats versionnés de rétention et sauvegarde appliquant les valeurs décidées (§10.2, §10.5) : horodatage, filiation, échéance la plus restrictive, consentement de sauvegarde séparé et statut de suppression. Concevoir chiffrement, cycle de vie et récupération des clés, suppression ou effacement cryptographique vérifiable des copies, stockage protégé des marqueurs et barrière de restauration. Fixer les critères de preuve, les erreurs et l'état en attente si une copie ne peut être traitée.
- Définir et versionner la politique d'évolution locale : catégories de contenus et dérivés, identifiant de projet, finalité, accord explicite, statut, échéance/rétention et révocation. Par défaut : référence synthétique admissible et champs techniques minimisés seulement ; variante réservée, contenus réels non autorisés et secrets exclus (spec §10.4).
- Définir le contrat d'autorisation hors modèle : confinement et restauration vérifiables, références protégées, exception R1 aux suppressions uniquement si ses conditions sont prouvées ; périmètre de projet, proposition et approbation liés, accord explicite par suppression ou déplacement, contrôle d'état juste avant application ; demande préalable pour chaque téléchargement et interdiction d'action sur le bureau réel. Prévoir des tests de refus et d'échec (spec §13.5.1-13.7).
- Politique de sandbox Windows vérifiable : réseau, presse-papiers, audio/vidéo et imprimantes désactivés ; aucun dossier hôte inscriptible ; import/export via une zone contrôlée. Évaluer vGPU et Protected Client selon la compatibilité des tâches.
- Schéma `RemoteInferenceGrant` : fournisseur/endpoint, finalité, catégories de données, expiration, budget, approbateur et révocation ; essais de réussite dans le périmètre et de refus pour fournisseur, finalité ou données hors périmètre, budget dépassé, grant expiré ou révoqué.
- Créer l'application de notes avec le bug de sauvegarde décrit ci-dessus et préparer l'application de tâches avec le bug du filtre « À faire » (§12.3). Pour chaque scénario : figer le dépôt et l'état initial, écrire le test de régression et les non-régressions, vérifier que le premier échoue sur la version fautive et réussit sur une correction de référence qui n'est pas fournie à l'agent. Chaque essai repart de l'état figé ; les tests et vérificateurs sont hors de portée d'écriture du candidat. Isoler la variante pendant l'optimisation, y compris les descriptions présentes dans la spec et le plan. Consigner le protocole, les cas réservés et une baseline humaine chronométrée (spec §2.6, §12.2-12.3).
- Sélection et vérification en CPU seul d'au moins deux petits spécialistes GGUF préentraînés pour la communication et le code, ainsi que d'un modèle préentraîné de vision/OCR sur un second moteur local ; versions, modèles, quantizations, licences et capacités épinglées. Mesurer réussite par exécution et qualité du diff. Le nombre initial de trois essais sert au profilage ; augmenter l'échantillon selon la dispersion avant de conclure à un gain ou de fixer un seuil.
- Mesurer Rbitnet et son adaptateur candidat : chargement à froid, appel à chaud, changement et déchargement de modèle, reprise après échec, RAM/VRAM crêtes, concurrence et saturation ; distinguer valeurs mesurées, estimées et indisponibles. Inclure cache de contexte, allocations temporaires, autres processus et réserves système. Comparer au workflow fixe de référence, sur un protocole reproductible et des conditions consignées (spec §6.2, §12.2).
- Inventorier les capacités effectivement exposées par Rbitnet (serveur/proxy, API Rust, chargement, déchargement, métriques et placement hybride) ; séparer les fonctions observées des travaux à développer. Sélectionner le moteur local de vision/OCR et son modèle préentraîné, avec versions, licences, ressources et exécution CPU consignées. Définir le contrat minimal commun des adaptateurs. Les transferts fins RAM/VRAM sont une optimisation facultative à justifier par mesure.
- Vérification de l'observation Windows (accessibilité, focus, UIA) et des canaux désactivés ; tester l'import/export contrôlé. Trancher le harness : Windows Sandbox jetable vs checkpoint de VM selon la tâche (spec §12.2).

**Sortie :** baseline fixe simple (localisation → réparation → validation) mesurée ; aucune action réelle hors sandbox ; schémas gelés en v0 ; métrique de coût fixée (spec §15.1) et premiers seuils dérivés des mesures, consignés avec leur protocole.

**Risques / rollback :** sans objet (gel de schémas) ; un schéma instable se corrige ici, pas en Phase 1.

## Phase 1 — Parcours bureau/code et évolution bornée (MVP)

**Entrée :** Phase 0 verte.

**Livrables :**

- Registre de capacités (annoncé vs évalué), compilateur d'objectif, runtime à graphe versionné avec contrats, traces mappées OpenTelemetry via couche épinglée, rôles spécialisés et outils déterministes ; chaque exécution conserve une version stable du graphe.
- Adaptateur code (recherche, vue de fichier bornée, édition gardée, exécution de tests) et adaptateur bureau en environnement isolé, avec observation par accessibilité et vision/OCR selon la tâche.
- Application desktop : conversation, progression, résultats et diff ; graphe interactif de consultation, chemin exécuté, statut actif/candidat, versions et historique ; pause/reprise de l'évolution et retour à une version précédente ; consultation, accord et révocation de la réutilisation locale par projet et catégorie, avec demande de suppression.
- Boucle d'évolution du §11.7 : démarrage en arrière-plan après chaque tâche utilisateur éligible, sans déclenchement récursif par les essais, budgets configurables, priorité aux tâches interactives ; recomposition bornée de capacités existantes, évaluations isolées et promotion automatique limitée au banc R0/R1 si la fiabilité prioritaire et les critères critiques sont satisfaits.
- Appliquer la politique de données avant toute conservation ou réutilisation pour l'évolution : sans accord, essais sur le banc synthétique et résultats techniques minimisés uniquement ; avec accord, seulement projet et catégories autorisés, jamais secrets ou variante réservée. Révocation : bloquer les travaux en attente, arrêter les essais aux points sûrs et empêcher la promotion de candidats fondés sur des données devenues interdites. Un accord local ne modifie ni les permissions d'exécution ni les grants distants.
- Vérifier : tâche réelle sans accord puis essai synthétique, absence de contenu brut et dérivé dans les données d'évolution par défaut, accord limité à une catégorie et un projet, refus inter-projets, révocation d'un essai en attente ou en cours, demande de suppression de copies contrôlées, et exclusion de la variante de transfert. Les résultats techniques sont traités comme potentiellement sensibles, pas présumés anonymes.
- Mettre en œuvre les échéances configurables, la suppression anticipée, la sauvegarde locale chiffrée automatique quotidienne et sa fenêtre glissante de 7 jours ; aucune copie de contenu réel sans accord de sauvegarde séparé par projet et catégorie. Conserver les marqueurs hors des sauvegardes restaurées, bloquer l'exposition si leur intégrité ne peut être vérifiée et empêcher la restauration de données expirées ou supprimées ; présenter les suppressions en attente et leur motif. Ne pas toucher aux fichiers originaux ni prétendre effacer les exports externes.
- Vérifier notamment les échéances de 90/30/7 jours depuis la création, l'échéance la plus proche des dérivés, l'absence de prolongation par sauvegarde, les deux accords distincts, les échecs de suppression, l'indisponibilité des marqueurs et le refus de réintroduire les données à la restauration. Les essais utilisent des données de test.
- Clés d'idempotence sur tout effet de bord ; contrôle d'autorisation hors modèle, approbation humaine sur les actions destructives hors exception strictement confinée au bac (§13.6).
- Leases exclusifs par environnement mono-instance, sérialisation des objectifs sur l'adaptateur bureau, échéances d'approbation et journal d'audit chaîné qui exclut prompts, contenu utilisateur, artefacts et empreintes de ces données (spec §8.5, §10.2).
- Traces et checkpoints contenant des données utilisateur rangés dans des stockages effaçables ; leur accès pour la tâche ne vaut pas autorisation de réutilisation pour l'évolution. Mécanisme d'effacement immédiat distinct du journal d'audit append-only minimal ; ne pas supprimer les fichiers du projet d'origine lors de la suppression des copies Akasha.
- Livrer le parcours de projet réel : copie isolée, tests automatiques sans réseau ni secrets ni écriture dans l'original, aperçu du diff et des résultats, validation de la proposition avant application, accord distinct explicite au cas par cas pour suppressions et déplacements, contrôle juste avant application et nouvelle proposition si changement détecté. Signaler tout échec ou état partiel ; aucune commande de test n'est exécutée sur l'hôte par cette autorisation.
- Vérifier les refus : absence d'isolation ou de restauration, accès à une référence protégée, tentative de suppression hors copie jetable sans accord explicite, diff non approuvé ou devenu obsolète, suppression ou déplacement sans accord spécifique, téléchargement non approuvé, test demandant réseau ou secrets, et tentative de contrôle du bureau réel. Vérifier aussi la suppression confinée autorisée et le bon fonctionnement des parcours de test.
- Réseau désactivé dans la sandbox ; appels d'inférence distante seulement via le courtier hôte et un `RemoteInferenceGrant` valide ; audit minimal de chaque invocation sans prompt, sortie ni empreinte de contenu.
- Pour chaque téléchargement de dépendance, afficher version et source et obtenir un accord préalable ; le résolveur hôte alimente un cache vérifié, puis l'installation s'effectue hors ligne dans le bac jetable. Refus ou téléchargement supplémentaire : arrêter ou demander un nouvel accord.
- Intégrer Rbitnet par un adaptateur pour les GGUF retenus et un second adaptateur vers le moteur local sélectionné pour un modèle non couvert. Le gestionnaire de ressources fournit admission, préparation, état, libération et déchargement sûr ; il arbitre RAM/VRAM et concurrence sans interrompre une requête active (spec §6.2). Aucun moteur neuf ni déplacement dynamique partiel des poids n'est exigé pour le MVP.
- Vérifier les chemins modèle compatible/incompatible, moteur indisponible, budget insuffisant, appels concurrents, erreur au chargement et libération ; journaliser les mesures disponibles sans substituer zéro à une valeur inconnue. Un autre backend déclaré ne devient pas un recours distant ou un grand modèle sans la politique et le grant requis.

**Sortie :** critères du MVP ci-dessus satisfaits : régression et non-régressions de l'application de notes vérifiées en CPU seul, parcours bureau avec OCR et contrôle indépendant de persistance, deux moteurs locaux avec modèles préentraînés, graphe consultable et commandes, une évolution automatiquement promue sur preuves et retour arrière exercé, variante du filtre de tâches évaluée indépendamment, parcours de projet réel et autorisations vérifiés, puis campagne GPU documentée. Échecs attribuables (capacité, lien, plan, environnement). Toute preuve manquante, y compris absence de candidat promouvable ou de modèle compatible, laisse le critère concerné ouvert.

**Risques / rollback :** retry ré-exécutant un effet de bord → clés d'idempotence et retry restreinte aux transitoires ; rollback = graphe parent versionné ; approbation en attente bloquant un objectif → pause typée `approval_expired`, jamais d'auto-approbation (spec §8.5).

## Phase 2 — Mémoire et réutilisation

**Entrée :** journal d'expériences de la Phase 1 suffisant.

**Livrables :**

- Stockage d'expériences effaçable et extraction sélective ; journal d'audit minimal append-only séparé ; mémoire de travail paginée et faits sémantiques bi-temporels (spec §10.1-10.2).
- Bibliothèque de workflows validés ; retrieval combiné (récence/importance/pertinence, graphe en complément).
- Benchmark A/B du filtre dur de préconditions contre la similarité seule — hypothèse Akasha, tranchée par la mesure.
- Filiation des sources et dérivés ; suppression vérifiable de bout en bout dans les mémoires, index, artefacts, traces, sauvegardes et compétences ; trace expurgée non rejouable si un input a été effacé. Éprouver plusieurs générations de sauvegardes, la reprise après échec, la suppression de clés et de leurs copies si cette méthode est retenue, et la non-résurrection après restauration ; ne confirmer la suppression qu'après vérification de toutes les copies contrôlées.
- Registre local privé au format d'annuaire versionné (pas de dépendance au registre public en preview).

**Sortie :** gain de réutilisation mesuré sans régression de sécurité ; politique de rétention active, utilisation bloquée et suppression engagée sans délai hors courbe d'oubli ; confirmation après vérification.

**Risques / rollback :** consolidation perdant de l'information → évolution versionnée des notes ; rollback = désactivation de la mémoire, retour au registre parent.

## Phase 3 — Évolution des liens étendue

**Entrée :** replay déterministe prouvé sur les traces des Phases 1-2.

**Livrables :**

- Étendre la boucle bornée du MVP : diagnostics de liens, adaptateurs et conversions candidats construits sur graphe candidat isolé (nouvelle version compilée, jamais de mutation de l'actif).
- Promotion par paliers (replay → shadow → limité → actif), décision signée, surveillance post-promotion.
- Vérificateur de transition en garde supplémentaire avant action irréversible — jamais gate unique.

**Sortie :** au moins une évolution de lien promue avec gain attribué par nœud/lien contre la référence, et un rollback exercé en conditions réelles.

**Risques / rollback :** score probabiliste pris pour un gate → approbation humaine maintenue sur l'irréversible ; rollback automatique vers la version parent si les limites sont dépassées.

## Phase 4 — Spécialistes

**Entrée :** GapReports récurrents et discriminants (spec §11.4).

**Livrables :**

- Compétences comme API exécutables testées, cycle de vie complet (candidate → active → dépréciée → retirée), plafond actif et score de contribution.
- Intégration ou fine-tuning candidat seulement avec droits, licences et provenance documentés ; donnée utilisateur exclue par défaut des entraînements partagés, accord explicite et filiation obligatoires pour l'inclure. Une demande d'effacement entraîne une reconstruction sans la donnée, un désapprentissage validé ou le retrait de la version si l'effacement ne peut pas être démontré.
- Routage appris et cascade calibrés par famille de tâches, journalisés comme activités du workflow.
- Pilote de porte de décision outillée sur Tâches (spec §8.6). Comparer le Path A de `akasha-model==0.3.0` (MIT) au routage déterministe sur les mêmes décisions et le même rejeu. Consigner l’accord préalable de téléchargement, la version, l’empreinte de la roue, les seuils et la latence. L’hôte applique les autorisations et les approbations. Une promotion exige un gain attribué face à la référence et les contrôles de non-régression des autres familles. [Qualification du pilote](phase4_status.md#porte-de-décision-tâches-avec-akasha-model-030)

**Sortie :** gain attribué au spécialiste contre la baseline, sans régression sur les autres familles ; retirement exercé sur au moins une compétence.

**Risques / rollback :** accumulation de compétences dégradant le retrieval → plafond et trimming pilotés par les résultats ; rollback = retirement de la compétence.

## Phase 5 — Prédicteur d'état/action sur le banc bureau & code

**Entrée :** transitions (état, action, état) collectées en Phases 1-3.

**Livrables :**

- `DesktopState`/`CodeState` explicites et versionnés (accessibilité/DOM, fichiers, git, processus ; screenshot en appoint).
- Prédicteur de delta d'état symbolique ; scoreur latent de candidats seulement avec ablation « prédicteur aléatoire ».
- Prédiction d'exécution de code subordonnée à l'interpréteur et aux tests réels.

**Sortie :** gain de sélection d'action à politique figée ; faux-acceptés du vérificateur sous le seuil fixé en Phase 0 ; écart prévu/observé suivi par variable.

**Risques / rollback :** dynamique apprise surcréditée → ablation obligatoire et politique sans modèle du monde conservée comme repli ; rollback = désactivation du prédicteur. Les résultats ne valident pas à eux seuls la perception spatiale ni l'action dans un environnement physique.

Différés sur ce banc : reconstruction 3D métrique, contrôle continu, génération d'écran comme preuve. Ces capacités appartiennent à la piste spatiale séparée et nécessitent un plan de recherche et d'évaluation dédié.

## Phase 6 — Évolution intégrée

**Entrée :** Phases 3-5 stables et surveillées.

**Livrables :**

- Apprentissage des routes, compétences et politiques de mémoire ; détection de dérive ; attribution continue des gains.
- Automatisation limitée aux classes d'évolution à faible risque prouvées ; toute classe supérieure garde ses paliers et approbations.

**Sortie :** promotions automatiques bornées, auditables et réversibles ; aucun changement de permission par un modèle de travail.

**Risques / rollback :** dérive silencieuse → alertes sur les métriques de la Phase 5 et retour au niveau d'autonomie de la Phase 3.

## Post-MVP — Agent universel local

Les phases 0 à 6 ont validé les mécanismes sur le banc bureau et code. Les jalons G1 à G5 ont intégré les premières capacités de l’agent universel local (§2.1 de la spec).

- **G1 ouvre et restaure les sessions avec une mémoire structurée.** Un contrôle hors modèle applique le schéma d’admission avant toute écriture durable de session. Le texte libre, les pièces jointes et les valeurs dont l’admissibilité reste indéterminée demeurent volatiles. Le rejeu sur deux sessions a vérifié l’isolation et l’absence du secret synthétique et de son empreinte dans les stockages contrôlés, sauvegarde chiffrée comprise, avant et après redémarrage (§10.6).
- **G2 ajoute le vault hybride.** Le keystore OS reçoit les secrets admis et le vault applicatif gère les métadonnées de handle. Le rejeu Windows a vérifié la résolution autorisée et journalisée, le refus hors session et l’effacement dans le keystore (§10.6).
- **G3 diagnostique les lacunes puis cherche une reprise déclarée.** Une approbation requise suspend la demande. `missing` signale l’absence de capacité admissible après recherche, `abstain` clôt une demande insuffisamment étayée et une proposition de construction décrit un candidat soumis à évaluation (§11.8, §14). Les voies A à D ont été rejouées sur leurs cas de référence.
- **G4 simule hors charge.** Dans Windows Sandbox, le lancement de Notes avec Rbitnet CPU et RapidOCR a interrompu la simulation au prochain point sûr. Les deux exécutions ont validé le premier diff, les quatre tests et la persistance après relance. Sur l’assemblage G4–G5, le surcoût de préemption de l’ordonnanceur était de 2,09 ms au p95, pour un plafond de 3 s.
- **G5 explicite le registre multi-spécialistes.** Les traces identifient les moteurs et leurs budgets. Le rejeu à froid entre `image_resume` et le PNG vérifié a pris 113,521 s sous Windows Sandbox et 56,944 s sous Ubuntu WSL2. Les deux mesures passent leur seuil.

La réouverture d’une session G1 restaure les faits admis. Une tâche image MCP en attente se reprend avec son `task_id` tant que le même serveur tourne. Après un redémarrage du serveur, le client utilise `image_start` et obtient un nouvel identifiant. Les caches restent disponibles et le serveur vérifie les artefacts avant de les réutiliser (§8.7).

Après G1 et G6, la suite `tests` et `contracts` a passé 272 tests. Elle en a passé 275 après G2, 289 après G3 et 297 après G4 et G5. [Révisions testées et preuves par jalon](product-goal-roadmap-v1.md#clôture-sur-main)

### Voix locale — G7 et G8 validés sur Windows

Le parcours G7 aboutit à un compte rendu extractif dans le bureau et via MCP. Les bornes citées ont été comparées aux interventions de référence et le responsable d’une action reste indéterminé lorsque la voix dit seulement « je ». [Validation de G7](../../bench/results/g7-meeting-v1.json)

G8 est clôturé. Le bouton **Lire la réponse** utilise Vivian en streaming sur GPU et Piper sur CPU en repli. Les deux écoutes françaises ont fixé `reference` pour la conversation et `sobre` pour la narration seule. [Votes, latence et arrêt](product-goal-roadmap-v1.md#clôture-g8-sur-windows)

**Entrée.** Reprendre le dossier de spécialiste `audio.transcribe` prévu par G3 et le registre de G5. Figer un corpus français avec transcriptions de référence et extraits réservés. Préparer les manifestes candidats avec versions, licences, empreintes, formats et budgets mesurables. [Contrats audio](../architecture/brain-system-spec.md#731-transcription-et-synthèse-vocale-locales)

**Exécution.** Comparer les moteurs STT sur CPU sous Windows, puis raccorder le profil retenu à la conversation et au serveur MCP avec les mêmes vérifications de projet, de récupération et d’admission. Composer les segments avec les capacités d’analyse déclarées en gardant les références aux passages sources. Livrer ensuite `audio.synthesize` pour la lecture à la demande. Raccorder enfin le micro et l’import explicite d’une demande vocale au parcours de brouillon et d’envoi de la conversation. [Jalons et critères de sortie](product-goal-roadmap-v1.md#prochains-jalons--voix-locale)

**Validation et retour arrière.** Publier les mesures de qualité et de ressources par moteur. Rejouer les cas d’échec, de reprise, d’annulation et d’isolation. Vérifier qu’une consigne prononcée dans un enregistrement à analyser reste une donnée et qu’une demande vocale envoyée suit les mêmes contrôles qu’une demande écrite. Vérifier l’ordonnancement des tâches audio avec une autre tâche interactive. En cas d’échec de qualification ou de régression, retirer le profil du routage actif et conserver son rapport d’évaluation. La transcription non couverte revient au parcours de diagnostic G3.

## Piste séparée — Modèle du monde spatial et agent incarné

La perception spatiale, les simulateurs et l’action incarnée suivent un plan dédié. Le jalon documentaire G6 a été relu et fusionné sur `main`. Le plan fixe les critères d’entrée depuis la Phase 5, les scénarios, les observations et les seuils d’évaluation pour la piste de recherche. [Plan de recherche spatial](spatial-world-model-plan-v0.md)

## Questions de conception initiales

Ces questions ont guidé les qualifications successives. Les décisions et les preuves de sortie sont rassemblées dans les statuts de phase et leur [audit de clôture](phase6_status.md#audit-des-preuves-des-phases-0-à-6).

- Effacement et sauvegardes : les durées et principes par défaut sont décidés (§10.2, §10.5). Avant la Phase 1, choisir les mécanismes de chiffrement, clés, suppression, marqueurs et critères de preuve ; vérifier leur fonctionnement dans le MVP, puis livrer avant la fin de la Phase 2 la preuve bout-en-bout et les tests de non-résurrection sur l'ensemble des stockages concernés. La suppression d'une donnée utilisée par un modèle entraîné doit être traitée avant la Phase 4.
- Entraînement partagé : format d'accord explicite et portée de consentement ; méthodes validées de reconstruction, désapprentissage ou retrait d'un modèle — avant la Phase 4.
- Ordre de force des paliers de sandbox sur un même modèle de menace ; compatibilité du profil Windows durci, du courtier d'export et des interfaces UIA — pendant la Phase 0.
- Seuils chiffrés par domaine (réussite, coût, latence, faux-acceptés) — après les mesures des Phases 0/1, jamais importés de la littérature.
- Intégration Rbitnet : choisir HTTP/proxy ou API Rust embarquée selon les mesures de Phase 0/1 ; déterminer les contrôles et métriques manquants par architecture et version. Sélectionner en Phase 0 le second moteur local de vision/OCR et son modèle préentraîné ; choisir les adaptateurs supplémentaires au fil des besoins, sans imposer un moteur unique (spec §6.2).
- Fenêtre de compatibilité des schémas (nombre de majeurs supportés par le runtime) — avant le gel des schémas en Phase 0 (spec §16.1).
- Renforcement de la signature d'audit : chaîne de digests seule ou keystore OS — avant la fin de la Phase 1 (spec §8.5).
- Rétention : valeurs par défaut décidées en spec §10.2 ; mesurer les besoins d'ajustement en Phase 2 sans les présenter comme indéfinies.
