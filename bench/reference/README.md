# Référence scellée — contrôle et baseline uniquement

Ce dossier contient la **correction de référence** du banc notes, utilisée
uniquement pour :

1. valider que les tests du banc réussissent une fois la faute corrigée
   (contrôle positif, spec §12.3) ;
2. mesurer la baseline fixe du pipeline localisation → réparation →
   validation (`../run_baseline.py`).

**Interdit :** fournir ces fichiers, leur contenu ou leur diff à un modèle
ou graphe candidat pendant l'optimisation (spec §12.3, isolement du
transfert). La variante `tasks/` n'a pas de correction de référence
entreposée : elle reste réservée à l'évaluation du transfert.
