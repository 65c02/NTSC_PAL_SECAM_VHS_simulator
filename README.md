# Simulateur de codage couleur NTSC · PAL · SECAM

Reconstruit le **vrai signal composite** d'une image — ligne par ligne,
échantillonné à quatre fois la sous-porteuse — puis le décode comme le ferait
un téléviseur.

Les artefacts célèbres de la télévision analogique — points rampants (*dot
crawl*), moirages irisés (*cross-color*), barres de Hanover, « feu » SECAM —
ne sont **jamais dessinés**. Ils émergent du calcul. C'est la seule façon
d'être sûr que ce qu'on regarde est vrai.

📘 **Le cours complet est dans [`docs/cours.md`](docs/cours.md)** — la théorie,
les mathématiques et les dérivations, illustrées par vingt-cinq figures
produites par le simulateur lui-même. Le **chapitre 12** est consacré aux
shaders — comment la même chaîne a été portée sur carte graphique, ce qu'un
fragment shader interdit, et ce que le portage a coûté en fidélité — et le
**chapitre 13** au son, qui ne voyageait pas dans le signal vidéo mais sur sa
propre porteuse. Le **chapitre 14** ajoute le magnétoscope, qui ne se contentait
pas de transporter le signal : il le démontait. Le **chapitre 15** remonte enfin
tout en amont, jusqu'à la caméra à tubes et à sa queue de comète — ces grandes
traînées blanches que laissaient les reflets dans les émissions musicales des
années soixante-dix.

---

## Démarrage

```bash
pip install -r requirements.txt
```

Quatre applications, quatre usages :

```bash
run.bat     # banc de mesure : une image fixe, les instruments
tv.bat      # lecteur vidéo temps réel, codage sur GPU
radio.bat   # simulateur radio : AM, FM, CB, talkie, VHF marine et aéro
arty.bat    # injecte un son dans l'onde de l'image, et regarde ce qu'il devient
```

`tv.bat`, `radio.bat` et `arty.bat` acceptent qu'on **glisse un fichier sur leur
icône**. Sans passer par les lanceurs : `python -m gui`, `python -m lecteur`,
`python -m radio`, `python -m arty`.

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
- **Douze mires** conçues pour révéler chacune un artefact — dont un piège à
  cross-color, un piège à dot crawl, et trois cartes de test nationales.
- **Un magnétoscope VHS**, entre l'antenne et le téléviseur — sa vraie place.
- **Une caméra à tubes**, tout en amont — rémanence, désalignement des trois
  tubes, et queue de comète sur les reflets.
- **Comparaison des trois normes** dans des conditions identiques.

Les réglages sont en cinq onglets — **Image**, **Caméra**, **Bruit**,
**Magnétoscope**, **Son**. Le bruit a le sien pour une raison précise : il n'appartient pas à
l'image. Il y a un canal, une densité de bruit, et deux porteuses qui y
puisent.

Sept normes sont disponibles : NTSC-M, NTSC-J, NTSC 1953, PAL-B/G, PAL-I,
SECAM-L et SECAM-D/K.

### La cassette VHS

Un magnétoscope n'enregistre pas le composite tel quel : il le **démonte**. La
bande ne tient pas cinq mégahertz, et le contact tête/bande fluctue trop pour
qu'un enregistrement en amplitude soit envisageable. D'où le procédé
*color-under* : séparer Y et C, moduler la luminance en fréquence, et
**transposer la chrominance sous elle**, à 627 kHz.

Le prix se lit dans un seul chiffre. La chrominance transposée ne dispose plus
que de 400 kHz contre 1,3 MHz à l'antenne, et sa définition horizontale tombe à
**une trentaine de lignes** quand la luminance en garde 240 — un facteur huit.
C'est ce qui trahit une cassette même quand tout le reste est propre.

| | bande luma | bande chroma | définition chroma |
|---|---|---|---|
| direct | 5,0 MHz | 1,3 MHz | 100 lignes |
| VHS SP | 3,0 MHz | 0,40 MHz | 31 lignes |
| VHS LP | 2,6 MHz | 0,35 MHz | 27 lignes |
| VHS EP | 2,0 MHz | 0,29 MHz | 22 lignes |

S'y ajoutent la gigue de défilement — les verticales ondulent —, la commutation
des têtes en bas de l'image, les pertes de signal, le liseré clair au bord des
contours, et le cumul des générations de copie.

