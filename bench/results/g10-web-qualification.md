# G10 — Collecte web publique depuis le bureau Windows

Le 19 novembre 2026, le parcours a été rejoué à partir de la clôture G9 (`8e2aa95`) avec les seuls changements G10. Les deux lectures de la page publique ont chacune reçu leur propre accord. Le bureau a affiché les extraits après 0,938 s puis 0,766 s. Le changement de session, la demande à deux liens et l’annulation ont laissé le compteur à deux lectures. [Relevé de clôture](g10-web-desktop-cloture.json)

**Qualifié le 18 novembre 2026** sur Windows 11, build 26320, Python 3.12.7 et Tk 8.6. Le bureau lancé sans projet a affiché deux extraits datés de la même page publique. La première demande contenait l’URL, la seconde disait « Que dit cette page ? ». Chaque lecture a demandé son propre accord. [Relevé du rejeu](g10-web-desktop.json)

## Rejeu dans la fenêtre

Le banc ouvre le bureau et utilise ses champs et boutons Tk, son registre de sessions, son ordonnanceur et son lecteur HTTPS. Les données locales de ce rejeu sont temporaires. Le banc observe les lancements du processus de collecte sur l’hôte et relit les décisions dans SQLite. La seule page demandée est `https://example.com/`. [Banc reproductible](../run_g10_web.py)

| Action | Observation |
| --- | --- |
| Envoyer l’URL en session 1 | Le bureau affiche l’adresse exacte et propose « Autoriser la lecture ». Aucun lancement du lecteur ni aucune décision de collecte avant le clic. |
| Autoriser le premier tour | « Example Domain », l’URL et « Relevé le 18/11/2026 à 23:17 » apparaissent dans la conversation après 0,859 s. |
| Envoyer la relance puis autoriser | Même URL, nouvel accord, deuxième extrait daté après 0,765 s. Deux processus de collecte au total, une paire `authorized` / `collected` pour chaque identifiant. |
| Ouvrir une nouvelle session sans projet et envoyer la relance | Le bureau invite à coller une URL. Le transcript de la nouvelle session ne reprend ni l’adresse ni l’accord précédent. |
| Indiquer deux liens puis annuler une proposition à lien unique | Le bureau demande de choisir un lien. Après « Annuler », le bouton d’autorisation disparaît. Le compteur de lancements reste à deux et le journal conserve ses quatre lignes. |

Les deux durées vont du clic d’autorisation à l’affichage dans le bureau sur cette machine. Le plafond du lecteur est vérifié séparément avec un enfant local qui attend, pour éviter de dépendre du temps de réponse d’un site.

## Contrôles locaux

| Propriété vérifiée | Résultat |
| --- | --- |
| Accord obligatoire, échéance et usage unique | Sans accord, le lecteur reste inactif. À 299,999 s un accord neuf est accepté. À 300 s un autre accord émis au même instant est expiré. Une seconde utilisation est refusée après succès comme après dépassement du délai. |
| Délai du processus | Le parent de production interrompt un véritable enfant local qui devait attendre 45 s. Le test complet dure 15,07 s, constate la fin de l’enfant et retrouve `timeout_exceeded` dans le journal. |
| Taille du corps et du texte | Aux abords de 256 Kio, le lecteur demande au plus 262 145 octets, octet de détection compris. Le texte est conservé jusqu’à 8 000 caractères inclus. Le dépassement de l’une ou l’autre limite signale la troncature. |
| Formats de réponse | Le lecteur refusait déjà une image ou un encodage gzip. Deux cas échouaient avant correction car le parseur assimilait un type absent ou vide à du texte. Le lecteur exige désormais un type déclaré pris en charge avant de lire le corps. |
| Destinations, redirections et TLS | Des réponses DNS et HTTP fournies en mémoire vérifient le refus d’une résolution comprenant une adresse privée et l’arrêt dès la redirection. Le contrôle TLS porte sur le nom approuvé. Ces cas ne sollicitent aucune destination réseau. |
| Journal | La relecture vérifie le numéro de séquence, l’UUID d’accord, l’heure UTC et l’issue. Elle contrôle aussi que le schéma se limite à ces quatre champs, y compris pour les décisions refusées et expirées. |
| Frontière du bac | Le rejeu observe le processus hôte. Le contrôle existant du profil Windows Sandbox lit `Networking=Disable` et refuse une copie du profil avec le réseau activé. Cette vérification porte sur la configuration. |

## Reproduire

Depuis la racine du dépôt, dans PowerShell, les deux premières commandes exécutent les contrôles locaux. La troisième ouvre la fenêtre et effectue les deux lectures publiques.

```powershell
.venv/Scripts/python -m pytest -q --durations=1 tests/test_web_collection.py
.venv/Scripts/python -m pytest -q tests/test_conversation_planning.py tests/test_desktop_conversation.py tests/test_conversation_sessions.py tests/test_notes_runtime.py
.venv/Scripts/python -m bench.run_g10_web --output bench/results/g10-web-desktop.json
```

Les **25 tests web** ont réussi en 15,54 s et les **27 tests voisins** en 0,64 s. Les 12 cas web présents au début de la qualification sont repris dans les 25. [Tests web](../../tests/test_web_collection.py) · [Lecteur corrigé](../../akasha_brain/web_collection.py)
