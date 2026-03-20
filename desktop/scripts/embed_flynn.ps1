$ErrorActionPreference = 'Stop'
$regPath = 'C:\Users\Dani\clawd\github-sourcer-desktop\src\assets\fonts\Flynn.otf'
$boldPath = 'C:\Users\Dani\clawd\github-sourcer-desktop\src\assets\fonts\Flynn Bold.otf'
$outPath = 'C:\Users\Dani\clawd\github-sourcer-desktop\src\fonts_embed.css'

$reg = [Convert]::ToBase64String([IO.File]::ReadAllBytes($regPath))
$bold = [Convert]::ToBase64String([IO.File]::ReadAllBytes($boldPath))

$css = @()
$css += "@font-face {"
$css += "  font-family: 'FlynnEmbedded';"
$css += "  src: url('data:font/otf;base64,$reg') format('opentype');"
$css += "  font-weight: 400;"
$css += "  font-style: normal;"
$css += "}"
$css += "@font-face {"
$css += "  font-family: 'FlynnEmbedded';"
$css += "  src: url('data:font/otf;base64,$bold') format('opentype');"
$css += "  font-weight: 700;"
$css += "  font-style: normal;"
$css += "}"
$cssText = ($css -join "`n") + "`n"

Set-Content -Encoding UTF8 -Path $outPath -Value $cssText
Write-Host "Wrote $outPath"