**Tous les taux sont calés sur des chiffres réels**, jamais réglés à l'œil.
Une bande VHS neuve est spécifiée à dix ou vingt pertes de signal par *minute* ;
le réglage par défaut en produit 1,5 par seconde, et le maximum 75. La gigue
vaut 0,9 échantillon au milieu de l'image — moins d'un pixel — et quatre fois
plus sur les premières lignes, là où l'asservissement du tambour n'est pas
encore stabilisé : c'est le « drapeau », la signature qu'on reconnaît
instantanément. Le §14.7 du cours donne toutes les formules et leur origine.

La gigue ne fait **pas** tourner la teinte, et c'est le point qui a coûté deux
fautes : un magnétoscope régénère sa porteuse de relecture à partir du signal
lu, si bien que l'erreur de base de temps s'annule dans la démodulation. Le
décalage porte donc sur l'enveloppe de la chrominance, jamais sur sa porteuse.

### Trois mires nationales

Au catalogue, à côté des mires d'instrument : la **mire TDF** française, la
**Test Card F** de la BBC et la **mire de définition NHK** japonaise.

Leur disposition est une reconstruction — elle reprend la structure de chaque
carte sans prétendre au pixel près. Leurs éléments **mesurables**, en revanche,
sont exacts et calculés depuis la norme choisie : les réseaux tombent sur les
mégahertz annoncés parce qu'ils sont dérivés de la durée de ligne active, et
`tests/test_mires.py` les remesure par transformée de Fourier. Le réseau unique
de la mire NHK est calé sur la coupure de luminance de la norme : il se déplace
donc de 4,2 MHz en NTSC à 6,0 en SECAM, et doit disparaître dans les deux cas.

La photographie de la Test Card F n'est pas reproduite — ni la petite fille, ni
le clown. Le panneau central garde le tableau noir et sa grille de morpion, qui
étaient bien dessinés derrière eux.

### La caméra à tubes

Dans une émission musicale des années soixante-dix, les reflets sur les
cymbales et le chrome des pieds de micro laissaient de **grandes traînées
blanches** quand ils se déplaçaient. Cela s'appelle une *queue de comète*, et
cela se déduit du fonctionnement du tube analyseur.

Un tube ne mesure pas la lumière : il mesure la **charge** que la lumière a
soutirée à une cible photoconductrice, et c'est le courant qu'il faut au
faisceau d'électrons pour la remettre à niveau qui fait le signal vidéo. Or ce
faisceau a un débit maximal, réglé pour évacuer 130 % du blanc. Un reflet
spéculaire, lui, dépasse le blanc de vingt à cinquante fois : le faisceau en
évacue une tranche **fixe** par trame, et il lui faut plusieurs trames pour en
venir à bout — pendant lesquelles le reflet s'est déplacé.

Quatre conséquences, toutes vérifiables sur un enregistrement d'époque, et
toutes émergentes du calcul plutôt que peintes :

- le cœur de la traînée est d'un **blanc plat**, entouré d'un halo dégradé que
  l'objectif fabrique — un reflet ne se pose pas sur la cible en carré net, et
  l'oublier donnait des taches blanches à bords francs ;
- **l'image disparaît derrière elle** — le faisceau donne déjà tout ;
- elle **s'arrête net**, la décroissance étant arithmétique et non
  exponentielle. C'est ce qui distingue une comète d'un flou de bougé ;
- et elle **change de couleur sur sa longueur** quand le fichier a gardé
  l'inégalité entre canaux : sur un reflet à (1,000 ; 0,981 ; 0,950), le rouge
  traîne sur 53 pixels, le vert sur 24, le bleu sur 5. Si les trois canaux sont
  à 255, en revanche, plus rien ne dit lequel dominait dans la scène et la
  traînée sort blanche — l'information a été perdue par le fichier, pas par la
  simulation.

**Le réglage par défaut est délibérément léger**, et il est calé sur une
capture d'émission de 1972 — un groupe sur scène, éclairage de concert,
mouvement partout. Ce qu'on y voit est discret : aucune plage blanche, aucun
pixel écrêté, et les traînées visibles sont celles du sujet lui-même. Sur un
éclat de chrome de douze pixels, le cœur blanc en fait vingt-six, entouré d'un
halo dégradé de cent huit. La comète spectaculaire existe — mais elle suppose un
projecteur dans l'axe, et c'est au curseur **Éclat des reflets** de le dire.

Ce chiffre a d'abord été dix fois plus grand, et faux. La **cible sature** — sa
face arrière ne peut pas remonter au-delà du potentiel de sa face avant — et le
premier modèle l'ignorait : un reflet resté quarante trames dans le champ y
accumulait de quoi traîner **quinze secondes**. Une fois la borne posée, la
durée ne dépend plus que du rapport entre la capacité de la cible et le courant
du faisceau, et non de l'éclat du reflet : au-delà de la saturation, un reflet
deux fois plus brillant ne traîne pas plus longtemps. Le moteur temps réel avait
en outre sa propre faute, du même genre — il déchargeait la cible une fois par
*image* de vidéo au lieu d'une fois par *trame*, ce qui faisait durer toutes les
traînées exactement deux fois trop longtemps sur une source à 25 im/s.

