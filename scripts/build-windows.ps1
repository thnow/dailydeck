# Builds dist\Daily Deck\ (PyInstaller) and dist\DailyDeck-<version>-windows-x64-setup.exe (Inno Setup).
#
#   powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1
#
# Needs uv (winget install astral-sh.uv) or $env:PYTHON pointing to a Python 3.13, and Inno Setup 6
# (winget install JRSoftware.InnoSetup) – ISCC.exe on PATH or in its default location.
# The build runs in a fresh venv under build\windows; nothing is installed globally.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$Build = Join-Path $Root "build\windows"
$Dist = Join-Path $Root "dist"
$PyInstallerVersion = "6.22.3"
$Version = (Select-String -Path "dailydeck\__init__.py" -Pattern '^__version__ = "(.+)"').Matches[0].Groups[1].Value

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Run {
    param([Parameter(ValueFromRemainingArguments = $true)] $Command)
    & $Command[0] $Command[1..($Command.Count - 1)]
    if ($LASTEXITCODE -ne 0) { throw "failed ($LASTEXITCODE): $($Command -join ' ')" }
}

Step "Daily Deck $Version (Windows x64)"
if (-not $env:PYTHON) {
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) { throw "set PYTHON=... or install uv (winget install astral-sh.uv)" }
    Run $uv python install -q 3.13
    $env:PYTHON = (& $uv python find 3.13).Trim()
}
Write-Host "    Python: $(& $env:PYTHON -V)"

$Iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
    $Iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
              "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }

if (Test-Path $Build) { Remove-Item -Recurse -Force $Build }
if (Test-Path "$Dist\Daily Deck") { Remove-Item -Recurse -Force "$Dist\Daily Deck" }
New-Item -ItemType Directory -Force $Build, $Dist | Out-Null

Step "build environment"
Run $env:PYTHON -m venv "$Build\venv"
$Py = "$Build\venv\Scripts\python.exe"
Run $Py -m pip install -q --upgrade pip
Run $Py -m pip install -q $Root "pyinstaller==$PyInstallerVersion"

Step "hidapi"
Run powershell -NoProfile -ExecutionPolicy Bypass -File "$Root\scripts\fetch-hidapi.ps1"
$Hidapi = Join-Path $Root "dailydeck\data\win32\hidapi.dll"

Step "icon and version resource"
$env:QT_QPA_PLATFORM = "offscreen"
$IconScript = @'
import sys
from io import BytesIO
from PIL import Image
from PySide6.QtCore import QBuffer, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

app = QGuiApplication(sys.argv[:1])
svg = QSvgRenderer(sys.argv[1])
images = []
for size in (16, 20, 24, 32, 40, 48, 64, 256):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    svg.render(painter)
    painter.end()
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    images.append(Image.open(BytesIO(bytes(buf.data()))).convert("RGBA"))
images[-1].save(sys.argv[2], format="ICO", sizes=[i.size for i in images], append_images=images[:-1])
'@
$IconScript | Set-Content -Encoding utf8 "$Build\make_icon.py"
$Ico = "$Build\DailyDeck.ico"
Run $Py "$Build\make_icon.py" "$Root\dailydeck\data\io.github.thnow.dailydeck.svg" $Ico

$Numbers = (($Version -split '[-~]')[0] -split '\.') + @(0, 0, 0, 0) | Select-Object -First 4
$Tuple = $Numbers -join ", "
$VersionFile = "$Build\version.txt"
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($Tuple), prodvers=($Tuple), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Thomas Wittmann'),
      StringStruct('FileDescription', 'Daily Deck'),
      StringStruct('FileVersion', '$Version'),
      StringStruct('InternalName', 'dailydeck'),
      StringStruct('LegalCopyright', 'Thomas Wittmann, GPL-3.0-or-later'),
      StringStruct('OriginalFilename', 'Daily Deck.exe'),
      StringStruct('ProductName', 'Daily Deck'),
      StringStruct('ProductVersion', '$Version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Encoding utf8 $VersionFile

Step "PyInstaller $PyInstallerVersion"
$env:DAILYDECK_VERSION = $Version
$env:DAILYDECK_HIDAPI = $Hidapi
$env:DAILYDECK_ICO = $Ico
$env:DAILYDECK_VERSION_FILE = $VersionFile
Run $Py -m PyInstaller --noconfirm --log-level WARN --workpath "$Build\work" --distpath $Dist `
    "$Root\packaging\windows\dailydeck.spec"
$App = "$Dist\Daily Deck"

Step "third-party notices"
Run $Py "$Root\scripts\third_party_notices.py" "$App\THIRD-PARTY-NOTICES.txt"

Step "smoke test"
$Cli = "$App\dailydeck.exe"
# the bundled default, never the configuration of whoever runs the build
$SmokeConfig = "$Build\smoke-config.toml"
Copy-Item "$Root\dailydeck\data\default_config.toml" $SmokeConfig
Run $Cli "--config" $SmokeConfig --dry-run "primary+shift+t"
Run $Cli "--config" $SmokeConfig --preview "$Build\preview" | Out-Null
$Rendered = @(Get-ChildItem "$Build\preview" -Filter *.png).Count
if ($Rendered -eq 0) { throw "preview rendered nothing" }
Write-Host "    $Rendered preview images"
if (-not (Test-Path "$App\_internal\dailydeck\data\win32\hidapi.dll")) { throw "hidapi.dll missing in the build" }
if (-not (Test-Path "$App\_internal\dailydeck\data\symbols\play.png")) { throw "symbols missing in the build" }
if (-not (Select-String -Path "$App\THIRD-PARTY-NOTICES.txt" -Pattern "GNU LESSER GENERAL PUBLIC LICENSE" -Quiet)) {
    throw "third-party notices incomplete"
}

# Optional code signing: SIGN_COMMAND is e.g. a signtool or Azure Trusted Signing call in which
# {file} is replaced by the file to sign. Without it Windows SmartScreen warns about an unknown publisher.
function Sign($file) {
    if (-not $env:SIGN_COMMAND) { return }
    Invoke-Expression ($env:SIGN_COMMAND.Replace("{file}", "`"$file`""))
    if ($LASTEXITCODE -ne 0) { throw "signing failed: $file" }
}
if ($env:SIGN_COMMAND) { Step "sign programs" }
Sign "$App\Daily Deck.exe"
Sign "$App\dailydeck.exe"

Step "installer (Inno Setup)"
Run $Iscc /Q "/DAppVersion=$Version" "/DSourceDir=$App" "/DIconFile=$Ico" "/DOutputDir=$Dist" `
    "$Root\packaging\windows\dailydeck.iss"
$Setup = "$Dist\DailyDeck-$Version-windows-x64-setup.exe"
Sign $Setup

Step "done"
"{0,8:N1} MB  {1}" -f ((Get-ChildItem $App -Recurse | Measure-Object Length -Sum).Sum / 1MB), $App
"{0,8:N1} MB  {1}" -f ((Get-Item $Setup).Length / 1MB), $Setup
