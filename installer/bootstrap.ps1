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
    [switch]$Browsers,       # fetch Chromium for Playwright (about 200 MB)
    [switch]$Firefox,        # fetch Firefox for Playwright (about 80 MB)
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
    # On Windows PowerShell 5.1, a missing py.exe runtime can turn native stderr
    # into a terminating PowerShell error when ErrorActionPreference is Stop.
    # Suppress that expected probe failure and continue checking other runtimes.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $out = & $Exe @Pre -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $v = ("$out").Trim()
        $p = $v.Split('.')
        if ([int]$p[0] -eq 3 -and [int]$p[1] -ge 11) { return $v }
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $previousPreference
    }
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
    Say "Installing requirements. This needs internet and may take a few minutes the first time..."
    $code = 1
    for ($i = 1; $i -le 3; $i++) {
        $code = Run $VenvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '--prefer-binary', '--retries', '5', '--timeout', '45', '-r', $Req)
        if ($code -eq 0) { break }
        Say "pip did not finish (attempt $i of 3). Retrying in 5 seconds..."
        Start-Sleep -Seconds 5
    }

    # A single optional plugin dependency can fail to resolve on a particular Python
    # version or mirror. Recover per requirement so it doesn't block installing the
    # core assistant. Truly required imports are checked below and still stop setup.
    $failedRequirements = @()
    if ($code -ne 0) {
        Say "The combined dependency install failed. Trying individual packages so one optional package cannot block the whole setup..."
        foreach ($line in Get-Content -LiteralPath $Req) {
            # Strip inline comments before passing a requirement as a single CLI argument.
            # This matters for entries such as "send2trash  # optional-plugin reason".
            $spec = ($line -split '\s+#', 2)[0].Trim()
            if (-not $spec -or $spec.StartsWith('#') -or $spec.StartsWith('-')) { continue }
            Say ("Installing package: " + $spec)
            $one = 1
            for ($attempt = 1; $attempt -le 2; $attempt++) {
                $one = Run $VenvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '--prefer-binary', '--retries', '5', '--timeout', '45', $spec)
                if ($one -eq 0) { break }
                Start-Sleep -Seconds 2
            }
            if ($one -ne 0) { $failedRequirements += $spec; Say ("Skipped package after retry: " + $spec) }
        }
    }

    # pywin32 sometimes needs its post-install step (same check as setup.py)
    $c = Run $VenvPy @('-c', 'import win32com.client')
    if ($c -ne 0) {
        $post = Join-Path $VenvDir 'Scripts\pywin32_postinstall.py'
        if (Test-Path -LiteralPath $post) { Say "Registering pywin32..."; [void](Run $VenvPy @($post, '-install')) }
    }

    # ---- 4. Playwright browsers (optional; skipped by default to save data) ----
    $browserNames = @()
    if ($Browsers) { $browserNames += 'chromium' }
    if ($Firefox) { $browserNames += 'firefox' }
    if (-not $SkipBrowsers -and $browserNames.Count -gt 0) {
        Say ("Downloading optional browser(s) for web automation: " + ($browserNames -join ', ') + " ...")
        $bc = Run $VenvPy (@('-m', 'playwright', 'install') + $browserNames)
        if ($bc -ne 0) {
            Say "Browsers were not installed (exit $bc). The rest of JARVIS is ready; run Repair JARVIS with -Browsers to retry."
        }
    } else {
        Say "Skipping optional Playwright browser download to save data. Website automation needs Chromium; it can be installed later."
    }

    # ---- 5. sanity check ----
    $chk = Run $VenvPy @('-c', 'import PyQt6.QtWidgets, numpy, sounddevice, requests, psutil, pyautogui, pyperclip; from google import genai')
    if ($chk -ne 0) { throw "Installed, but required core packages do not import. See install.log." }
    Say "Core package imports passed."

    # Import the real application before reporting success. This catches a missing
    # top-level dependency that a small list of core imports would otherwise miss.
    Say "Checking that JARVIS itself can start..."
    $appCheck = Run $VenvPy @('-c', 'import main')
    if ($appCheck -ne 0) { throw "A package is missing or incompatible with JARVIS startup. See install.log, then run Repair JARVIS." }
    Say "JARVIS startup imports passed."

    if ($failedRequirements.Count -gt 0) {
        Say ("WARNING: " + $failedRequirements.Count + " optional/package requirement(s) failed: " + ($failedRequirements -join '; '))
        Say "JARVIS core installed, but plugins depending on those packages may be unavailable. See install.log."
    }
    Say "All done."
    try { Stop-Transcript | Out-Null } catch {}
    exit 0
}
catch {
    Say ("FAILED at bootstrap line " + $_.InvocationInfo.ScriptLineNumber + ": " + $_.Exception.Message)
    if ($_.ScriptStackTrace) { Say ("PowerShell trace: " + $_.ScriptStackTrace) }
    Say "Details are in $Log"
    try { Stop-Transcript | Out-Null } catch {}
    Start-Sleep -Seconds 3
    exit 1
}
