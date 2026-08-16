# Simulateur de codage couleur NTSC · PAL · SECAM

Reconstruit le **vrai signal composite** d'une image — ligne par ligne,
échantillonné à quatre fois la sous-porteuse — puis le décode comme le ferait
un téléviseur.

Les artefacts célèbres de la télévision analogique — points rampants (*dot
crawl*), moirages irisés (*cross-color*), barres de Hanover, « feu » SECAM —
ne sont **jamais dessinés**. Ils émergent du calcul. C'est la seule façon
d'être sûr que ce qu'on regarde est vrai.

📘 **Le cours complet est dans [`docs/cours.md`](docs/cours.md)** — la théorie,
les mathématiques et les dérivations, illustrées par vingt figures produites
par le simulateur lui-même.

---

## Démarrage

```bash
pip install -r requirements.txt
```

Deux applications, deux usages :

```bash
run.bat            # banc de mesure : une image fixe, les instruments
play_video.bat     # lecteur vidéo temps réel, codage sur GPU
```

`play_video.bat` accepte aussi qu'on **glisse un fichier vidéo sur son icône**.
Sans passer par les lanceurs : `python -m gui` et `python -m lecteur`.

---

## Le banc de mesure

Une image fixe, analysée sous toutes les coutures. Il s'ouvre sur une mire de
barres de couleur en PAL ; chargez une image avec `Ctrl+O`, poussez le curseur
**phase différentielle** et regardez le vectorscope : le NTSC tourne, le PAL
pâlit, le SECAM ne bouge pas.

- **Trois vues liées** — original, décodé, différence amplifiée, à zoom et
  déplacement communs.
- **Un oscilloscope de ligne** — le signal composite réel de la ligne
  sélectionnée. Le bouton « voir quelques cycles » descend jusqu'à la
  sinusoïde de la sous-porteuse.
- **Un vectorscope** avec les cibles des barres 75 %, un analyseur de spectre
  qui montre l'entrelacement des peignes, un moniteur de forme d'onde, un
  profil de ligne décodé, et un bilan chiffré (ΔE\*ab, erreur de teinte,
  écrêtage, résolutions).
- **Tous les réglages normatifs** — bandes passantes, séparateur Y/C, ligne à
  retard PAL, bruit, phase et gain différentiels, écho, désaccord de
  sous-porteuse, primaires, gamma, piédestal, entrelacement.
- **Neuf mires** conçues pour révéler chacune un artefact, dont un piège à
  cross-color et un piège à dot crawl.
- **Comparaison des trois normes** dans des conditions identiques.

Sept normes sont disponibles : NTSC-M, NTSC-J, NTSC 1953, PAL-B/G, PAL-I,
SECAM-L et SECAM-D/K.

---

## Le lecteur vidéo

```bash
play_video.bat "C:\films\mon_film.mp4"   # ou glisser le fichier sur l'icône
run.bat video mon_film.mp4               # équivalent, via le lanceur général
```

**Commandes** — `Ctrl+O` ouvrir · `Espace` lire/pause · `1` `2` `3` changer de
norme **sans interrompre la lecture** · `←` `→` reculer ou avancer de cinq
secondes · `F11` plein écran. Le glisser-déposer fonctionne aussi dans la
fenêtre.

Trois shaders GLSL — un par norme — refont le même trajet que la bibliothèque,
mais sur le processeur graphique. Mesuré sur une RTX 3090, source 1920×1080 :

| Norme | Grille de travail | Temps GPU | Cadence |
|---|---|---|---|
| NTSC-M | 753 × 480 à 14,32 MHz | 0,90 ms | ≈ 1100 im/s |
| PAL-B/G | 921 × 576 à 17,73 MHz | 0,89 ms | ≈ 1120 im/s |
| SECAM-L | 916 × 576 à 17,63 MHz | 1,15 ms | ≈ 870 im/s |

