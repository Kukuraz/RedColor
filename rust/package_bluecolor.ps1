param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
New-Item -ItemType Directory -Path $Destination -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Destination 'rust') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'target\release\redcolor.exe') -Destination (Join-Path $Destination 'BlueColor.exe') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'formula_helper.py') -Destination (Join-Path $Destination 'rust\formula_helper.py') -Force
foreach ($folder in @('rp', 'assets')) {
    Copy-Item -LiteralPath (Join-Path $root $folder) -Destination $Destination -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $root 'requirements.txt') -Destination $Destination -Force
Write-Output 'BlueColor packaged with formula modules. Python and requirements.txt dependencies are required for formulas.'