Ce qui distingue vraiment ces caméras n'est d'ailleurs pas leur comète — treize
millisecondes séparent le vidicon de 1966 du Plumbicon de 1973, personne ne les
voit — mais leur **rémanence** et leur **colorimétrie**. C'est la rémanence,
et non la comète, qu'on voit sur les captures d'époque.

Deux réglages méritent d'être connus, parce qu'ils décident de la force de
l'effet. Le **seuil des reflets** est la seule hypothèse du modèle : un fichier
huit bits ne dit plus quel pixel écrêté était du chrome sous projecteur et lequel
était un mur éclairé. À 0,94 par défaut, seul ce qui est à un cheveu de
l'écrêtage est candidat — le baisser fait réapparaître de grandes plages
blanches, ce qui est instructif mais n'est pas ce que voyait un opérateur. Le
**pont entre images** comble ce que l'échantillonnage temporel de la source a
laissé vide : sans lui, un reflet rapide sort en chapelet plutôt qu'en traînée.
Il est **nul par défaut** — c'est une interpolation et non un phénomène, et sur
une image chargée elle diverge du simulateur de référence. On ne l'allume que
pour ce à quoi il sert.

L'onglet règle aussi la **rémanence** — bien pire dans les bas niveaux, d'où la
lumière de biais qui remontait le point de fonctionnement — le **désalignement**
des trois tubes, et le **circuit anti-comète** que Philips a livré en 1976.

Mais on n'est pas obligé de toucher aux curseurs : un **menu de sept caméras**,
de 1966 à 1987, les règle d'un geste.

| année | caméra | encaisse | traînée | rémanence 3ᵉ | ΔE\*ab |
|---|---|---|---|---|---|
| 1966 | Vidicon 3 tubes | 1 × | 41 ms | 28,90 % | 16,9 |
| 1970 | Plumbicon, car de reportage | 1 × | 34 ms | 1,84 % | 11,9 |
| 1973 | Plumbicon de studio, bien réglé | 1 × | 28 ms | 1,19 % | 8,9 |
| 1977 | Plumbicon à anti-comète | 128 × | 0 | 1,19 % | 6,7 |
| 1981 | Saticon d'ENG | 83 × | 0 | 5,34 % | 5,2 |
| 1984 | Saticon à canon diode | 272 × | 0 | 0,33 % | 3,0 |
| 1987 | CCD | 1 204 × | 0 | 0,00 % | 2,5 |

La traînée ne remonte jamais, et la bascule est nette en 1977 : c'est l'arrivée
de l'anti-comète. La rémanence, en revanche, n'est pas monotone — le Saticon de
1981 traîne davantage que le Plumbicon de 1973, parce qu'il gagnait ailleurs, en
définition. Le simulateur rend cet arbitrage plutôt que de le lisser.

La dernière colonne est celle de la **colorimétrie**, et c'est elle qui
distingue le mieux ces caméras — bien avant leur comète. Les courbes d'analyse
idéales d'une caméra ont des *lobes négatifs*, et aucun filtre ne sait
soustraire de la lumière : chaque voie récolte donc une part de ses voisines et
l'image sort désaturée. D'où la **matrice de masquage** dans l'électronique,
aux coefficients hors diagonale négatifs, qui refabrique par soustraction ce
que l'optique ne pouvait pas faire. Sans elle, 37 % de saturation en moins ;
avec, la caméra redevient exactement transparente.

**Ces valeurs ne sont pas recopiées de fiches techniques**, et le cours le dit
en toutes lettres : ce qui est documenté, c'est le comportement de chaque
génération, et les paramètres sont choisis pour le reproduire. Chaque ligne
porte sa rémanence *mesurée*, que la suite de tests recalcule à chaque
exécution. Le chapitre 15 du cours donne tout le calcul et les tableaux.

Un contrôle vaut d'être signalé : sur une scène **fixe**, le tube est
rigoureusement transparent — ΔE\*ab moyen de 2,51 sans caméra, 2,51 avec. Un
tube ne dégrade pas une image immobile, il ne fait que retarder les changements,
et le modèle le rend exactement.

---

## Le simulateur radio

