@echo off
setlocal enableextensions
cd /d "%~dp0"
title Publish JARVIS to GitHub
echo.
echo  Publishing this folder to  https://github.com/KyZer-HADOC/Jarvis
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo  Git is not installed. Get it from https://git-scm.com/download/win , then run this file again.
  pause
  exit /b 1
)

if not exist ".git" git init
git branch -M main
git add -A

rem ---- Safety: never publish a key. These checks look at exactly what is about to be committed. ----
git ls-files --error-unmatch config/api_keys.json >nul 2>nul
if not errorlevel 1 (
  echo.
  echo  STOP: config/api_keys.json is about to be published. Nothing was pushed.
  echo        Run:  git rm --cached config/api_keys.json   and try again.
  pause
  exit /b 1
)
git grep --cached -I -l -E "gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}" >"%TEMP%\jarvis_secret_files.txt" 2>nul
if not errorlevel 1 (
  echo.
  echo  STOP: something that looks like an API key was found in these files. Nothing was pushed:
  type "%TEMP%\jarvis_secret_files.txt"
  echo  Remove the key from the file (and revoke it), then run this again.
  pause
  exit /b 1
)

git config user.email >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Git does not know who you are yet. Run these two lines once, then run this file again:
  echo      git config --global user.name  "Your Name"
  echo      git config --global user.email "you@example.com"
  pause
  exit /b 1
)

git diff --cached --quiet
if errorlevel 1 (
  git commit -m "JARVIS: new plugins, Windows installer and CI"
) else (
  echo  Nothing new to commit.
)

git remote remove origin >nul 2>nul
git remote add origin https://github.com/KyZer-HADOC/Jarvis.git
echo.
echo  Pushing. If a browser window opens, sign in to GitHub there.
git push -u origin main
if errorlevel 1 (
  echo.
  echo  The push failed. Make sure you are signed in as an account that can write to KyZer-HADOC/Jarvis.
  pause
  exit /b 1
)

echo.
echo  Done. Next:
echo    1. Open https://github.com/KyZer-HADOC/Jarvis/actions
echo    2. Click "Build Windows installer", then "Run workflow".
echo    3. When it turns green, open the run and download "Jarvis-Setup" from the Artifacts box.
echo.
pause