Mesure faite par requête `GL_TIME_ELAPSED`, seule méthode honnête : chronométrer
des appels OpenGL avec l'horloge du processeur donne des cadences fantaisistes,
puisque les commandes sont empilées et rendent la main aussitôt.

Trois niveaux de qualité règlent la longueur des noyaux de filtrage, entre 13
et 31 coefficients — et jusqu'à 61 pour le piège de sous-porteuse. La **grille
de calcul** est réglable à part : normative (quatre points par cycle de
sous-porteuse), double, triple, ou calée sur la largeur réellement affichée.
Les longueurs de noyau suivent automatiquement, faute de quoi affiner la grille
*dégraderait* le résultat — un filtre se conçoit en fréquence normalisée, et
doubler l'échantillonnage sans rallonger le noyau divise par deux la largeur
relative de la bande à rejeter.

### L'enchaînement des passes

```
vidéo ──[codage]──> composite ──[décodage]──> image ──[présentation]──> écran
```

Le SECAM en demande dix de plus, imposées par la modulation de fréquence : la
phase y est l'**intégrale** du signal modulant depuis le début de la ligne, et
un fragment shader ne connaît que son propre pixel. Aucune formule locale n'a
pour dérivée le signal modulant. Une somme préfixe par doublement récursif
(Hillis-Steele) fournit donc cette intégrale en dix passes minuscules, chacune
ne lisant que deux texels — coût négligeable devant une seule passe de filtrage.

### Ce que le GPU concède