Le pendant sonore, et le même principe : on reconstruit le **signal réellement
transmis** — l'enveloppe complexe de la porteuse — on lui fait traverser un
canal bruité, et on le démodule comme le ferait le poste. Ce qu'on entend n'est
pas un effet appliqué à un fichier ; c'est ce qui ressort de la démodulation.

```bash
radio.bat "C:\musique\morceau.mp3"
```

Sept services, chacun avec sa modulation, son canal, son compresseur et son
haut-parleur :

| service | modulation | canal | largeur | β | gain FM |
|---|---|---|---|---|---|
| Radiodiffusion AM, ondes moyennes | AM | 9,00 kHz | 9,0 kHz | — | — |
| Radiodiffusion FM, mono | FM | 100,00 kHz | 180,0 kHz | 5,00 | +26,5 dB |
| CB 27 MHz, AM | AM | 10,00 kHz | 6,0 kHz | — | — |
| CB 27 MHz, bande latérale unique | BLU | 10,00 kHz | 2,7 kHz | — | — |
| Talkie-walkie PMR446 | FM | 12,50 kHz | 11,0 kHz | 0,83 | +5,8 dB |
| VHF marine | FM | 25,00 kHz | 16,0 kHz | 1,67 | +13,5 dB |
| VHF aéronautique | AM | 25,00 kHz | 5,4 kHz | — | — |

Trois lois se mesurent au lieu de se décréter. **L'AM ne gagne rien** : un
décibel de porteuse rend exactement un décibel de signal. **La FM gagne ce que
sa largeur lui coûte** : à C/N de 20 dB, le talkie fait douze décibels de mieux
qu'une AM de même encombrement, la radiodiffusion trente-cinq. **Et la FM
s'effondre** sous son seuil — les craquements ne sont pas un générateur de
clics, c'est le vecteur de bruit qui fait le tour de l'origine et le
discriminateur qui sort une impulsion à chaque tour.

Deux détails qui font tout le caractère. **Le sifflement de deux avions qui
parlent ensemble** n'est pas ajouté : on additionne deux nombres complexes, et
sa fréquence est l'écart des deux émetteurs. C'est même la raison pour laquelle
l'aéronautique est restée en amplitude — en fréquence, le plus fort aurait
effacé l'autre en silence. Et **le haut-parleur** : un talkie ne sonne pas comme
un talkie à cause de sa modulation, mais à cause du transducteur de trente-six
millimètres en boîtier plastique, qui ne descend pas, résonne à 1100 Hz et
s'éteint vite. La case se décoche, et l'écart est saisissant.

L'export se fait en WAV ou en MP3 (`Ctrl+E`). Le détail de la chaîne, les
tableaux de mesure et la liste de ce qui **n'est pas** simulé sont dans
[`docs/radio.md`](docs/radio.md).

---

## Écrire du son dans l'image

Un composite est une onde ; une pile d'opérateurs à modulation de fréquence —
celle d'un DX7 — en est une autre. Arty additionne la seconde à la première,
exactement là où un brouilleur agirait, entre le codeur et le canal.

```bash
arty.bat "C:\images\photo.png"   # ou rien du tout : il s'ouvre sur une mire
```

Rien n'est dessiné. Le motif qu'on voit est **déduit** par le décodeur du
téléviseur, à partir du seul rapport entre la fréquence du son et celle du
balayage — parce qu'un composite est un signal à une dimension, et que le
tableau à deux dimensions n'en est qu'un pliage : l'échantillon `k` de la ligne
`n` sort à l'instant `n / f_ligne + k / f_échantillonnage`.

| `f / f_ligne` | avance par ligne | ce qu'on voit |
|---|---|---|
| entier | 0° | barres verticales **immobiles** |
| demi-entier | 180° | damier, une ligne sur deux inversée |
| quelconque | le reste | barres **penchées**, d'autant plus que le reste est grand |
| près de `f_sc` | — | de la **couleur** : le décodeur y voit de la chrominance |

Les trois premiers cas sont vérifiés par la mesure : à 8 `f_ligne`, deux lignes
voisines de la perturbation sont identiques à 10⁻⁹ près ; à 8,5, elles sont
exactement opposées ; et le nombre d'alternances comptées sur une ligne vaut
`f / f_ligne` à une barre près. Le quatrième est le plus spectaculaire — près de
la sous-porteuse, une mire en niveaux de gris se met à teinter toute seule.
Sous la bande de chrominance il n'en sort rien du tout — 7·10⁻¹⁴ de saturation
moyenne à 600 kHz, c'est-à-dire le bruit de calcul ; puis 0,017 à 300 kHz de la
sous-porteuse, et 0,085 dessus. C'est le cross-color du chapitre 10, provoqué
exprès.

