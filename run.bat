@echo off
rem ===========================================================================
rem  Simulateur de codage couleur NTSC / PAL / SECAM
rem
rem  Usage :   run.bat [commande] [argument]
rem
rem    (rien)     lance le banc de mesure (interface d'analyse d'images)
rem    video      lance le lecteur video temps reel sur GPU
rem    radio      lance le simulateur radio (AM, FM, BLU)
rem    tests      execute la suite de verification
rem    figures    regenere les figures du cours
rem    html       reconstruit la page HTML du cours
rem    tout       figures + html + tests
rem    install    installe les dependances
rem    aide       affiche ce message
rem
rem  IMPORTANT : ce fichier doit rester en fins de ligne CRLF. En LF seul,
rem  cmd.exe se decale d'un octet apres chaque saut et mange le debut des
rem  lignes suivant un goto -- le script part en vrille sans message clair.
rem ===========================================================================

rem La console Windows n'affiche pas les accents en page de codes 850 ; on
rem bascule en UTF-8 et on restaure l'etat initial en sortant, pour ne pas
rem laisser la fenetre de l'utilisateur dans un autre reglage que le sien.
for /f "tokens=2 delims=:" %%C in ('chcp') do set "_PAGE=%%C"
set "_PAGE=%_PAGE: =%"
chcp 65001 >nul 2>&1

rem Le script s'execute toujours depuis le dossier du projet, quel que soit
rem l'endroit d'ou on l'appelle.
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

rem ------------------------------------------------------------- commande ---
set "CMD=%~1"
if "%CMD%"=="" set "CMD=mesure"

if /i "%CMD%"=="mesure"   goto :mesure
if /i "%CMD%"=="gui"      goto :mesure
if /i "%CMD%"=="video"    goto :video
if /i "%CMD%"=="radio"    goto :radio
if /i "%CMD%"=="lecteur"  goto :video
if /i "%CMD%"=="tests"    goto :tests
if /i "%CMD%"=="test"     goto :tests
if /i "%CMD%"=="figures"  goto :figures
if /i "%CMD%"=="html"     goto :html
if /i "%CMD%"=="tout"     goto :tout
if /i "%CMD%"=="all"      goto :tout
if /i "%CMD%"=="install"  goto :install
if /i "%CMD%"=="aide"     goto :aide
if /i "%CMD%"=="help"     goto :aide
if /i "%CMD%"=="-h"       goto :aide
if /i "%CMD%"=="--help"   goto :aide
if /i "%CMD%"=="/?"       goto :aide

echo.
echo   Commande inconnue : %CMD%
rem On affiche l'aide, mais on sort en erreur : un script appelant doit
rem pouvoir distinguer « voici l'aide » de « votre commande n'existe pas ».
set "ERREUR=2"
goto :aide

rem =========================================================================
:mesure
call :verifier_dependances
if errorlevel 1 goto :fin
echo.
echo   Banc de mesure — chargez une image, comparez les trois normes.
echo   (fermez cette fenetre pour quitter)
echo.
%PY% -m gui
goto :fin

rem =========================================================================
:video
call :verifier_dependances
if errorlevel 1 goto :fin
%PY% -c "import OpenGL, av, sounddevice" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Il manque une dependance du lecteur video.
    echo   Il lui faut PyOpenGL, av (PyAV) et sounddevice.
    echo   Lancez :  run.bat install
    echo.
    set "ERREUR=1"
    goto :fin
)
echo.
echo   Lecteur video — Ctrl+O pour ouvrir un fichier, 1/2/3 pour changer
echo   de norme, Espace pour lire ou mettre en pause, F11 pour le plein ecran.
echo.
%PY% -m lecteur %2 %3 %4
goto :fin

