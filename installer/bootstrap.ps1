<#
  JARVIS bootstrap - runs during setup (and from "Repair JARVIS" in the Start menu).

  1. Finds Python 3.11+ on the PC (py launcher, PATH). If there is none, downloads the official
     Python 3.12 installer from python.org and installs a private copy inside the app folder
     (no admin rights, nothing added to PATH, nothing else on the PC touched).
  2. Creates a virtual environment in <AppDir>\venv.
  3. Installs everything in requirements.txt into it (internet needed), retrying on network errors.
  4. Downloads the Playwright browser(s) used for web automation (not fatal if it fails).
  5. Checks that the key packages import.

  Everything is logged to <AppDir>\install.log.
  Manual run:  powershell -ExecutionPolicy Bypass -File installer\bootstrap.ps1 -AppDir "C:\path\to\Jarvis"

  Keep this file ASCII only: Windows PowerShell 5.1 reads BOM-less files in the ANSI code page.
#>
param(
    [Parameter(Mandatory = $true)][string]$AppDir,
    [switch]$Firefox,        # also fetch Firefox for Playwright (extra ~80 MB)
    [switch]$SkipBrowsers    # used by CI
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'      # makes Invoke-WebRequest much faster
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.ServicePointManager]::SecurityProtocol } catch {}

$AppDir = (Resolve-Path -LiteralPath $AppDir).Path
$Log    = Join-Path $AppDir 'install.log'
$VenvDir = Join-Path $AppDir 'venv'
$VenvPy  = Join-Path $VenvDir 'Scripts\python.exe'
$PrivPy  = Join-Path $AppDir 'python\python.exe'
$Req     = Join-Path $AppDir 'requirements.txt'

# Python used only when the PC has none (official installer, version listed on python.org/ftp)
$FallbackUrl  = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$FallbackName = 'python-3.12.10-amd64.exe'

try { Start-Transcript -Path $Log -Force | Out-Null } catch {}

function Say([string]$m) { Write-Host ("[JARVIS] " + $m) }

# Runs a native command, streams its output to the console/log, returns its exit code.
# (Windows PowerShell 5.1 turns native stderr into terminating errors under 'Stop', so relax it here.)
function Run([string]$Exe, [string[]]$Arguments) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
}

# Returns "3.12" etc. when $Exe (+ launcher args) is a usable Python 3.11+, otherwise $null.
function Test-Python([string]$Exe, [string[]]$Pre) {
    try {
        $out = & $Exe @Pre -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $v = ("$out").Trim()
        $p = $v.Split('.')
        if ([int]$p[0] -eq 3 -and [int]$p[1] -ge 11) { return $v }
    } catch {}
    return $null
}

