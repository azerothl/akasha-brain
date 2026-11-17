# Profil sandbox du banc (spec §13.5, §12.2)

Le profil initial de phase 0 est `akasha-bench.wsb`, vérifié automatiquement
par `check_harness.ps1`. Les lanceurs ajoutent les entrées en lecture seule
et adaptent la mémoire au scénario. Le parcours image décrit plus bas
emploie 8 192 Mio et vérifie son propre transport de sortie.

| Réglage | Valeur | Raison |
|---|---|---|
| `Networking` | Disable | Egress refusé par défaut ; réseau actif par défaut sinon |
| `ClipboardRedirection` | Disable | Canal de fuite vers l'hôte |
| `AudioInput` / `VideoInput` | Disable | Capteurs non requis par le banc |
| `PrinterRedirection` | Disable | Surface d'attaque inutile |
| `VGpu` | Disable | Ne s'active que si une tâche le requiert (compatibilité à mesurer) |
| `MemoryInMB` | 4096 | Borne mémoire du bac |
| `MappedFolders` | vide | Aucun dossier hôte accessible par défaut |

`ProtectedClient` demande une frontière AppContainer côté client.
Le profil nominal du banc emploie la valeur par défaut de Windows.
Le vGPU désactivé est compatible avec le parcours actuel des notes.
[Configuration Windows Sandbox](https://learn.microsoft.com/en-us/windows/security/threat-protection/windows-sandbox/windows-sandbox-configure-using-wsb-file)

## Preuves dans le bac

Le 15 novembre, [la sonde invitée](probe_guest_channels.ps1) n'a trouvé
aucune route par défaut IPv4 ou IPv6, caméra présente, entrée audio
active ni imprimante sur port redirigé. Le même résultat a été obtenu
dans le nouveau bac lancé avec `ProtectedClient=Enable`.

Avec `ClipboardRedirection=Disable`, l'hôte et l'invité ont chacun
écrit et relu un marqueur synthétique distinct. Le bac n'a pas reçu
le marqueur hôte. L'hôte a conservé son marqueur après l'écriture
du marqueur invité. Les huit formats initiaux du presse-papiers de
l'hôte ont été restaurés à chaque essai. Les deux sens ont été vérifiés
sur le profil nominal et sur le profil demandant Protected Client.
Les rapports `phase0-closure/clipboard-nominal-active.json` et
`phase0-closure/clipboard-disabled-active.json` contiennent les verdicts
et le nombre de formats.

### Essai Protected Client

Windows Sandbox 0.8.114.0 a accepté le profil avec
`ProtectedClient=Enable` et `VGpu=Disable`. Le montage a autorisé la
lecture et refusé l'ouverture en écriture du témoin et la création
d'un fichier. L'empreinte du témoin hôte correspond avant et après.
Le parcours clavier avec garde de focus UIA a été joué dans les deux
copies. Après fermeture, SQLite contient la note dans la référence
corrigée et reste vide dans le témoin fautif.

La compatibilité de ce parcours est vérifiée avec l'option demandée.
Le jeton du processus externe `WindowsSandboxRemoteSession` annonce
`TokenIsAppContainer=0`. La frontière interne reste à attester
si un futur profil d'exécution en dépend. Le profil nominal s'appuie
sur les contrôles de canaux et de montage mesurés ici.

## Import / export contrôlé

Le bac part sans montage : rien n'entre ni ne sort sauf procédure.

- **Intrants** : le lanceur copie la copie de travail dans un dossier de
  staging hôte, monté **en lecture seule** pour la durée du run uniquement
  (`<ReadOnly>true</ReadOnly>`), puis démonté avant toute autre tâche.
- **Sortants** : seul le courtier écrit dans le dossier d'export de
  l'hôte. Le banc a vérifié un rapport JSON de forme fermée, composé
  de valeurs bornées transmises par la CLI. La lecture indépendante
  de SQLite s'effectue dans le bac et remonte un résultat de contrôle.
- Captures et OCR suivent les durées de la politique de rétention
  (captures 7 j) et sont effaçables avec le reste des contenus.

Les parcours livrés prennent en charge les artefacts suivants.

- Rapports structurés en JSON avec schéma fermé, par exemple verdicts,
  compteurs et codes d'erreur du banc.
- Diffs unifiés textuels pour la proposition et sa relecture. Le
  courtier impose une taille bornée, décode le texte, vérifie les
  chemins et remet le diff à la chaîne d'approbation.
- PNG issus du moteur d’image déclaré, avec taille bornée,
  validation du décodage, normalisation et preuve SHA-256.

Le courtier choisit le nom de sortie dans la proposition et vérifie
les chemins des fichiers et du diff. Le reçu lie la sortie à
l’identifiant du run. Le parcours projet présente le diff vérifié
à l’approbation de l’utilisateur. [Projet via MCP](../results/mcp-real-project-v1.json)

Pour l’image, la CLI utilise le nouveau fichier PNG choisi par
l’utilisateur. MCP transmet le PNG au client, qui peut le conserver
et recalculer son empreinte.

Windows Sandbox est le banc des notes sur ce poste. L'inventaire
Hyper-V du profilage était vide. Le checkpoint de VM reste un repli
pour les tâches dont le bac ne peut pas isoler les entrées et le focus.

## Interaction avec les notes

UIA managé repère la fenêtre du processus de test et contrôle son
focus conjointement avec le PID Win32 de la fenêtre de premier plan.
Sur Tk, l'appel UIA d'activation a échoué. La reconnexion du bac
et l'activation de la fenêtre par le shell Windows ont permis le
parcours clavier. Avant chaque entrée, vérifier que la fenêtre et le
focus appartiennent toujours au processus de test. Entrer via le
clavier dans le bac. Pour l'observation des contrôles non exposés par
UIA, utiliser une capture locale et OCR dans le parcours exploratoire.
Pour le verdict, relire le contenu attendu dans SQLite après fermeture.

La [sonde de focus](probe_notes_focus.ps1) a saisi un titre et un
contenu synthétiques. Après fermeture, SQLite contient exactement la
note attendue dans la copie corrigée et reste vide dans le témoin
fautif. Le focus a échoué sur certains lancements et la reconnexion a
permis de rejouer. Cette sonde de phase 0 contrôle le focus et SQLite.

Le parcours Notes RapidOCR v2 relance l’application et retrouve
la note par OCR, puis confirme la persistance avec SQLite.
Le graphe complet l’intègre après le diff et les quatre tests.
[Graphe complet Notes](../../docs/plans/phase1_status.md#graphe-complet-rbitnet-cpu-et-rapidocr-v2)

## Exécution image sans fenêtre sur Windows et Linux

Sous Windows, le lanceur utilise la CLI Windows Sandbox et
`hcsdiag.exe` pour démarrer, identifier et interroger le bac sans
client graphique. Il vérifie les canaux désactivés et le montage en
lecture seule avant de lancer SD-Turbo sur CPU. Le flux HCS transporte
une enveloppe PNG bornée avec sa taille et son SHA-256.

Sous Linux, Bubblewrap utilise un compte non privilégié, des espaces
de noms privés, un réseau isolé, des entrées en lecture seule et un
espace temporaire privé. La sonde invitée vérifie ces contrôles avant
le démarrage du moteur. Le PNG est récupéré sur la sortie standard.
Le rejeu publié utilise Ubuntu sous WSL2.

La validation commune borne le PNG à 2 Mio, vérifie le décodage et
les dimensions 512 × 512, puis le normalise en RGB et retire ses
métadonnées. Le verdict conserve l’empreinte du flux reçu et celle du
PNG livré. Le contrôleur vérifie l’arrêt du bac.

L’archive CPU et les poids sont vérifiés avant chaque préparation.
Chaque téléchargement demande un accord distinct hors du bac.
La qualification synthétique est suivie de la demande dans un bac
neuf. La CLI, la conversation Windows et MCP réutilisent cette
chaîne d’exécution. [Export Windows](../results/image-windows-headless-v1.json) ·
[MCP Windows et Linux](../results/image-mcp-headless-v1.json) ·
[Deux accords et reprise à cache vide](../results/image-mcp-cold-cache-v1.json)
