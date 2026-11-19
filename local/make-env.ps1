# Creates .env from local\env.local.template with a fresh random SECRET_KEY (first run only).
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) { exit 0 }
$bytes = New-Object byte[] 48
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$key = [Convert]::ToBase64String($bytes) -replace '[+/=]', ''
$text = (Get-Content (Join-Path $PSScriptRoot "env.local.template") -Raw) -replace '__GENERATED__', $key
[System.IO.File]::WriteAllText($envFile, $text)
Write-Host "Created .env with a new secret key."