Six opérateurs, chacun avec son rapport de fréquence, son niveau, son désaccord,
sa rétroaction et son enveloppe à quatre segments ; cinq agencements (additif,
chaîne, deux piles, éventail, cloche) posés dans une matrice de modulation 6 × 6.
Monter l'indice ouvre l'éventail des harmoniques — les raies `f_p ± k·f_m` en
`J_k(β)` — et fait passer d'une barre franche à une texture fine.

Et l'enveloppe se lit **de haut en bas** : une trame dure vingt millisecondes,
donc l'axe du temps de l'enveloppe *est* la hauteur de l'image. Une attaque de
deux millisecondes, c'est le dixième supérieur de la trame.

**Le son n'est pas touché.** La voie audio a sa propre porteuse, plusieurs
mégahertz plus haut ; un test fait passer le même signal par la chaîne son avant
et après un rendu à niveau maximal, et exige le bit près. Le bouton « exporter
la voix » écrit un WAV : la même pile d'opérateurs, transposée à 110 Hz pour
être audible — littéralement le son qu'on est en train de regarder. Le détail,
les mesures et ce qui **n'est pas** repris du DX7 sont dans
[`docs/arty.md`](docs/arty.md).

---

## Le lecteur vidéo

```bash
tv.bat "C:\films\mon_film.mp4"   # ou glisser le fichier sur l'icône
run.bat video mon_film.mp4       # équivalent, via le lanceur général
```

**Commandes** — `Ctrl+O` ouvrir · `Espace` lire/pause · `1` `2` `3` changer de
norme **sans interrompre la lecture** · `←` `→` reculer ou avancer de cinq
secondes · `M` couper le son · `C` volet de comparaison · `F11` plein écran,
`Échap` pour en sortir · `Ctrl+E` exporter en MP4. Le glisser-déposer
fonctionne aussi dans la fenêtre.

### Le volet de comparaison

`C`, ou la case de l'onglet Image, et le pointeur commande un volet : **à
gauche la vidéo telle qu'elle est entrée, à droite le téléviseur.** Il n'y a
rien à cliquer ni à faire glisser — on passe la souris sur l'image, et la
coupure suit.

Les deux moitiés sont échantillonnées à la **même coordonnée d'image**,
courbure de la dalle comprise : un point de la scène tombe au même endroit des
deux côtés du volet. On ne compare donc que ce qui a changé — le signal, jamais
la géométrie. À gauche, aucun traitement : ni codage, ni canal, ni caméra à
tubes, ni réponse de tube, ni lignes de balayage. Ni luminosité non plus, ce
réglage n'existant que pour rendre la lumière que les lignes et le masque ont
prise.

Deux détails de mise en œuvre valent d'être dits. Le choix entre les deux
moitiés se fait **à la fin du shader**, alors qu'un retour anticipé coûterait
moins cher : `dFdx` et `dFdy` se calculent sur des groupes de quatre fragments,
et le GLSL ne les définit que si tout le groupe suit le même chemin — sortir
tôt rendrait fausses, sur la colonne qui borde le volet, les dérivées dont
dépendent l'intégrale des lignes de balayage et l'adoucissement du bord de
dalle. Et la position du volet ne vit **pas** dans `ParametresRendu` : elle
vient de la souris, que seule la vue connaît, et le panneau de réglages la
ramènerait en arrière au premier curseur touché.

Le volet est repris par l'export MP4 — un fichier de comparaison, coupé où on
l'a laissé.

Les réglages sont en cinq onglets — **Image**, **Caméra**, **Bruit**,
**Magnétoscope**, **Son**. Le bruit a le sien parce qu'il n'appartient à aucun des deux : un seul
canal, une seule densité de bruit, et l'onglet montre en clair ce que la voie
son en récolte.

Le magnétoscope tourne lui aussi sur la carte graphique — `shaders/vhs.glsl`,
une passe entre le codage et le décodage — et coûte 0,16 ms de plus par image :
0,36 ms au lieu de 0,20 en mode SP, soit encore près de trois mille images par
seconde.

La caméra à tubes également — `shaders/tube.glsl`, deux passes avant le codage.
C'est la seule partie de ce moteur qui garde un état d'une image à l'autre : la
charge restée sur la cible vit dans une texture, relue à l'image suivante, et
c'est elle qui fait la traînée. Son coût reste sous 0,06 ms, à la limite de ce
que le chronomètre GPU sait résoudre.

Le plein écran masque toute l'interface — barre d'outils, panneau de réglages,
transport et barre d'état : il ne reste que la dalle sur fond noir.

### Le son mène la marche

