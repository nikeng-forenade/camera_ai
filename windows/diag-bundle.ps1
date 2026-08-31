# Camera AI - kontrollera vad som paketerades i dist\CameraAI\_internal
$out = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\bundle_check.txt"))
"" | Set-Content -Path $out -Encoding UTF8
function Log($m) { $m | Add-Content -Path $out -Encoding UTF8 }

$i = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\dist\CameraAI\_internal"))
Log ("internal: " + $i)
foreach ($m in @("paho", "fastapi", "uvicorn", "ultralytics", "openvino", "ha_client", "app", "analyzer", "config", "webview", "pystray", "static", "yolo11n.pt")) {
    $hit = Get-ChildItem $i -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Name -like ($m + "*") } | Select-Object -First 1
    if ($hit) { Log ("OK   " + $m + "  -> " + $hit.FullName.Substring($i.Length)) } else { Log ("SAKNAS " + $m) }
}
