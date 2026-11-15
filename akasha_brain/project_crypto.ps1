param([Parameter(Mandatory = $true)][ValidateSet('seal', 'unseal', 'encrypt', 'decrypt')][string]$Action)

$ErrorActionPreference = 'Stop'
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$scope = [System.Security.Cryptography.DataProtectionScope]::CurrentUser
$entropy = [Text.Encoding]::UTF8.GetBytes('Akasha.ProjectBackup.v1')

function Decode([string]$Text) { return ,([Convert]::FromBase64String($Text)) }
function Encode([byte[]]$Bytes) { return [Convert]::ToBase64String($Bytes) }

$key = $null
$plain = $null
try {
    $result = switch ($Action) {
        'seal' {
            $plain = Decode $request.data
            @{ data = Encode ([System.Security.Cryptography.ProtectedData]::Protect($plain, $entropy, $scope)) }
        }
        'unseal' {
            $plain = [System.Security.Cryptography.ProtectedData]::Unprotect((Decode $request.data), $entropy, $scope)
            @{ data = Encode $plain }
        }
        'encrypt' {
            $key = [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
            $nonce = [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(12)
            $plain = Decode $request.data
            $cipher = [byte[]]::new($plain.Length)
            $tag = [byte[]]::new(16)
            $aes = [System.Security.Cryptography.AesGcm]::new($key, 16)
            try { $aes.Encrypt($nonce, $plain, $cipher, $tag, (Decode $request.aad)) }
            finally { $aes.Dispose() }
            @{
                cipher = Encode $cipher
                nonce = Encode $nonce
                tag = Encode $tag
                key = Encode ([System.Security.Cryptography.ProtectedData]::Protect($key, $entropy, $scope))
            }
        }
        'decrypt' {
            $key = [System.Security.Cryptography.ProtectedData]::Unprotect((Decode $request.key), $entropy, $scope)
            $cipher = Decode $request.cipher
            $plain = [byte[]]::new($cipher.Length)
            $aes = [System.Security.Cryptography.AesGcm]::new($key, 16)
            try { $aes.Decrypt((Decode $request.nonce), $cipher, (Decode $request.tag), $plain, (Decode $request.aad)) }
            finally { $aes.Dispose() }
            @{ data = Encode $plain }
        }
    }
    [Console]::Out.WriteLine(($result | ConvertTo-Json -Compress))
} finally {
    if ($null -ne $key) { [Array]::Clear($key) }
    if ($null -ne $plain) { [Array]::Clear($plain) }
}
