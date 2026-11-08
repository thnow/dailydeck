# Downloads hidapi.dll (needed by python-elgato-streamdeck on Windows) from the official
# libusb/hidapi release into dailydeck/data/win32/, where Daily Deck finds it.
# Does nothing if the expected DLL is already there.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Version = "0.15.0"
$ZipSha256 = "D18C43EC9506A2F6D7FAA9C7E0A342C4B64FBAE521B71B5D4AC0777FD24DDA93"
$DllSha256 = @{
    x64 = "D4C05BA2138CB5259A7F796464B5EAA63B9F8F67BB5CB003F96989244EE01583"
    x86 = "D4C8E5F799FC5F57038D492F13A687471D5D353447EAD7E6CAE70E957FB55AE1"
}
$Arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }

$Target = Join-Path $PSScriptRoot "..\dailydeck\data\win32"
$Dll = Join-Path $Target "hidapi.dll"
if ((Test-Path $Dll) -and (Get-FileHash $Dll -Algorithm SHA256).Hash -eq $DllSha256[$Arch]) {
    Write-Host "hidapi $Version ($Arch) already in place"
    exit 0
}

$Tmp = Join-Path ([IO.Path]::GetTempPath()) ("hidapi-" + [Guid]::NewGuid())
New-Item -ItemType Directory -Force $Tmp, $Target | Out-Null
try {
    $Zip = Join-Path $Tmp "hidapi-win.zip"
    Invoke-WebRequest "https://github.com/libusb/hidapi/releases/download/hidapi-$Version/hidapi-win.zip" -OutFile $Zip
    if ((Get-FileHash $Zip -Algorithm SHA256).Hash -ne $ZipSha256) { throw "hidapi-win.zip: checksum mismatch" }
    Expand-Archive $Zip (Join-Path $Tmp "x")
    $Source = Join-Path $Tmp "x\$Arch\hidapi.dll"
    if ((Get-FileHash $Source -Algorithm SHA256).Hash -ne $DllSha256[$Arch]) { throw "hidapi.dll: checksum mismatch" }
    Copy-Item $Source $Target -Force
    Write-Host "hidapi $Version ($Arch) -> $((Resolve-Path $Target).Path)\hidapi.dll"
} finally {
    Remove-Item -Recurse -Force $Tmp
}