PyAV démultiplexe et décode l'image et le son **d'une seule passe** sur le
fichier, ce qui donne des estampilles cohérentes entre les deux flux —
condition nécessaire à toute synchronisation honnête. La sortie audio passe par
sounddevice.

C'est le **son qui sert d'horloge**, jamais l'image. Un décrochage audio
s'entend immédiatement — craquement, silence, changement de hauteur — alors
qu'une image affichée deux millisecondes trop tôt ne se voit pas. L'horloge
avance donc au rythme des échantillons réellement remis au périphérique,
latence de sortie retranchée. Mesuré : **+4 ms de dérive sur 1,8 s**.

Trois cas particuliers, tous traités :

* **pas de piste audio** — on retombe sur une horloge absolue, en accumulant
  les périodes plutôt qu'en dormant d'une durée fixe : un `sleep` de durée
  fixe ferait dériver la lecture de plusieurs secondes sur un film entier ;
* **vitesse autre que 1×** — le son est coupé et l'horloge redevient absolue.
  Garder la hauteur demanderait un rééchantillonnage à tempo préservé ; ne pas
  y toucher donnerait le miaulement d'une bande accélérée. Le choix est franc
  et prévisible ;
* **déplacement** — un conteneur ne se déplace qu'à une image-clé, parfois très
  en amont. On décode et l'on **jette** jusqu'à l'instant demandé, puis on cale
  l'horloge sur la première image conservée. Sans cela, l'horloge annoncerait
  la position demandée pendant que l'écran montrerait le début du fichier.

Trois shaders GLSL — un par norme — refont le même trajet que la bibliothèque,
mais sur le processeur graphique. **Le chapitre 12 du cours leur est
entièrement consacré** : ce qu'un fragment shader interdit, comment on
contourne chaque interdit, et ce que le portage coûte en fidélité.

Mesuré sur une RTX 3090, source 1920×1080, fenêtre 1440×1080 :

| Norme | Grille de travail | Travail GPU | Image complète |
|---|---|---|---|
| NTSC-M | 753 × 480 à 14,32 MHz | 0,11 ms | 0,48 ms |
| PAL-B/G | 921 × 576 à 17,73 MHz | 0,14 ms | 0,49 ms |
| SECAM-L | 916 × 576 à 17,63 MHz | 0,22 ms | 0,60 ms |

La colonne « travail GPU » est ce que la carte passe réellement à calculer ; la
colonne « image complète » y ajoute le pilote, l'échange de tampons et la boucle
d'événements de Qt — soit 1 500 à 2 100 images par seconde de bout en bout.

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

Le SECAM en demande onze de plus — une passe de préparation et dix de somme
préfixe — imposées par la modulation de fréquence : la
phase y est l'**intégrale** du signal modulant depuis le début de la ligne, et
un fragment shader ne connaît que son propre pixel. Aucune formule locale n'a
pour dérivée le signal modulant. Une somme préfixe par doublement récursif
(Hillis-Steele) fournit donc cette intégrale en dix passes minuscules, chacune
ne lisant que deux texels — coût négligeable devant une seule passe de filtrage.

### Ce que le GPU concède

