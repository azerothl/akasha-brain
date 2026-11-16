# Phase 2 — Mémoire et réutilisation

## Journal Notes et mémoire locale

Les deux journaux SQLite de la phase 1 ont passé le contrôle d’intégrité. Le cycle Notes avec le plafond RAM corrigé contient six `ExperienceRecord`, et le cycle déclenché depuis le parcours projet en contient quatre. Les dix sont conformes au contrat et portent uniquement des résultats techniques. Les traces contiennent des vérifications de localisation, d’application du diff, de tests, de SQLite et, selon le parcours, de RapidOCR après relance.

La mémoire déplace les résultats sélectionnés dans la même base SQLite que le journal Notes. L’extraction conserve les versions, les étapes et les résultats techniques admis. La capture automatique s’active lorsque le journal de l’exécution est initialisé pour la mémoire. Les fenêtres de travail contiennent des références à au plus 32 expériences, avec éviction des plus anciennes de la fenêtre et des pages de quatre. Chaque expérience consigne cette politique. Les faits se consultent à une date de validité et à une date de connaissance distinctes.

Sur une copie jetable du premier journal, six expériences ont été importées et relues en deux pages de quatre et deux. Un fait SQLite a été extrait. La demande d’effacement d’une expérience a bloqué la lecture de l’expérience, de la fenêtre et du fait avant leur suppression. Le journal source contient toujours ses six lignes.

Le parcours fixe a été rejoué dans un Windows Sandbox neuf le 16 novembre 2026. Les trois étapes se sont terminées en 51,543 s, avec quatre tests réussis et un code SQLite de 0. Les sondes d’isolation ont réussi et les contrôles ont refusé l’exécution sans confinement et hors périmètre. Le journal a capturé automatiquement un enregistrement, relu après l’arrêt du bac. La preuve locale est dans `phase2-notes-capture-3wygr0g8/memory.json`.

