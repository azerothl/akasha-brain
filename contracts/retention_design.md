# Rétention, sauvegarde et restauration v1

Ce contrat de conception applique les §10.2, §10.4 et §10.5 de la
[spécification](../docs/architecture/brain-system-spec.md). Le stockage,
le coffre et les preuves de restauration relèvent des phases 1 et 2.
Les durées et la cadence restent définies par
[`RetentionPolicy/1.0.0`](schemas/RetentionPolicy/v1.0.0.json).

## Consentement et échéances

Le runtime accepte un [`BackupConsent/1.0.0`](schemas/BackupConsent/v1.0.0.json)
actif pour un projet et les catégories explicitement approuvées. La
finalité est `local_backup`. L'accord d'évolution a son propre contrat.
L'inclusion exige un accord en cours de validité pour chaque projet et
catégorie de contenu réel, y compris dans la filiation d'un dérivé.
La révocation bloque les nouvelles inclusions. Une demande d'effacement
déclenche le traitement des copies existantes. Les sauvegardes quotidiennes
locales expirent au bout de 7 jours. Les originaux du projet, secrets et
exports sous contrôle de l'utilisateur sont hors du coffre Akasha.

Chaque copie gérée porte un [`RetentionCopy/1.0.0`](schemas/RetentionCopy/v1.0.0.json).
Le registre mutable lie l'identifiant opaque de la copie aux identifiants
de ses sources directes et à son emplacement. La copie de sauvegarde
d'un contenu réel ou d'une capture enregistre ses références d'accord.
Il couvre aussi les index,
captures, caches, versions candidates et checkpoints pouvant contenir
des dérivés. Un accès en lecture conserve les échéances. Pour une nouvelle
copie ou un dérivé, enregistrer l'échéance la plus proche parmi sa classe
calculée depuis sa création, celles des sources et, pour une sauvegarde,
celle de la sauvegarde. Une restauration conserve cette échéance. Une
valeur nulle représente l'absence d'échéance propre pour une classe
admissible et reste bornée par toute échéance finie dans sa filiation.
Un lien absent, un cycle ou une échéance incohérente bloque l'inclusion
ou la restauration. Les instants sont enregistrés en UTC avec le suffixe
`Z`. L'échéance d'un temporaire sans date dépend de la fin de tâche.

## Chiffrement et récupération des clés

Chiffrer les données sauvegardées et leurs manifestes en AES-256-GCM via
une bibliothèque éprouvée. Utiliser une clé de données par objet chiffré
et une valeur de nonce unique par clé. Authentifier la version de format
et les identifiants opaques de sauvegarde et d'objet avec les données
associées. Garder les clés de données enveloppées dans un coffre courant
séparé des sauvegardes. La clé d'enveloppement de la racine
`AKASHA_HOME` est protégée au repos par DPAPI à portée utilisateur.
[AES-GCM](https://csrc.nist.gov/pubs/sp/800/38/d/final) ·
[Windows DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)

La récupération locale ouvre le coffre courant sous le compte Windows
autorisé. Pour un changement de compte ou de machine, le kit facultatif
de l'utilisateur enveloppe la clé de la racine sous un secret de
récupération aléatoire conservé séparément. Le kit requiert le coffre
courant et le registre courant de suppression. Toute copie historique
des clés de données relèverait de l'inventaire d'effacement. Le format du
kit embarque uniquement la clé d'enveloppement et son identifiant de
génération. En cas de perte du coffre, du registre, ou d'échec
d'authentification ou de déchiffrement, la restauration reste bloquée.
Après rotation, vérifier le réenveloppement et la lecture, puis traiter
l'ancienne génération et ses copies contrôlées. Exercer la récupération
sur une copie synthétique du coffre avant de la proposer.

## Effacement et barrière de restauration

1. Enregistrer le marqueur d'effacement avant de traiter les copies.
   Il porte un identifiant opaque de source, un instant, une génération
   du registre et un état de vérification. Les identifiants de contenus
   et leurs digests sont effaçables. Le journal d'audit minimal reçoit
   uniquement le statut et un code de motif.
2. Bloquer l'utilisation de la source et de ses dérivés par filiation.
   Traiter chaque emplacement contrôlé et retirer les clés de données
   et leurs copies si l'effacement est cryptographique. En présence
   d'un emplacement inaccessible, d'un dérivé lisible ou d'une clé
   non traitée, conserver l'état `pending` avec le motif et reprendre
   la même demande au prochain essai.
3. Marquer `verified` après relecture de l'inventaire, contrôle des
   dérivés et contrôle des sauvegardes et clés concernées. Maintenir les
   marqueurs tant qu'une sauvegarde peut réintroduire un objet.
4. Restaurer dans un staging inaccessible au runtime, avec le registre
   de marqueurs authentifié hors de la sauvegarde et sa génération
   courante épinglée dans le contrôle local. Un registre absent,
   invalide, plus ancien que la tête attendue ou de fraîcheur
   indéterminée bloque la restauration. Appliquer les marqueurs et
   échéances à toute la filiation avant de déchiffrer ou d'exposer une
   copie. Sous la même exclusion d'écriture que la suppression,
   revérifier la génération juste avant l'activation. Si elle a changé,
   reprendre le filtrage avant publication.

Les codes de motif du rapport sont `copy_unreachable`,
`lineage_invalid`, `key_unavailable`, `ledger_unverified`,
`ledger_generation_changed` et `verification_incomplete`. La
restauration rend `blocked` ou `verified`. Les preuves et détails
techniques restent dans un stockage effaçable et protégé.

## Critères de preuve

| Essai | Critère |
| --- | --- |
| Accord absent, expiré, révoqué ou hors périmètre | La copie réelle et ses dérivés sont écartés de la sauvegarde. |
| Source plus ancienne que son dérivé | La date d'expiration de la source prévaut après copie et restauration. |
| Clé perdue, coffre ou registre absent, registre antérieur | La restauration reste hors du runtime. |
| Effacement avec une copie indisponible | État `pending`, motif renseigné, reprise idempotente à la remise en ligne. |
| Rotation et récupération | Une copie admissible reste lisible avec le coffre courant et une copie expirée ou supprimée demeure inaccessible. |
| Suppression puis restauration de plusieurs générations | Chercher la source et ses dérivés dans les copies, index et versions restaurées donne zéro résultat lisible. Vérifier aussi le traitement des clés. |
| Effacement pendant une restauration | Le changement de génération impose un nouveau filtrage et l'objet supprimé reste inaccessible. |
