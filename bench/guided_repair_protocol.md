# Réparation guidée des notes sur CPU — protocole v1

Le banc mesure une réparation de `NoteStore.save_note` sur le poste cible.
[Critères de la phase 0](../docs/plans/phase0_status.md#premiers-seuils-proposés)

## Entrées et isolation

- Qwen3-8B Q4_K_M sur Rbitnet HTTP/CPU, en boucle locale, avec un
  processus neuf à chaque tentative. Le lanceur contrôle les SHA-256
  du binaire, du GGUF et du tokenizer avant de démarrer.
- Une session Windows Sandbox durcie et ouverte. Le Python portable
  préparé pour le banc et les fixtures sont montés en lecture seule.
  Les tests et le vérificateur disposent à chaque exécution de leur
  propre copie de travail et d'une base de test neuve. Le banc utilise
  Python 3.12.7 et pytest 9.2.0.
- La source fautive, l'interface et les tests sont identifiés dans le
  rapport par leur empreinte. La correction de référence est copiée
  le temps de la baseline et retirée du partage et du bac avant le
  premier cycle. Le modèle reçoit la méthode des notes et, au besoin,
  le résultat du contrôle de sa propre proposition.

## Déroulement figé

1. Contrôler le témoin fautif dans le bac. Il doit donner deux tests
   passants, deux échecs et un refus du vérificateur.
2. Baseline fixe dans la même session. Reproduire les échecs par les
   tests, copier la correction scellée, puis relancer les quatre tests
   et le vérificateur. Le chronomètre mesure ces étapes depuis l'hôte,
   avec la traversée de la CLI Windows Sandbox. Le plafond de **3 s**
   proposé auparavant s'applique à la baseline mesurée sur l'hôte.
3. Trois cycles indépendants. Utiliser les paires de graines
   **741/751**, **742/752**, **743/753**. Chaque cycle recommence sur
   la version fautive et avec une nouvelle requête. Utiliser
   température **0**, **176 jetons maximum**, le format ChatML et les
   invites définies dans le lanceur. La première proposition est une
   méthode Python complète. Le lanceur extrait le premier bloc Python
   complet ou lit la réponse entière si elle contient uniquement la
   méthode. Il contrôle la signature, construit un diff limité à
   `save_note`, puis lance `git apply --check` et `git apply`.
4. Vérifier chaque essai. Les tests et le vérificateur tournent sur la
   copie corrigée si le diff s'applique, ou sur le témoin fautif si la
   proposition est rejetée. Au premier échec, une seconde génération
   reçoit le rejet de la proposition ou les résultats de validation.
   Le retour distingue le cas où SQLite confirme la persistance et
   où les tests signalent une connexion fermée. Le second diff est
   calculé depuis la version fautive. Un cycle s'arrête dès que la
   réparation satisfait les critères fonctionnels.

## Mesures et critères

La durée d'une tentative couvre la préparation, le démarrage du
processus Rbitnet, la génération, le contrôle du diff et la validation
dans le bac. Le temps du cycle inclut aussi la préparation du retour
de tests. Les plafonds provisoires sont **60 s par tentative** et
**120 s par cycle**.

Le premier contrôle de répétabilité passe si **3 cycles sur 3**
respectent les plafonds et se terminent par un diff applicable,
**4/4 tests sans saut** et un vérificateur au vert. Le rapport
conserve les mesures par tentative et les réponses brutes. Ce lot
mesure la répétabilité sur la fixture des notes.

## Exécution

Lancer depuis la racine du dépôt, avec le bac durci déjà ouvert et
le dossier portable contenant `python.exe`, `DLLs`, `Lib` et Tcl/Tk.
La commande crée le dossier de résultats, qui doit être neuf.

~~~powershell
.\.venv\Scripts\python.exe bench/run_guided_repair.py `
    --engine <rbitnet-server.exe> --model <Qwen3-8B-Q4_K_M.gguf> `
    --tokenizer <tokenizer.json> --python-runtime <python-portable> `
    --sandbox-id <id-de-wsb-list> --output <dossier-de-résultats>
~~~

[Lanceur](run_guided_repair.py) · [Vérifications dans le bac](harness/validate_guided_notes.ps1)