rem =========================================================================
:radio
call :verifier_dependances
if errorlevel 1 goto :fin
%PY% -c "import pyqtgraph, av, sounddevice" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Il manque une dependance du simulateur radio.
    echo   Il lui faut pyqtgraph, av (PyAV) et sounddevice.
    echo   Lancez :  run.bat install
    echo.
    set "ERREUR=1"
    goto :fin
)
echo.
echo   Simulateur radio - Ctrl+O pour ouvrir un fichier audio,
echo   menu Service pour choisir la radio, Ctrl+E pour exporter.
echo.
%PY% -m radio %2 %3 %4
goto :fin

rem =========================================================================
:tests
call :verifier_dependances
if errorlevel 1 goto :fin
echo.
echo   Verification de la simulation
echo   -----------------------------
%PY% -m pytest tests/ -q
goto :fin

rem =========================================================================
:figures
call :verifier_dependances
if errorlevel 1 goto :fin
echo.
echo   Generation des figures du cours (environ 80 s)
echo   ---------------------------------------------
%PY% docs\generer_figures.py
goto :fin

rem =========================================================================
:html
call :verifier_dependances
if errorlevel 1 goto :fin
echo.
echo   Construction de la page HTML du cours
echo   -------------------------------------
%PY% docs\construire_html.py
goto :fin

rem =========================================================================
:tout
call :verifier_dependances
if errorlevel 1 goto :fin
echo.
echo   [1/3] Figures
%PY% docs\generer_figures.py
if errorlevel 1 goto :fin
echo.
echo   [2/3] Page HTML
%PY% docs\construire_html.py
if errorlevel 1 goto :fin
echo.
echo   [3/3] Tests
%PY% -m pytest tests/ -q
goto :fin

rem =========================================================================
:install
echo.
echo   Installation des dependances
echo   ----------------------------
%PY% -m pip install -r requirements.txt
goto :fin

rem =========================================================================
:aide
echo.
echo   Simulateur de codage couleur NTSC / PAL / SECAM
echo.
echo     run.bat             banc de mesure : une image, trois normes, les
echo                         instruments (oscilloscope, vectorscope, spectre)
echo     tv.bat              lecteur video temps reel, code sur GPU
echo     tv.bat film.mp4     ouvre directement ce fichier
echo     radio.bat           simulateur radio : AM, FM, CB, talkie, VHF
echo                         (run.bat video et run.bat radio font pareil)
echo.
echo     run.bat tests       execute la suite de verification
echo     run.bat figures     regenere les figures du cours
echo     run.bat html        reconstruit docs\cours.html
echo     run.bat tout        figures + html + tests
echo     run.bat install     installe les dependances
echo.
echo   Le cours se lit dans docs\cours.md ou docs\cours.html
echo.
goto :fin

rem =========================================================================
:verifier_dependances
rem Un import rate ici donne un message utile ; sans cette verification,
rem l'utilisateur recevrait une trace d'erreur Python de vingt lignes.
%PY% -c "import numpy, scipy, PyQt5, pyqtgraph, PIL" >nul 2>&1
if not errorlevel 1 exit /b 0
echo.
echo   Il manque des dependances.
echo   Lancez d'abord :  run.bat install
echo.
exit /b 1

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

rem On ne met en pause qu'en cas d'echec, et c'est un choix delibere.
rem
rem L'astuce repandue qui consiste a inspecter %cmdcmdline% pour reconnaitre
rem un double-clic ne fonctionne pas : PowerShell lance lui aussi le script
rem par    cmd /c ""C:\...\run.bat" ...   avec exactement la meme forme que
rem l'Explorateur. Le test a ete essaye, mesure, et il donne un faux positif.
rem
rem La regle retenue est donc simple et previsible :
rem   - succes     : aucune pause. Sur un double-clic sans argument, c'est
rem                  l'interface qui tient la fenetre ouverte tant qu'elle
rem                  tourne, ce qui est exactement le comportement voulu ;
rem   - echec      : pause, pour qu'un message d'erreur ne disparaisse pas
rem                  en un dixieme de seconde. Dans un terminal ou dans un
rem                  script, l'entree standard n'est pas une console et la
rem                  pause rend la main immediatement, sans rien bloquer.
if not "%CODE%"=="0" pause
exit /b %CODE%
