# Profil sandbox du banc (spec §13.5, §12.2)

Fichier de référence : `akasha-bench.wsb` (vérifié automatiquement par
`check_harness.ps1`, section profil). Réglages et raisons :

| Réglage | Valeur | Raison |
|---|---|---|
| `Networking` | Disable | Egress refusé par défaut ; réseau actif par défaut sinon |
| `ClipboardRedirection` | Disable | Canal de fuite vers l'hôte |
| `AudioInput` / `VideoInput` | Disable | Capteurs non requis par le banc |
| `PrinterRedirection` | Disable | Surface d'attaque inutile |
| `VGpu` | Disable | Ne s'active que si une tâche le requiert (compatibilité à mesurer) |
| `MemoryInMB` | 4096 | Borne mémoire du bac |
| `MappedFolders` | vide | Aucun dossier hôte accessible par défaut |

Non activé par défaut (compatibilité à évaluer par tâche) :
`ProtectedClient` (exige VBS). À évaluer avec vGPU en Phase 1.

## Import / export contrôlé

Le bac part sans montage : rien n'entre ni ne sort sauf procédure.

- **Intrants** : le lanceur copie la copie de travail dans un dossier de
  staging hôte, monté **en lecture seule** pour la durée du run uniquement
  (`<ReadOnly>true</ReadOnly>`), puis démonté avant toute autre tâche.
- **Sortants** : seul le courtier d'export écrit dans le dossier d'export
  hôte (extensions autorisées : `.log`, `.json`, bases de test), après
  contrôle du contenu ; jamais d'exécutable ni de secret.
- Captures et OCR suivent les durées de la politique de rétention
  (captures 7 j) et sont effaçables avec le reste des contenus.

Tant que la fonctionnalité Sandbox n'est pas activée sur le poste,
le harness primaire reste le checkpoint de VM (`check_harness.ps1`).

Activation (à lancer soi-même dans PowerShell **administrateur**,
l'agent ne peut pas s'élever) :
`Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All`
puis redémarrer si demandé. Vérification ensuite par l'agent :
`check_harness.ps1` doit passer Sandbox + `.wsb` (binaire présent,
association `.wsb`), puis fumée du bac durci.

Constat 2026-11-14 : module Hyper-V présent, **aucune VM sur l'hôte**.
Le checkpoint exige donc de créer d'abord une VM (image OS à choisir,
installation, snapshot initial) — arbitrage Sandbox (activation avec
élévation) contre création VM à trancher avec l'utilisateur.
