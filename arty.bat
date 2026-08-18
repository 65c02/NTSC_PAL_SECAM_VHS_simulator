@echo off
rem ===========================================================================
rem  Arty — ecrire du son dans l'onde de l'image
rem
rem  Trois facons de s'en servir :
rem
rem    - double-cliquer sur ce fichier, puis Ctrl+O dans l'application ;
rem    - GLISSER UNE IMAGE SUR CETTE ICONE : il s'ouvre directement ;
rem    - en ligne de commande :  arty.bat "C:\images\photo.png"
rem
rem  Une fois l'application ouverte :
rem    Ctrl+O  ouvrir une image      Ctrl+E  exporter l'image obtenue
rem    Six operateurs a modulation de frequence, injectes dans l'onde du
rem    composite. Rien n'est dessine : la geometrie est deduite.
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
%PY% -c "import numpy, scipy, PyQt5, pyqtgraph, PIL" >nul 2>&1
if not errorlevel 1 goto :dependances_ok
echo.
echo   Il manque des dependances pour Arty.
echo   Il lui faut numpy, scipy, PyQt5, pyqtgraph et Pillow.
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
    echo   Arty — Ctrl+O pour ouvrir une image, ou une mire par defaut.
) else (
    echo   Image : %~nx1
)
echo   Reglez les six operateurs ; l'encadre predit le motif avant de le tracer.
echo.

rem %* transmet tous les arguments tels quels, guillemets compris, ce qui
rem couvre aussi le cas ou l'on depose plusieurs fichiers d'un coup :
rem l'application ouvre le premier qui existe.
%PY% -m arty %*
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
