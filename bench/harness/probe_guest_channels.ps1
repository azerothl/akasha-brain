# Sonde en lecture seule dans Windows Sandbox. Le code de sortie encode
# les contrôles pour un rapport borné via wsb exec.
$ErrorActionPreference = 'Stop'

try {
    $routes = @(Get-NetRoute | Where-Object {
        $_.DestinationPrefix -in @('0.0.0.0/0', '::/0')
    })
    $devices = @(Get-PnpDevice -PresentOnly)
    $cameras = @($devices | Where-Object { $_.Class -in @('Camera', 'Image') })
    $capturePath = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture'
    $capture = @(
        if (Test-Path -LiteralPath $capturePath) {
            Get-ChildItem -LiteralPath $capturePath | Where-Object {
                ((Get-ItemProperty -LiteralPath $_.PSPath).DeviceState -band 1) -ne 0
            }
        }
    )
    $redirectedPrinters = @(Get-CimInstance Win32_Printer | Where-Object {
        $_.PortName -match '^TS\d+' -or $_.Name -match 'redirected|redirig'
    })
    $clipboardProcess = @(Get-Process rdpclip -ErrorAction SilentlyContinue)

    $result = 0x4100
    if ($routes.Count -eq 0) { $result = $result -bor 1 }
    if ($cameras.Count -eq 0) { $result = $result -bor 2 }
    if ($capture.Count -eq 0) { $result = $result -bor 4 }
    if ($redirectedPrinters.Count -eq 0) { $result = $result -bor 8 }
    if ($clipboardProcess.Count -eq 0) { $result = $result -bor 16 }
    exit $result
} catch {
    exit 20
}
