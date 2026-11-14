# Couverture UIA — constat Phase 0 (2026-11-14)

Sonde : `check_uia.ps1` (lecture seule, aucune focalisation ni modification).
Données brutes en `$env:TEMP/akasha-uia-probe.json` (titres de session
réelle : non versionnés, confidentialité). Seuls les agrégats sont
consignés ici.

## Résultat

- COM `CUIAutomation` (`{ff48dba4-...}`) : **non enregistré**
  (`REGDB_E_CLASSNOTREG`) sur ce poste — voie COM inutilisable, repli
  obligatoire.
- API managée `UIAutomationClient` : **opérationnelle** — racine lue,
  **34 éléments de premier niveau**, 5/5 premières fenêtres nommées lues
  avec nom, type de contrôle, descendants directs et AutomationId.
- Conclusion : l'état bureau explicite par accessibilité (spec §9.7) est
  accessible sans dépendance ; prévoir le repli managé et tester la
  couverture par application (certaines apps n'exposent qu'un arbre
  partiel). Focus/IME/presse-papiers/DPI et comportement UAC restent à
  vérifier par tâche en Phase 1.
