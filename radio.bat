@echo off
rem ===========================================================================
rem  Simulateur radio — AM, FM et BLU, de l'emetteur au haut-parleur
rem
rem  Trois facons de s'en servir :
rem
rem    - double-cliquer sur ce fichier, puis Ctrl+O dans l'application ;
rem    - GLISSER UN FICHIER AUDIO SUR CETTE ICONE : il s'ouvre directement ;
rem    - en ligne de commande :  radio.bat "C:\films\mon_film.mp4"
rem
rem  Une fois l'application ouverte :
rem    Ctrl+O  ouvrir un fichier     Ctrl+E  exporter en WAV ou en MP3
rem    Le menu Service choisit la radio simulee ; les reglages agissent
rem    pendant la lecture.
rem
rem  IMPORTANT : ce fichier doit rester en fins de ligne CRLF. En LF seul,
rem  cmd.exe se decale d'un octet apres chaque saut et mange le debut des
rem  lignes suivant un goto -- le script part en vrille sans message clair.
rem ===========================================================================

for /f "tokens=2 delims=:" %%C in ('chcp') do set "_PAGE=%%C"
set "_PAGE=%_PAGE: =%"
chcp 65001 >nul 2>&1

rem Le glisser-deposer transmet un chemin absolu, mais le repertoire courant
rem reste celui de l'Explorateur. On se replace donc dans le projet.
pushd "%~dp0"

rem --------------------------------------------------------------- Python ---
set "PY="
python -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :python_trouve
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
:python_trouve
if not defined PY goto :pas_de_python

rem ---------------------------------------------------------- dependances ---
%PY% -c "import numpy, scipy, PyQt5, pyqtgraph, av, sounddevice" >nul 2>&1
if not errorlevel 1 goto :dependances_ok
echo.
echo   Il manque des dependances pour le simulateur radio.
echo   Il lui faut numpy, scipy, PyQt5, pyqtgraph, av (PyAV) et sounddevice.
echo.
echo   Installez-les avec :   run.bat install
echo.
set "ERREUR=1"
goto :fin
:dependances_ok

rem -------------------------------------------------------------- fichier ---
rem %~1 retire les guillemets que l'Explorateur ajoute autour des chemins
rem contenant des espaces ; sans cela, le test d'existence echouerait sur
rem tout fichier range dans "Mes videos".
if "%~1"=="" goto :lancer
if exist "%~1" goto :lancer

echo.
echo   Fichier introuvable :
echo     %~1
echo.
set "ERREUR=1"
goto :fin

rem --------------------------------------------------------------- lancer ---
:lancer
echo.
if "%~1"=="" (
    echo   Simulateur radio — Ctrl+O pour ouvrir un fichier audio.
) else (
    echo   Source : %~nx1
)
echo   Menu Service : AM, FM, CB, talkie-walkie, VHF marine, VHF aeronautique.
echo.

rem %* transmet tous les arguments tels quels, guillemets compris, ce qui
rem couvre aussi le cas ou l'on depose plusieurs fichiers d'un coup :
rem l'application ouvre le premier qui existe.
%PY% -m radio %*
goto :fin

rem =========================================================================
:pas_de_python
echo.
echo   Python est introuvable.
echo   Installez Python 3.10 ou plus recent depuis python.org,
echo   en cochant "Add Python to PATH" pendant l'installation.
echo.
goto :fin

rem =========================================================================
:fin
set "CODE=%errorlevel%"
if defined ERREUR set "CODE=%ERREUR%"
popd
chcp %_PAGE% >nul 2>&1

rem Pause seulement en cas d'echec : sur un double-clic reussi, c'est le
rem simulateur lui-meme qui tient la fenetre ouverte tant qu'il tourne. En cas
rem d'erreur en revanche, le message doit rester lisible au lieu de
rem disparaitre en un dixieme de seconde.
if not "%CODE%"=="0" pause
exit /b %CODE%
