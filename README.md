# Simulateur de codage couleur NTSC · PAL · SECAM

Reconstruit le **vrai signal composite** d'une image — ligne par ligne,
échantillonné à quatre fois la sous-porteuse — puis le décode comme le ferait
un téléviseur.

Les artefacts célèbres de la télévision analogique — points rampants (*dot
crawl*), moirages irisés (*cross-color*), barres de Hanover, « feu » SECAM —
ne sont **jamais dessinés**. Ils émergent du calcul. C'est la seule façon
d'être sûr que ce qu'on regarde est vrai.

📘 **Le cours complet est dans [`docs/cours.md`](docs/cours.md)** — la théorie,
les mathématiques et les dérivations, illustrés par des figures produites par
le simulateur lui-même.

---

## Démarrage

```bash
pip install -r requirements.txt
python -m gui
```

L'interface s'ouvre sur une mire de barres de couleur en PAL. Chargez une image
(`Ctrl+O`), changez de norme, poussez le curseur **phase différentielle** et
regardez le vectorscope : le NTSC tourne, le PAL pâlit, le SECAM ne bouge pas.

## Ce que fait l'interface

- **Trois vues liées** — original, décodé, différence amplifiée, à zoom et
  déplacement communs.
- **Un oscilloscope de ligne** — le signal composite réel de la ligne
  sélectionnée. Le bouton « voir quelques cycles » descend jusqu'à la
  sinusoïde de la sous-porteuse.
- **Un vectorscope** avec les cibles des barres 75 %, un analyseur de spectre
  (qui montre l'entrelacement des peignes), un moniteur de forme d'onde, un
  profil de ligne décodé, et un bilan chiffré (ΔE\*ab, erreur de teinte,
  écrêtage, résolutions).
- **Tous les réglages normatifs** — bandes passantes, type de séparateur Y/C,
  ligne à retard PAL, bruit, phase et gain différentiels, écho, désaccord de
  sous-porteuse, primaires, gamma, piédestal, entrelacement.
- **Neuf mires de test** conçues pour révéler chaque artefact, dont un piège
  à cross-color et un piège à dot crawl.
- **Comparaison des trois normes** dans des conditions identiques, avec les
  métriques côte à côte.

## Ce que fait la bibliothèque

`tvcolor` est du numpy pur, sans aucune dépendance à Qt. Elle s'utilise seule :

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
  mires.py          les mires de test
  mesures.py        vectorscope, spectres, ΔE*ab, résolutions

gui/              l'interface PyQt5
docs/             le cours, et son générateur de figures
tests/            58 tests
```

## Vérification

```bash
python -m pytest tests/ -v
```

Les tests ne se contentent pas de vérifier que le code s'exécute. Ils
contrôlent les **propriétés physiques** dont tout le reste découle :

- les coefficients 0,299 / 0,587 / 0,114 sont recalculés depuis les primaires
  NTSC 1953 et comparés à la norme ;
- les facteurs 0,492 et 0,877 sont redémontrés depuis la contrainte
  d'excursion $[-1/3, +4/3]$ — et retombent à la sixième décimale ;
- la sous-porteuse NTSC tourne de 180,000° par ligne, à $10^{-9}$ près, y
  compris à la 480ᵉ ligne de la 100ᵉ image ;
- une image grise ne produit **aucune** chrominance en NTSC et en PAL, et le
  test correspondant vérifie qu'en SECAM elle en produit quand même — parce
  que c'est le cas ;
- le spectre simulé a bien ses raies de luminance sur les entiers et ses raies
  de chrominance sur les demi-entiers ;
- la ligne à retard PAL annule l'erreur de phase, le SECAM ignore le gain
  différentiel, le dot crawl apparaît, le cross-color colore une mire en noir
  et blanc.

Si un artefact n'apparaissait pas, ce serait la simulation qui aurait tort.

## Régénérer les figures du cours

```bash
python docs/generer_figures.py            # les vingt
python docs/generer_figures.py --seulement 05,07,10
```

## Environnement

Python 3.10 ou plus récent. Testé sous Windows 11 avec Python 3.13, PyQt5
5.15.11, numpy 1.26 et scipy 1.15.
"# NTSC_PAL_SECAM" 
