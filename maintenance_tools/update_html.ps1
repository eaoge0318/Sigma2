
$filePath = "c:\Users\foresight\Desktop\MantleTemp\pythaon\Sigma2\dashboard.html"
$cssLink = '    <link rel="stylesheet" href="/static/css/styles.css">'
$jsScript = '    <script src="/static/js/dashboard.js"></script>'

$lines = Get-Content -Path $filePath -Encoding UTF8

$newLines = @()
$inStyle = $false
$inScript = $false
$styleReplaced = $false
$scriptReplaced = $false

for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    $stripped = $line.Trim()

    # Style Block Logic
    if (-not $styleReplaced -and $stripped -eq '<style>') {
        $inStyle = $true
        $newLines += $cssLink
        $styleReplaced = $true
        continue
    }

    if ($inStyle) {
        if ($stripped -eq '</style>') {
            $inStyle = $false
        }
        continue
    }

    # Script Block Logic
    # Identify Main Script: <script> alone, no src
    if (-not $scriptReplaced -and $stripped -eq '<script>' -and $line -notmatch 'src=') {
        $inScript = $true
        $newLines += $jsScript
        $scriptReplaced = $true
        continue
    }

    if ($inScript) {
        if ($stripped -eq '</script>') {
            $inScript = $false
        }
        continue
    }

    $newLines += $line
}

$newLines | Set-Content -Path $filePath -Encoding UTF8
Write-Host "dashboard.html updated successfully via PowerShell."
