# Gera o executável Windows do atendeIO: dist\atendeIO\atendeIO.exe e dist\atendeIO-windows.zip
# Uso (na raiz do repositório, em PowerShell):  powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv-build\Scripts\python.exe"

function Invoke-Pnpm {
    # pnpm no PATH, ou o corepack que vem com o Node (corepack pnpm), sem instalar nada
    if (Get-Command pnpm -ErrorAction SilentlyContinue) { & pnpm @args }
    elseif (Get-Command corepack -ErrorAction SilentlyContinue) { & corepack pnpm @args }
    else { throw "Nem pnpm nem corepack encontrados. Instale o Node 24+ (https://nodejs.org)." }
    if ($LASTEXITCODE -ne 0) { throw "pnpm $args falhou (código $LASTEXITCODE)." }
}

$nodeMajor = [int]((node --version) -replace '^v(\d+)\..*', '$1')
if ($nodeMajor -lt 24) { throw "Node 24+ é obrigatório (tem v$nodeMajor). Abra um terminal novo se acabou de atualizar." }

Write-Host "[1/5] Interface Ionic/Angular (frontend\www)"
Push-Location frontend
Invoke-Pnpm install --frozen-lockfile
Invoke-Pnpm run build:web
Pop-Location

Write-Host "[2/5] Ambiente de build (.venv-build)"
if (-not (Test-Path $py)) { python -m venv .venv-build }
& $py -m pip install --upgrade pip
# torch CPU primeiro: o pip não puxa a versão com CUDA (centenas de MB a mais)
& $py -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
& $py -m pip install -r requirements-build.txt -r requirements-dev.txt

Write-Host "[3/5] Testes do backend"
& $py -m pytest -q

Write-Host "[4/5] PyInstaller"
& $py -m PyInstaller --noconfirm atendeio.spec

Write-Host "[5/5] Zip para entrega"
Compress-Archive -Path dist\atendeIO -DestinationPath dist\atendeIO-windows.zip -Force
Write-Host "Pronto: dist\atendeIO\atendeIO.exe e dist\atendeIO-windows.zip"
