# Waits until the app answers (first start builds the image and can take a while).
for ($i = 0; $i -lt 180; $i++) {
  try { Invoke-WebRequest "http://localhost:8080/api/health" -UseBasicParsing -TimeoutSec 3 | Out-Null; exit 0 }
  catch { Start-Sleep -Seconds 5; if ($i % 6 -eq 0) { Write-Host "  still starting..." } }
}
exit 1
