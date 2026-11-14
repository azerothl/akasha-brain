# Vérification du harness bureau Windows (spec §12.2, §13.5).
# Controle non destructif, sans élévation : Hyper-V, présence du bac
# jetable (Windows Sandbox), association .wsb, connectivité de secours.
# Sortie : une ligne PASS/FAIL/UNKNOWN par contrôle + recommandation.

$checks = @()

function Add-Check($name, $status, $detail) {
  $script:checks += [pscustomobject]@{Controle=$name; Etat=$status; Détail=$detail}
}

# Hyper-V : services d'hôte actifs ?
$vmcompute = (Get-Service vmcompute -ErrorAction SilentlyContinue).Status
$vmms = (Get-Service vmms -ErrorAction SilentlyContinue).Status
if ($vmcompute -eq 'Running' -and $vmms -eq 'Running') {
  Add-Check 'Hyper-V hôte' 'PASS' 'vmcompute + vmms actifs : checkpoint de VM utilisable.'
} else {
  Add-Check 'Hyper-V hôte' 'FAIL' "vmcompute=$vmcompute vmms=$vmms."
}

# Bac jetable : binaire et association présents ?
if (Test-Path "$env:SystemRoot\System32\WindowsSandbox.exe") {
  Add-Check 'Windows Sandbox (binaire)' 'PASS' 'WindowsSandbox.exe présent.'
} else {
  Add-Check 'Windows Sandbox (binaire)' 'FAIL' 'Absent : fonctionnalité à activer (élévation requise).'
}
$wsbAssoc = (Get-ItemProperty 'HKLM:\SOFTWARE\Classes\.wsb' -ErrorAction SilentlyContinue).'(default)'
# Information seulement : le harness lance toujours WindowsSandbox.exe avec
# le chemin du .wsb ; le double-clic n'est pas requis.
if ($wsbAssoc) {
  Add-Check 'Association .wsb (info)' 'PASS' ".wsb -> $wsbAssoc."
} else {
  Add-Check 'Association .wsb (info)' 'PASS' 'Non enregistrée ; lancement explicite utilisé.'
}

# Client de connexion VM (secours / inspection) ?
if (Get-Command vmconnect.exe -ErrorAction SilentlyContinue) {
  Add-Check 'vmconnect' 'PASS' 'Client présent.'
} else {
  Add-Check 'vmconnect' 'UNKNOWN' 'Non trouvé sur PATH.'
}

# Profil durci : le .wsb de référence porte exactement les réglages de
# sandbox_profile.md (parse XML, aucune exécution).
$wsb = Join-Path (Split-Path $PSCommandPath -Parent) 'akasha-bench.wsb'
try {
  [xml]$cfg = Get-Content $wsb -Raw -Encoding UTF8
  $expected = @{
    Networking = 'Disable'; ClipboardRedirection = 'Disable';
    AudioInput = 'Disable'; VideoInput = 'Disable';
    PrinterRedirection = 'Disable'; VGpu = 'Disable'; MemoryInMB = '4096'
  }
  $bad = @()
  foreach ($k in $expected.Keys) {
    $node = $cfg.Configuration.SelectSingleNode($k)
    if ($null -eq $node -or $node.InnerText -ne $expected[$k]) { $bad += $k }
  }
  $mapped = $cfg.Configuration.SelectSingleNode('MappedFolders')
  if ($null -eq $mapped -or ($mapped.HasChildNodes)) { $bad += 'MappedFolders(non-vide)' }
  if ($bad.Count -eq 0) {
    Add-Check 'Profil .wsb durci' 'PASS' 'akasha-bench.wsb conforme.'
  } else {
    Add-Check 'Profil .wsb durci' 'FAIL' ('Ecarts : ' + ($bad -join ', '))
  }
} catch {
  Add-Check 'Profil .wsb durci' 'FAIL' 'Illisible.'
}
$checks | Format-Table -AutoSize | Out-String | Write-Output
$fail = @($checks | Where-Object { $_.Etat -eq 'FAIL' }).Count
if ($fail -eq 0) {
  Write-Output 'HARNESS PASS : bac jetable vérifié.'
} elseif ((@($checks | Where-Object { $_.Controle -eq 'Hyper-V hôte' -and $_.Etat -eq 'PASS' }).Count) -gt 0) {
  Write-Output 'HARNESS PARTIEL : checkpoint de VM utilisable ; bac jetable à activer avant le parcours bureau (voir spec §12.2).'
  exit 1
} else {
  Write-Output 'HARNESS FAIL : ni bac jetable ni Hyper-V vérifiés.'
  exit 2
}
