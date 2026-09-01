# Kolla om Microsoft Edge WebView2 Runtime finns (krav for pywebview)
$out = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\webview2_check.txt"))
"" | Set-Content -Path $out -Encoding UTF8
function Log($m) { $m | Add-Content -Path $out -Encoding UTF8 }

$paths = @(
    "$env:ProgramFiles(x86)\Microsoft\EdgeWebView\Application\msedgewebview2.exe",
    "$env:ProgramFiles\Microsoft\EdgeWebView\Application\msedgewebview2.exe"
)
$found = $false
foreach ($p in $paths) {
    if (Test-Path $p) {
        Log ("WEBSITE2 FINNS: " + $p)
        $found = $true
    }
}
if (-not $found) {
    Log "WEBSITE2 SAKNAS - pywebview kommer inte att fungera (fallback till webbläsare)."
    Log "Installera: https://developer.microsoft.com/en-us/microsoft-edge/webview2/"
}