Le registre d’effacement vit à côté du stockage SQLite. Les marqueurs bloquent les objets et leurs dérivés avant leur purge. Le journal d’audit séparé enregistre uniquement les opérations et leurs résultats. Les vérifications locales ont exercé l’échec de purge, sa reprise, la présence du marqueur de trace expurgée, la rétention héritée et le refus d’un stockage dont le registre d’effacement manque.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.memory --db $journal init
.\.venv\Scripts\python.exe -m akasha_brain.memory --db $journal capture
.\.venv\Scripts\python.exe -m akasha_brain.memory --db $journal list
.\.venv\Scripts\python.exe -m akasha_brain.retention --db $journal
```

## Bibliothèque privée et mesure de réutilisation

Les manifestes de l’annuaire local séparent la version parente `1.0.0` et la version avec réutilisation `1.1.0`. Les preuves du journal, les compétences, les workflows, les index et les diffs restent gérés par le stockage effaçable. La publication a admis Notes code après deux preuves CPU et Notes avec RapidOCR après trois preuves CPU. Chaque preuve porte sur un bac distinct et le même diff vérifié.

Sur 13 fiches synthétiques, la similarité seule a pris 3 décisions correctes et sélectionné 10 workflows incompatibles. Le même classement précédé du filtre a pris 13 décisions correctes. Le classement combiné sur les workflows qui passent le filtre a également obtenu 13/13. Les cas couvrent notamment les permissions, une approbation en attente, l’incertitude, le transfert réservé, l’absence de capacité et un vérificateur modifié. Le bras similarité est évalué en lecture seule.

Le classement combiné associe pertinence lexicale, récence, importance et PageRank personnalisé sur les liens entre workflows et capacités. Le filtre s’applique avant ce classement. Le banc A/B a également été rejoué avec ce classement sur la version actuelle.

Le gain de réutilisation a été mesuré sur le même graphe Notes avec RapidOCR, en bacs neufs et avec l’ordre des bras inversé entre les deux paires. Le bras génération utilise Rbitnet CPU, le même protocole et un plafond d’admission de 8 192 Mio. Le bras réutilisation applique le diff validé et rejoue les mêmes contrôles.

| Paire | Génération Rbitnet CPU | Réutilisation | Temps gagné |
| --- | ---: | ---: | ---: |
| 1 | 153,338 s | 74,956 s | 78,382 s |
| 2 | 118,360 s | 70,995 s | 47,365 s |
| Médiane | 135,849 s | 72,976 s | 62,873 s |

Les quatre bacs ont donné le même résultat pour l’application du diff, les quatre tests, l’isolation, les autorisations et la persistance après relance vérifiée par RapidOCR et SQLite. La seconde réutilisation est le rejeu de la première trace. La suite locale a tourné pendant une partie de la première génération. La seconde paire donne une mesure de 47,365 s gagnées pour ce parcours.

Le retrait d’une source a bloqué les deux traces avant la purge et supprimé sept objets dans le stockage actif. Le retour arrière a rétabli la version `1.0.0`, le graphe parent Notes code et désactivé la capture et la réutilisation. Le rapport local `phase2-workflow-reuse-526264a8/report.json` contient les décisions A/B et les quatre traces normalisées.

Le cycle de compétence a exercé la publication sur preuves, le refus d’un doublon actif, la dépréciation, la réactivation et le retrait. Le retrait a exclu la compétence du classement et conservé son artefact pour un rejeu explicite. Ce rejeu a reproduit le verdict en bac neuf, avant le refus des deux traces après effacement. Les compteurs de contribution ont enregistré une utilisation vérifiée. Le rapport local est dans `phase2-skill-lifecycle-zx6ek9mc/proof.json`.

## Sauvegarde chiffrée des mémoires techniques

Chaque objet de chaque génération est chiffré avec sa propre clé AES-GCM. La clé est protégée par DPAPI pour le compte Windows courant et conservée dans un coffre séparé de l’enveloppe. Le coffre lie la restauration aux marqueurs d’effacement courants. La rotation conserve sept jours par défaut, avec une sauvegarde par jour lorsque le service de maintenance tourne.

Le banc a créé deux générations de 18 objets comprenant des expériences, une fenêtre de travail, un fait, des artefacts, des compétences, des workflows, des index et une trace. Une panne simulée du coffre a laissé l’effacement en attente, avec la réutilisation bloquée dès la demande. La reprise a traité huit objets et supprimé leurs 16 clés dans les deux générations, y compris celles d’une trace présente uniquement dans les sauvegardes. Le registre absent et une copie du registre antérieure à l’effacement ont chacun provoqué le refus de la restauration.

Une restauration indépendante de chaque génération dans un stockage actif vidé a rétabli dix objets et écarté les huit objets effacés. La rétention a ensuite retiré un objet expiré présent uniquement dans les sauvegardes, avant la rotation des deux générations. La chaîne d’audit a été vérifiée sur onze événements. Le rapport local est dans `phase2-memory-backup-expiry-2556015f/report.json`.

```powershell
.\.venv\Scripts\python.exe -m akasha_brain.memory_backup --db $journal watch
.\.venv\Scripts\python.exe -m akasha_brain.memory_backup --db $journal restore $generation
```

## Mémoire et consentement du parcours projet

La mémoire référence la copie autorisée dans le stockage du projet et enregistre le résultat technique de son rejeu. Elle contrôle à chaque lecture l’identité du projet, la catégorie, l’accord courant et les marqueurs d’effacement. Le contenu source reste dans le stockage de projet et la sauvegarde de mémoire des résultats techniques exclut les objets rattachés à un projet.

Sur un projet jetable, Windows Sandbox a validé la proposition et son rejeu. Les contrôles ont refusé la collecte sans accord, la catégorie et le projet hors périmètre, puis la réutilisation et la lecture après révocation. La trace s’est bloquée dès la demande d’effacement. Une restauration de la sauvegarde du projet créée avec un accord distinct a réintroduit zéro copie et zéro rapport. Le fichier d’origine est resté intact. Le rapport local est dans `phase2-project-memory-2rx8dtmk/proof.json`.

## Plafond disque

`AKASHA_MEMORY_DISK_BYTES` fixe le plafond appliqué par la maintenance. La purge priorise les demandes d’effacement, puis évince les artefacts orphelins par ancienneté. Elle protège les artefacts référencés dans le stockage actif ou dans les générations chiffrées et signale le dépassement si le stockage protégé excède le plafond.

## Clôture

Les critères de sortie du [plan de développement](development-plan.md) ont été vérifiés sur le banc local. Le gain de réutilisation a été mesuré avec les mêmes contrôles en bac, et l’effacement a été vérifié sur le stockage actif, les exécutions temporaires, les traces et les sauvegardes contrôlées. La suite de validation finale compte 175 tests réussis.

Le [relevé de validation versionné](../../bench/results/memory-phase2-v1.json) regroupe les résultats par essai, les décisions A/B et les contrôles de rejeu, d’effacement et de restauration.