* les filtres analogiques (Butterworth d'ordre 4) deviennent des filtres à
  réponse finie — un shader ne peut pas être récursif ;
* le composite est échantillonné sur la grille de la norme plutôt qu'à quatre
  fois la sous-porteuse ;
* les préaccentuations SECAM basse fréquence sont omises, transparentes à
  l'aller-retour.

L'écart avec le simulateur de référence est **mesuré**, pas supposé
(`tests/test_shaders.py`) : ΔE\*ab médian de **0,70** en NTSC et **0,88** en PAL
— sous le seuil de perception — et **3,44** en SECAM, où le piège de
sous-porteuse à réponse finie n'égale pas le récursif de la référence.

### La définition du tube

Un écran plat restitue 4,4 MHz intégralement. **Aucun tube ne l'a jamais fait.**

Le spot du faisceau a une largeur finie et l'amplificateur vidéo sa propre
bande passante ; leur effet combiné se modélise par une gaussienne, réglée en
*lignes de résolution horizontale* — la grandeur que les constructeurs
affichaient. Un téléviseur d'appartement en donnait 300 à 400, et rendait donc
la sous-porteuse — qui tombe à 229 alternances par largeur d'image — à moins du
quart de son amplitude.

À quoi s'ajoute la géométrie de vision, qui n'est pas un détail :

| | Période du motif | Angle sous-tendu |
|---|---|---|
| Tube 4:3 de 60 cm, vu à 2,5 m | 2,62 mm | **3,6′ d'arc** |
| Moniteur de 50 cm, vu à 60 cm | ~11 mm | **12,5′ d'arc** |

L'œil résout environ une minute d'arc. Sur le téléviseur, le résidu frôlait le
seuil de visibilité ; sur un moniteur, il est trois fois et demie plus gros et
saute aux yeux. Mesuré sur une image blanche en SECAM, la simulation du tube le
ramène de 2,1 à 0,6 niveau sur 255.

### Le halo

Un tube ne se contente pas de flouter. Deux phénomènes de plus, réunis sous le
nom de *bloom* :

* la **halation** — la lumière du luminophore traverse une dalle de verre
  épaisse, s'y diffuse et se réfléchit sur la face avant. Une petite fraction
  de chaque point repart en un halo large et faible. Phénomène **linéaire**,
  proportionnel à la lumière émise ;
* l'**épanouissement du faisceau** — à fort courant le spot s'élargit et perd
  sa mise au point. Franchement **non linéaire** : le blanc bave sur les
  génériques quand les gris restent nets.

Le seuil réglable interpole entre les deux : à zéro tout diffuse, relevé seules
les hautes lumières s'épanouissent.

Trois passes au quart de la résolution — extraction avec réduction, flou
horizontal, flou vertical. Un flou gaussien étant séparable, deux passes de
treize échantillons valent une passe de cent soixante-neuf. **Coût mesuré :
1,09 ms sans halo, 1,12 ms avec**, soit dans le bruit de mesure.

Deux points d'implémentation :

* l'addition se fait en **lumière**, jamais sur les valeurs affichées. Deux
  sources lumineuses s'additionnent ; leurs racines gamma-ièmes non. Un halo
  calculé en valeurs affichées paraît trop fort dans les ombres et trop faible
  dans les hautes lumières — exactement l'inverse d'une dalle de verre ;
* le **seuil se règle en niveau affiché** mais se compare en lumière. Sans
  cette conversion, un réglage à 0,55 correspondrait en réalité à un gris de
  0,81 à l'écran.

Tous ces réglages agissent dans la passe de présentation, jamais dans la chaîne
de signal : ce sont des caractéristiques d'**affichage**, et la comparaison
avec le simulateur de référence reste ainsi exacte.

### Deux réglages qui ne se devinent pas

Le **piège de sous-porteuse** a sa propre longueur de noyau, bien plus grande
que les passe-bas : un passe-bas n'a qu'un flanc à former, un réjecteur en a
deux encadrant une bande étroite. Mesuré sur la bande SECAM, 21 coefficients ne
rejettent que 11 dB — la sous-porteuse resterait visible en clair. Il en faut
41 pour atteindre 34 dB, et le gabarit est conçu par équiondulation
(Parks-McClellan) plutôt que par fenêtrage, qui plafonnerait à 16 dB.

La longueur du noyau de **démodulation SECAM** n'est pas choisie mais
**calculée** (`longueur_minimale_discriminateur`). Le mélangeur transpose la
luminance continue à la fréquence de repos ; le passe-bas doit l'y rejeter. Or
la luminance vaut jusqu'à 1,0 quand la porteuse n'atteint que 0,24 : à 33 dB de
réjection — ce qu'obtiennent treize coefficients — il reste un résidu valant 9 %
de la porteuse, qui fausse la **phase**, c'est-à-dire précisément la grandeur
mesurée. Le SECAM décroche alors complètement.

Le son n'est pas géré : OpenCV ne décode que l'image.

---

## La bibliothèque

`tvcolor` est du numpy pur, sans aucune dépendance à Qt ni à OpenGL. Elle
s'utilise seule :

```python
from tvcolor import encoder_decoder, Parametres, mires, mesures
from tvcolor.canal import ParametresCanal

image = mires.barres_couleur(576, 768)

resultat = encoder_decoder(image, Parametres(
    norme="SECAM-L",
    canal=ParametresCanal(phase_differentielle=40.0, rapport_signal_bruit=32.0),
))

print(mesures.evaluer(resultat).resume())
```

La chaîne complète :

```
sRGB → linéaire → [primaires] → gamma caméra → R'G'B'
     → matriçage Y'UV / Y'IQ / Y'D'RD'B
     → limitation de bande normative
     → modulation sur sous-porteuse (quadrature, ou FM pour SECAM)
     → composite = Y + C
     → CANAL : bruit, phase et gain différentiels, écho
     → séparation Y/C (réjecteur | peigne | ligne à retard)
     → démodulation → matriçage inverse → écrêtage → sRGB
```

---

## Organisation

```
tvcolor/          bibliothèque de simulation (numpy pur)
  constantes.py     constantes normatives BT.470 / BT.601
  colorimetrie.py   primaires, blancs, gamma, CIELAB
  matrices.py       matriçage, et la dérivation des constantes de la norme
  filtres.py        limitation de bande, peignes, préaccentuations SECAM
  porteuse.py       l'horloge de sous-porteuse — le cœur horaire
  encodeur.py       R'G'B' → signal composite
  canal.py          les dégradations de la transmission
  decodeur.py       séparation Y/C, démodulation, mémoire de ligne
  pipeline.py       la chaîne complète
  mires.py          les neuf mires de test
  mesures.py        vectorscope, spectres, ΔE*ab, résolutions

shaders/          les trois shaders GLSL, un par norme
  commun.glsl       matriçage, horloge de sous-porteuse, noyaux
  ntsc.glsl         modulation en quadrature
  pal.glsl          idem, avec l'inversion de V ligne à ligne
  secam.glsl        modulation de fréquence, séquentielle
  scan.frag         somme préfixe : l'intégrale de phase du SECAM
  bloom.glsl        halation et épanouissement du faisceau
  presentation.frag mise à l'échelle, définition du tube, lignes, masque
  sommet.vert       triangle plein écran, sans tampon de sommets

lecteur/          le lecteur vidéo temps réel
  normes_gl.py      traduction des normes en uniformes, conception des noyaux
  gl_util.py        compilation, cibles de rendu, quad plein écran
  vue_gl.py         l'enchaînement des passes
  source_video.py   décodage vidéo dans un fil séparé
  app.py            la fenêtre

gui/              le banc de mesure PyQt5
docs/             le cours, ses vingt figures, et leurs générateurs
tests/            76 tests
```

---

## Vérification

```bash
run.bat tests          # ou : python -m pytest tests/ -v
```

76 tests : 23 sur le matriçage et la colorimétrie, 16 sur l'horloge de
sous-porteuse, 19 sur la chaîne complète, 18 sur les shaders. Ils ne se
contentent pas de vérifier que le code s'exécute — ils contrôlent les
**propriétés physiques** dont tout le reste découle :

- les coefficients 0,299 / 0,587 / 0,114 sont recalculés depuis les primaires
  NTSC 1953 et comparés à la norme ;
- les facteurs 0,492 et 0,877 sont redémontrés depuis la seule contrainte
  d'excursion [−1/3, +4/3] — et retombent à la sixième décimale ;
- la sous-porteuse NTSC tourne de 180,000° par ligne, à 10⁻⁹ près, y compris à
  la 480ᵉ ligne de la 100ᵉ image ;
- une image grise ne produit **aucune** chrominance en NTSC et en PAL, et le
  test correspondant vérifie qu'en SECAM elle en produit quand même — parce
  que c'est le cas ;
- le spectre simulé a bien ses raies de luminance sur les entiers et ses raies
  de chrominance sur les demi-entiers ;
- la ligne à retard PAL annule l'erreur de phase, le SECAM ignore le gain
  différentiel, le dot crawl apparaît, le cross-color colore une mire en noir
  et blanc ;
- les shaders retrouvent ce que calcule la bibliothèque, à ΔE près et borné.

Si un artefact n'apparaissait pas, ce serait la simulation qui aurait tort.

---

## Le lanceur

```
run.bat                banc de mesure
run.bat video [f.mp4]  lecteur vidéo
run.bat tests          suite de vérification
run.bat figures        régénère les vingt figures du cours
run.bat html           reconstruit docs/cours.html
run.bat tout           figures + html + tests
run.bat install        installe les dépendances
run.bat aide           rappelle tout ceci
```

Les figures et la page HTML se régénèrent aussi à la main :

```bash
python docs/generer_figures.py              # les vingt
python docs/generer_figures.py --seulement 05,07,10
python docs/construire_html.py
```

---

## Environnement

Python 3.10 ou plus récent. Le lecteur vidéo demande en outre un pilote
OpenGL 3.3.

Testé sous Windows 11 avec Python 3.13, PyQt5 5.15.11, numpy 1.26, scipy 1.15,
OpenCV 4.11, PyOpenGL 3.1, sur GeForce RTX 3090.
