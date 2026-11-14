# Sonde UIA en lecture seule (spec §12.2, angle mort §19.10).
# N'ouvre, ne focalise et ne modifie rien : parcourt l'arbre
# d'accessibilité via CUIAutomation (COM, sans dépendance).
# Sortie : résumé + JSON détaillé (chemin passé en argument ou TEMP).

param([string]$OutJson = "")

$ErrorActionPreference = 'SilentlyContinue'
$report = @{ windows = @(); top_level_count = 0; ok = $false; error = '' }

try {
  # Voie 1 : COM CUIAutomation. Voie 2 (repli) : UIAutomationClient managé.
  $via = 'com'
  try {
    $auto = [Activator]::CreateInstance([Type]::GetTypeFromCLSID('{ff48dba4-60ef-4201-aa87-54190cce594e}'))
  } catch {
    Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
    $via = 'managed'
  }
  if ($via -eq 'com') {
    $root = $auto.GetRootElement()
    $cond = $auto.CreateTrueCondition()
    $kids = $root.FindAll(2, $cond)
  } else {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $cond = [System.Windows.Automation.Condition]::TrueCondition
    $kids = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
  }
  $report.via = $via
  $report.top_level_count = $kids.Length
  $P = @{
    name = 30005; control_type = 30003; automation_id = 30011
    scope_children = 2
    get_count = { param($col) $col.Length }; get_item = { param($col, $i) $col.GetElement($i) }
  }
  if ($via -eq 'managed') {
    Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
    $P.name = [System.Windows.Automation.AutomationElement]::NameProperty
    $P.control_type = [System.Windows.Automation.AutomationElement]::ControlTypeProperty
    $P.automation_id = [System.Windows.Automation.AutomationElement]::AutomationIdProperty
    $P.scope_children = [System.Windows.Automation.TreeScope]::Children
    $P.get_count = { param($col) $col.Count }; $P.get_item = { param($col, $i) $col[$i] }
  }
  $get = { param($el, $prop) try { "$($el.GetCurrentPropertyValue($prop))" } catch { '' } }
  $shown = 0
  $total = & $P.get_count $kids
  $report.top_level_count = $total
  for ($i = 0; $i -lt $total -and $shown -lt 5; $i++) {
    $el = & $P.get_item $kids $i
    $name = & $get $el $P.name
    if ([string]::IsNullOrWhiteSpace($name)) { continue }
    $entry = @{ name = $name; control_type = 0; children = @() }
    try { $entry.control_type = [int](& $get $el $P.control_type) } catch {}
    try {
      $sub = $el.FindAll($P.scope_children, $cond)
      $subtotal = & $P.get_count $sub
      $n = [Math]::Min($subtotal, 8)
      for ($j = 0; $j -lt $n; $j++) {
        $c = & $P.get_item $sub $j
        $entry.children += @{ name = (& $get $c $P.name); control_type = 0; automation_id = (& $get $c $P.automation_id) }
        try { $entry.children[-1].control_type = [int](& $get $c $P.control_type) } catch {}
      }
      $entry.child_count = $subtotal
    } catch {}
    $report.windows += $entry
    $shown++
  }
  $report.ok = $true
} catch {
  $report.error = "$($_.Exception.Message)"
}

if ($OutJson -eq '') { $OutJson = Join-Path ([IO.Path]::GetTempPath()) 'akasha-uia-probe.json' }
$report | ConvertTo-Json -Depth 4 | Set-Content $OutJson -Encoding UTF8
Write-Output ("UIA ok={0} top_level={1} fenetres_lues={2} json={3} {4}" -f $report.ok, $report.top_level_count, $report.windows.Count, $OutJson, $report.error)
if (-not $report.ok) { exit 1 }