* les filtres analogiques (Butterworth d'ordre 4) deviennent des filtres à
  réponse finie — un shader ne peut pas être récursif. Ils ne sont pas
  synthétisés depuis un gabarit idéal mais **ajustés sur la réponse du
  Butterworth aller-retour**, faute de quoi la bande passante s'affaisse de
  2,9 dB à 1 MHz et toutes les transitions de couleur s'élargissent ;
* le composite est échantillonné sur la grille de la norme plutôt qu'à quatre
  fois la sous-porteuse ;
* **la désaccentuation SECAM basse fréquence est omise** — son coude à 85 kHz
  demanderait plus de deux cents coefficients. Elle n'est pas transparente pour
  autant : sans elle, le discriminateur restituait les transitions avec un
  dépassement de 0,26 en U contre 0,004 pour la référence, et cette frange
  verte n'avait rien d'authentique. On en rend compte en resserrant la bande de
  démodulation à 0,85 MHz — valeur mesurée, non déduite.

L'écart avec le simulateur de référence est **mesuré**, pas supposé
(`tests/test_shaders.py`, et figure 21 du cours) : ΔE\*ab médian de **0,69** en
NTSC et **0,92** en PAL — sous le seuil de perception — et **4,44** en SECAM.
L'erreur n'est pas répartie : elle est concentrée sur les transitions, là où la
forme exacte des filtres compte.

### Le son passe par sa porteuse

Le son d'un téléviseur ne voyageait **pas** dans le signal vidéo : il occupait
sa propre porteuse, quelques mégahertz plus haut dans le même canal. Il subit
donc le même bruit, et le simulateur le lui fait subir.

| | porteuse | modulation | excursion | préaccentuation |
|---|---|---|---|---|
| NTSC-M | +4,5 MHz | FM | ±25 kHz | 75 µs |
| PAL-B/G | +5,5 MHz | FM | ±50 kHz | 50 µs |
| PAL-I | +6,0 MHz | FM | ±50 kHz | 50 µs |
| SECAM-D/K | +6,5 MHz | FM | ±50 kHz | 50 µs |
| **SECAM-L** | **+6,5 MHz** | **AM** | taux 54 % | aucune |

La chaîne est complète : limitation à 15 kHz, préaccentuation, limiteur,
modulation, **bruit de canal de la même densité que celui de l'image**, filtre
à fréquence intermédiaire, démodulation, désaccentuation. Le souffle, le seuil
FM et ses claquements, le ronflement intercarrier — rien n'est peint.

Deux gains, et leur place dans la chaîne change tout. Le **niveau d'entrée du
modulateur** est celui du studio : placé avant la modulation, il décide de
l'excursion réellement employée, donc du rapport signal/bruit. Un décibel de
gain en rend un — mesuré sur une source gravée bas dans un canal à 25 dB :
33 dB de signal/bruit sans gain, 45 avec douze décibels, 51 avec dix-huit.
C'est lui qu'il faut pousser quand le fichier est faible.

Le **gain de sortie** de l'onglet Son est le bouton de volume du poste : il
agit après la démodulation, amplifie donc le bruit autant que le signal, et ne
rattrape aucune mauvaise réception. Il sert quand le fichier est gravé bas — ou
simplement parce que la porteuse ne transportait qu'une voie, et que ramener
une source stéréo en mono coûte jusqu'à trois décibels. Au-delà de la butée,
l'étage sature en douceur plutôt que d'écrêter carré : mesuré, une source à
0,03 encaisse les 24 dB sans la moindre distorsion, une source à 0,4 n'en prend
que 9,5 avant de comprimer. Le curseur de volume du transport monte de son côté
jusqu'à 200 %.

Le réglage de bruit reste du côté image, et c'est voulu : il n'y a **qu'un
canal**. Ce que la voie son en récolte se déduit de sa largeur de bande
(130 kHz contre 5 MHz, soit 15,8 dB de gagnés) et de sa puissance d'émission
(10 à 13 dB plus bas), sans rien choisir.

Ce qui donne, à 30 dB de rapport signal/bruit d'image :

| | porteuse/bruit | son restitué |
|---|---|---|
| NTSC-M | 37,2 dB | 56,7 dB |
| PAL-B/G | 32,9 dB | 57,2 dB |
| **SECAM-L** | **43,0 dB** | **31,9 dB** |

Le SECAM-L part avec **le meilleur rapport porteuse/bruit des cinq systèmes** —
sa porteuse est la plus étroite et la mieux servie en puissance — et arrive
vingt-cinq décibels derrière. Toute la différence tient à ce que sa modulation
d'amplitude n'apporte aucun gain de démodulation, là où la FM en rend une
vingtaine de décibels. C'est l'explication de ce que tout le monde a constaté
sans se l'expliquer : ailleurs, le son restait propre bien après que l'image
eut commencé à neiger.

### Exporter en MP4

`Ctrl+E` convertit la vidéo ouverte en la faisant passer par le téléviseur —
et l'on enregistre **ce qu'on voit** : courbure, réponse du tube, halo, lignes
de balayage, son par la porteuse.

La géométrie suit la taille de DESTINATION, pas celle de la fenêtre. Exporter
en 1152 points de haut depuis une fenêtre de 700 donne donc des lignes de
balayage bien plus franches, et c'est juste : 576 lignes dans 1152 pixels, on
passe enfin la limite de Shannon.

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

### La courbure de la dalle

La dalle d'un tube n'est pas plate : c'est une **calotte sphérique**, sur
laquelle le balayage peint l'image à longueur d'arc constante.

Plutôt que la distorsion en barillet habituelle — sans signification physique,
et dont les coefficients se règlent au jugé — la géométrie est faite pour de
bon : un rayon part de l'œil, traverse le point d'écran considéré, et
l'intersection avec la sphère n'est qu'une équation du second degré. Le point
obtenu se convertit en longueur d'arc depuis le sommet, ce qui donne la
coordonnée dans l'image. La projection azimutale équidistante ainsi obtenue
conserve les distances radiales — exactement la façon dont le faisceau balaie
la dalle.

Le rayon s'exprime en demi-diagonales d'image, ce qui le rend indépendant du
format comme de la résolution :

| Réglage | Rayon | Sur un tube de 21 pouces | Époque |
|---|---|---|---|
| 1,00 | 1,6 | 42 cm | poste des années 60 |
| 0,40 | 4,0 | 1,06 m | années 80 |
| 0,16 | 10,0 | 2,65 m | dalle presque plate des derniers tubes |

Les coins sont arrondis par une superellipse, et le calcul est court-circuité
dès que le rayon dépasse quarante demi-diagonales : à plat, la courbure ne
coûte rien. Mesuré : 0,18 à 0,36 ms selon le bombement — parfois *moins* qu'à
plat, l'image occupant alors moins de pixels.

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
  tube.py           la caméra : rémanence, queue de comète, désalignement
  vhs.py            le magnétoscope : color-under, gigue, pertes de signal
  son.py            la voie son : porteuse, FM, accentuations, intercarrier
  pipeline.py       la chaîne complète
  mires.py          les douze mires de test, dont TDF, Test Card F et NHK
  mesures.py        vectorscope, spectres, ΔE*ab, résolutions

shaders/          les trois shaders GLSL, un par norme
  commun.glsl       matriçage, horloge de sous-porteuse, noyaux
  ntsc.glsl         modulation en quadrature
  pal.glsl          idem, avec l'inversion de V ligne à ligne
  secam.glsl        modulation de fréquence, séquentielle
  scan.frag         somme préfixe : l'intégrale de phase du SECAM
  tube.glsl         la caméra — la seule passe à garder un état d'une image à l'autre
  vhs.glsl          le magnétoscope, entre le codage et le décodage
  bloom.glsl        halation et épanouissement du faisceau
  presentation.frag courbure de la dalle, définition du tube, lignes, masque
  sommet.vert       triangle plein écran, sans tampon de sommets

radio/            le simulateur radio (numpy pur, sauf l'interface)
  services.py       la table des sept services, et leurs constantes
  modulation.py     AM, FM, BLU — modulateurs et démodulateurs
  canal.py          bruit, évanouissement, parasites, stations voisines
  chaine.py         l'enchaînement complet, en flux
  source_audio.py   décodage des fichiers, export WAV et MP3
  app.py            la fenêtre

arty/             l'injection sonore dans l'onde de l'image
  dx7.py            six opérateurs à modulation de fréquence, et leur matrice
  injection.py      la base de temps du balayage, et la prédiction du motif
  app.py            la fenêtre

lecteur/          le lecteur vidéo temps réel
  normes_gl.py      traduction des normes en uniformes, conception des noyaux
  gl_util.py        compilation, cibles de rendu, quad plein écran
  vue_gl.py         l'enchaînement des passes
  source_video.py   décodage image et son, synchronisés sur l'horloge audio
  app.py            la fenêtre

gui/              le banc de mesure PyQt5
docs/             le cours, ses vingt-cinq figures, et leurs générateurs
tests/            305 tests
```

---

## Vérification

```bash
run.bat tests        # ou : python -m pytest tests/ -v
```

305 tests : 23 sur le matriçage et la colorimétrie, 16 sur l'horloge de
sous-porteuse, 19 sur la chaîne complète, 39 sur les shaders, 31 sur le son,
37 sur la caméra, 21 sur le magnétoscope, 37 sur la radio, 23 sur l'injection
sonore, 46 sur les mires et 13 sur l'export. Ils ne se contentent pas de vérifier que le code s'exécute — ils contrôlent les
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
tv.bat [film.mp4]      lecteur vidéo
run.bat video [f.mp4]  synonyme du précédent
radio.bat [son.mp3]    simulateur radio
run.bat radio [s.mp3]  synonyme du précédent
arty.bat [image.png]   injection sonore dans l'onde de l'image
run.bat arty [i.png]   synonyme du précédent
run.bat tests          suite de vérification
run.bat figures        régénère les figures du cours
run.bat html           reconstruit docs/cours.html
run.bat tout           figures + html + tests
run.bat install        installe les dépendances
run.bat aide           rappelle tout ceci
```

Les figures et la page HTML se régénèrent aussi à la main :

```bash
python docs/generer_figures.py              # toutes
python docs/generer_figures.py --seulement 05,07,10
python docs/construire_html.py
```

---

## Environnement

Python 3.10 ou plus récent. Le lecteur vidéo demande en outre un pilote
OpenGL 3.3.

Testé sous Windows 11 avec Python 3.13, PyQt5 5.15.11, numpy 1.26, scipy 1.15,
PyOpenGL 3.1, PyAV 17.0 et sounddevice 0.5, sur GeForce RTX 3090.
