[CmdletBinding()]
param(
    [ValidateSet('Build', 'Clean')]
    [string]$Action = 'Build'
)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if ($Action -eq 'Clean') {
        & latexmk -C main.tex
    }
    else {
        & latexmk -pdf main.tex
    }

    if ($LASTEXITCODE -ne 0) {
        throw "LaTeX build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