function Find-Python {
    # returns @{ Exe = ...; Pre = @(...); Version = ... } or $null
    if (Test-Path -LiteralPath $PrivPy) {
        $v = Test-Python $PrivPy @()
        if ($v) { return @{ Exe = $PrivPy; Pre = @(); Version = $v } }
    }
    $candidates = @(
        @{ Exe = 'py';      Pre = @('-3.12') },
        @{ Exe = 'py';      Pre = @('-3.13') },
        @{ Exe = 'py';      Pre = @('-3.11') },
        @{ Exe = 'python';  Pre = @() },
        @{ Exe = 'python3'; Pre = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        $v = Test-Python $c.Exe $c.Pre
        if ($v) { return @{ Exe = $c.Exe; Pre = $c.Pre; Version = $v } }
    }
    return $null
}

function Install-PrivatePython {
    Say "No Python 3.11+ found. Downloading Python 3.12 from python.org (about 27 MB)..."
    $tmp = Join-Path ([IO.Path]::GetTempPath()) $FallbackName
    $ok = $false
    for ($i = 1; $i -le 3 -and -not $ok; $i++) {
        try {
            Invoke-WebRequest -Uri $FallbackUrl -OutFile $tmp -UseBasicParsing
            if ((Get-Item $tmp).Length -gt 20MB) { $ok = $true }
        } catch {
            Say "Download attempt $i failed: $($_.Exception.Message)"
            Start-Sleep -Seconds 4
        }
    }
    if (-not $ok) { throw "Could not download Python. Check the internet connection and run 'Repair JARVIS' from the Start menu." }

    $sig = Get-AuthenticodeSignature -FilePath $tmp
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        throw "The downloaded Python installer failed its signature check, so it was not run."
    }

    Say "Installing a private copy of Python into the app folder..."
    $target = Join-Path $AppDir 'python'
    $argLine = "/quiet InstallAllUsers=0 TargetDir=`"$target`" PrependPath=0 Include_launcher=0 " +
               "Include_test=0 Include_doc=0 Include_pip=1 Shortcuts=0 AssociateFiles=0"
    $p = Start-Process -FilePath $tmp -ArgumentList $argLine -Wait -PassThru
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $PrivPy)) {
        throw "The Python installer exited with code $($p.ExitCode)."
    }
}

try {
    Say "App folder: $AppDir"
    if (-not (Test-Path -LiteralPath $Req)) { throw "requirements.txt not found in $AppDir" }

    # ---- 1. Python ----
    $py = Find-Python
    if (-not $py) {
        Install-PrivatePython
        $py = Find-Python
        if (-not $py) { throw "Python was installed but could not be started." }
    }
    Say ("Using Python " + $py.Version + " (" + $py.Exe + " " + ($py.Pre -join ' ') + ")")

    # ---- 2. virtual environment ----
    $needVenv = $true
    if (Test-Path -LiteralPath $VenvPy) {
        $vv = Test-Python $VenvPy @()
        if ($vv) { $needVenv = $false }
        else { Say "Existing environment is broken, rebuilding it."; Remove-Item -LiteralPath $VenvDir -Recurse -Force }
    }
    if ($needVenv) {
        Say "Creating the virtual environment..."
        $code = Run $py.Exe ($py.Pre + @('-m', 'venv', '--upgrade-deps', $VenvDir))
        if ($code -ne 0 -or -not (Test-Path -LiteralPath $VenvPy)) { throw "Could not create the virtual environment (exit $code)." }
    }

    # ---- 3. requirements ----
    Say "Installing requirements. This needs internet and takes a few minutes the first time..."
    $code = 1
    for ($i = 1; $i -le 3; $i++) {
        $code = Run $VenvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', $Req)
        if ($code -eq 0) { break }
        Say "pip did not finish (attempt $i of 3). Retrying in 5 seconds..."
        Start-Sleep -Seconds 5
    }
    if ($code -ne 0) { throw "Installing requirements failed (pip exit code $code). See install.log." }

    # pywin32 sometimes needs its post-install step (same check as setup.py)
    $c = Run $VenvPy @('-c', 'import win32com.client')
    if ($c -ne 0) {
        $post = Join-Path $VenvDir 'Scripts\pywin32_postinstall.py'
        if (Test-Path -LiteralPath $post) { Say "Registering pywin32..."; [void](Run $VenvPy @($post, '-install')) }
    }

    # ---- 4. Playwright browsers (optional, not fatal) ----
    if (-not $SkipBrowsers) {
        $browsers = @('chromium'); if ($Firefox) { $browsers += 'firefox' }
        Say ("Downloading browser(s) for web automation: " + ($browsers -join ', ') + " ...")
        $bc = Run $VenvPy (@('-m', 'playwright', 'install') + $browsers)
        if ($bc -ne 0) { Say "Browsers were not installed (exit $bc). Everything except browser automation still works. Run 'Repair JARVIS' later to retry." }
    }

    # ---- 5. sanity check ----
    $chk = Run $VenvPy @('-c', 'import PyQt6.QtWidgets, numpy, requests; from google import genai; print("imports ok")')
    if ($chk -ne 0) { throw "Installed, but the core packages do not import. See install.log." }

    Say "All done."
    try { Stop-Transcript | Out-Null } catch {}
    exit 0
}
catch {
    Say ("FAILED: " + $_.Exception.Message)
    Say "Details are in $Log"
    try { Stop-Transcript | Out-Null } catch {}
    Start-Sleep -Seconds 3
    exit 1
}
