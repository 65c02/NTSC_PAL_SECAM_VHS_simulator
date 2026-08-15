# Le codage couleur de la télévision analogique

### NTSC, PAL, SECAM — la théorie, les mathématiques, et ce que tout cela fait à vos pixels

---

Ce document est un cours. Il part d'un problème d'ingénierie posé en 1953, en
suit les conséquences jusqu'aux artefacts que l'on voyait encore sur les
téléviseurs des années 1990, et démontre chaque étape plutôt que de l'énoncer.

Toutes les figures qu'il contient sont des sorties réelles du simulateur qui
l'accompagne : aucune n'a été dessinée à la main. Toutes les valeurs numériques
citées ont été mesurées sur ce même simulateur, et les propriétés
fondamentales sont vérifiées par une suite de tests (`tests/`). Quand le texte
affirme quelque chose de vérifiable, il indique la fonction qui le calcule et
le test qui le contrôle.

**Table des matières**

1. [Le problème de 1953](#1-le-problème-de-1953)
2. [Colorimétrie et gamma](#2-colorimétrie-et-gamma)
3. [D'où viennent 0,299 / 0,587 / 0,114](#3-doù-viennent-0299--0587--0114)
4. [Les signaux de différence de couleur](#4-les-signaux-de-différence-de-couleur)
5. [L'entrelacement spectral](#5-lentrelacement-spectral)
6. [NTSC](#6-ntsc)
7. [Le péché du NTSC : l'erreur de phase](#7-le-péché-du-ntsc--lerreur-de-phase)
8. [PAL](#8-pal)
9. [SECAM](#9-secam)
10. [Décoder : réjecteur, peigne, et les artefacts qui en naissent](#10-décoder--réjecteur-peigne-et-les-artefacts-qui-en-naissent)
11. [Ce que tout cela fait au RGB d'origine](#11-ce-que-tout-cela-fait-au-rgb-dorigine)
12. [Annexes](#12-annexes)

---

## 1. Le problème de 1953

### 1.1 Un canal déjà plein

En 1941, les États-Unis normalisent la télévision en noir et blanc : 525 lignes,
60 trames par seconde, un canal hertzien de 6 MHz dont 4,2 MHz sont occupés par
l'image et le reste par la porteuse son, placée 4,5 MHz au-dessus de la porteuse
image. Dix ans plus tard, plus de dix millions de récepteurs sont en service.

Le problème posé au *National Television System Committee* n'est donc pas
« comment transmettre de la couleur », mais quelque chose de bien plus contraint :

> Comment ajouter la couleur à un signal existant, sans un hertz de bande
> supplémentaire, sans rendre obsolètes dix millions de récepteurs, et de
> telle sorte qu'un récepteur couleur affiche correctement une émission en
> noir et blanc ?

La première tentative avait échoué sur ce point précis. Le système de CBS,
adopté puis abandonné en 1951, était *séquentiel à trames* : un disque coloré
tournant devant le tube présentait successivement les images rouge, verte et
bleue. C'était simple, la colorimétrie en était excellente — et c'était
totalement incompatible. Un récepteur noir et blanc n'y voyait qu'un
scintillement.

### 1.2 Les deux faits qui rendent la chose possible

Toute la télévision couleur analogique repose sur deux propriétés de la vision
humaine, et sur rien d'autre.

**Premièrement, l'œil sépare la luminance des couleurs.** Notre système visuel
possède un canal achromatique à haute résolution et deux canaux chromatiques
à basse résolution. On distingue des détails de luminance dix fois plus fins
que des détails de couleur.

**Deuxièmement, une image se décompose en une composante achromatique et deux
composantes chromatiques** sans perte : ce n'est qu'un changement de base dans
l'espace des couleurs, donc réversible.

De là découle la stratégie : on transmet la luminance exactement comme avant —
c'est elle que verra le récepteur noir et blanc — et on glisse les deux
composantes chromatiques, sévèrement réduites en bande passante, dans les
interstices du signal existant.

Le mot « interstices » n'est pas une métaphore. Le chapitre 5 montrera que le
spectre d'une image balayée est un peigne de raies séparées par du vide, et
que ce vide est très exactement là où l'on peut loger un second signal.

### 1.3 Trois réponses au même problème

Trois systèmes ont résolu cette équation, dans cet ordre :

| | NTSC | PAL | SECAM |
|---|---|---|---|
| Normalisé | 1953, États-Unis | 1963, Allemagne (Walter Bruch, Telefunken) | 1956–1967, France (Henri de France) |
| Chrominance portée par | amplitude **et** phase d'une sous-porteuse | idem, mais une composante alterne de signe | **fréquence** de deux sous-porteuses |
| Les deux composantes sont | simultanées | simultanées | **séquentielles**, une par ligne |
| Talon d'Achille | l'erreur de phase | la résolution verticale de la couleur | tout ce qui touche à l'amplitude est perdu |

Ils partagent le même matriçage, les mêmes coefficients de luminance et la
même philosophie. Ils divergent uniquement sur la façon de moduler la
sous-porteuse — et cette seule différence entraîne tout le reste.

---

## 2. Colorimétrie et gamma

### 2.1 Les primaires : le même nombre ne désigne pas la même couleur

Un triplet $(R, G, B)$ n'est pas une couleur. C'est une recette : *tant* de la
primaire rouge de cet écran-là, *tant* de sa primaire verte, *tant* de sa
primaire bleue. Changez d'écran, la recette produit une autre couleur.

Pour parler de couleurs sans ambiguïté, la CIE a défini en 1931 un espace
absolu, XYZ, et sa projection $(x, y)$ dite *diagramme de chromaticité*. Un jeu
de primaires est alors trois points dans ce plan, plus un blanc de référence.
Le triangle qu'ils forment est le **gamut** : l'ensemble des couleurs
reproductibles.

Passer de RGB linéaire à XYZ est une matrice $3\times3$, entièrement
déterminée par les primaires et le blanc. On écrit les primaires normalisées
par leur $y$ :

$$
M = \begin{pmatrix}
x_R/y_R & x_G/y_G & x_B/y_B \\
1 & 1 & 1 \\
z_R/y_R & z_G/y_G & z_B/y_B
\end{pmatrix},
\qquad z = 1 - x - y
$$

puis on cherche les trois facteurs d'échelle $(s_R, s_G, s_B)$ qui envoient
$(1,1,1)$ sur le blanc de référence $W$ :

$$
\mathbf{s} = M^{-1} W, \qquad
M_{\text{RGB}\to\text{XYZ}} = M \cdot \operatorname{diag}(\mathbf{s})
$$

> **Dans le code** — `colorimetrie.Primaires.matrice_vers_xyz`.

### 2.2 Trois jeux de primaires, et un mensonge normatif

![Les gamuts des trois systèmes](figures/01_gamuts.png)

Le NTSC de 1953 spécifiait des primaires extrêmement saturées, sous illuminant
C. Elles supposaient des luminophores qui n'existaient pas. Ceux qu'on savait
fabriquer et qui étaient assez lumineux pour un salon éclairé avaient un gamut
bien plus étroit. Dès le milieu des années 1960, **aucun téléviseur américain
n'utilisait les primaires NTSC**, et l'écart a fini par être normalisé sous le
nom SMPTE-C.

L'Europe, arrivant plus tard, a normalisé d'emblée les primaires réellement
disponibles (EBU Tech. 3213), qui sont à un cheveu de celles du sRGB
d'aujourd'hui.

Conséquence pratique, visible sur la figure ci-dessous : une image sRGB
réinterprétée dans les primaires de 1953 paraît **terne**. Le gamut cible étant
plus large, le même triplet numérique y désigne une couleur moins éloignée du
blanc.

![L'effet des primaires de 1953](figures/20_primaires.png)

> **Dans le code** — `colorimetrie.PRIMAIRES`, `colorimetrie.convertir_primaires`.
> L'adaptation chromatique de Bradford est appliquée entre blancs différents,
> sans quoi le passage de l'illuminant C au D65 introduirait une dominante.

### 2.3 Le gamma : une économie devenue une contrainte

Un tube cathodique n'est pas linéaire. La luminance émise suit une loi de
puissance de la tension de commande :

$$L \propto V^{\gamma}, \qquad \gamma \approx 2{,}2 \ \text{à}\ 2{,}8$$

Il faut donc compenser. On aurait pu placer le correcteur dans chaque
récepteur ; on l'a placé une fois pour toutes à la prise de vue :

$$V' = L^{1/\gamma}$$

C'était un choix économique — un correcteur dans les studios plutôt que dans
dix millions de foyers — et il s'est révélé heureux à un autre titre : la
courbe $L^{1/\gamma}$ ressemble à la réponse de l'œil, si bien que quantifier
$V'$ uniformément répartit le bruit de façon perceptuellement homogène. C'est
la raison pour laquelle toute la vidéo numérique code encore aujourd'hui des
valeurs gamma-corrigées.

Mais ce choix a une conséquence qui va nous poursuivre pendant tout ce cours :

> **Le matriçage a lieu APRÈS la correction de gamma.**

Le codeur ne combine pas des luminances, il combine des racines γ-ièmes de
luminances. On note ces grandeurs avec une apostrophe — $R'$, $G'$, $B'$, $Y'$ —
et $Y'$ s'appelle **luma**, jamais *luminance*. Le chapitre 11 chiffrera ce que
cette apostrophe coûte.

BT.470 retient $\gamma = 2{,}2$ pour le système M et $\gamma = 2{,}8$ pour les
systèmes 625 lignes. Cette dernière valeur est une surestimation reconnue : les
tubes réels tournaient plutôt autour de 2,4.

> **Dans le code** — `colorimetrie.oetf_camera`, `colorimetrie.eotf_ecran`.

---

## 3. D'où viennent 0,299 / 0,587 / 0,114

Ces trois nombres sont les plus célèbres de la vidéo. Ils ne sont pas
arbitraires, et ils ne sont pas non plus le fruit d'un réglage empirique.

La composante $Y$ de l'espace CIE XYZ **est** la luminance photométrique, par
construction : la fonction $\bar y(\lambda)$ est la courbe d'efficacité
lumineuse de l'œil. Donc la deuxième ligne de la matrice
$M_{\text{RGB}\to\text{XYZ}}$ donne directement la contribution de chaque
primaire à la luminance.

Pour les primaires NTSC 1953 sous illuminant C, le calcul donne :

$$
Y = 0{,}29890\,R + 0{,}58662\,G + 0{,}11448\,B
$$

Les normalisateurs ont arrondi à trois décimales. **0,299 / 0,587 / 0,114.**

> **Vérifié par** — `tests/test_matrices.py::test_origine_des_coefficients_luma`,
> qui recalcule ces coefficients depuis les coordonnées des primaires et
> compare aux constantes de la norme.

### 3.1 Une incohérence assumée

Ces coefficients décrivent les primaires de 1953. Or PAL et SECAM utilisent les
primaires EBU, pour lesquelles le calcul donnerait :

$$
Y_{\text{EBU}} = 0{,}222\,R + 0{,}707\,G + 0{,}071\,B
$$

BT.470 a néanmoins conservé 0,299 / 0,587 / 0,114 pour les trois systèmes. La
« luma » transmise n'est donc pas la luminance des primaires effectivement
affichées. L'écart est réel, il n'a jamais été corrigé, et il s'ajoute
simplement à la non-constant-luminance du chapitre 11.

Il a fallu attendre la haute définition et BT.709 pour que les coefficients
soient recalculés sur les bonnes primaires — 0,2126 / 0,7152 / 0,0722. La
définition standard numérique (BT.601), elle, a gardé les valeurs de 1953 par
compatibilité.

> **Vérifié par** — `tests/test_matrices.py::test_les_coefficients_luma_ne_conviennent_plus_aux_primaires_modernes`.

---

## 4. Les signaux de différence de couleur

### 4.1 Pourquoi B−Y et R−Y

On veut transmettre $Y'$ plus deux autres signaux qui, avec elle, permettent de
retrouver $R'G'B'$. Le choix des différences de couleur $B'-Y'$ et $R'-Y'$
n'est pas le seul possible, mais il est le seul à satisfaire une contrainte
absolue :

> **Sur un gris, les deux signaux doivent être rigoureusement nuls.**

C'est la condition de compatibilité. Si la chrominance ne s'annule pas sur une
image en noir et blanc, le récepteur couleur y ajoutera des couleurs, et le
récepteur noir et blanc y verra un moirage. Comme $Y' = R' = G' = B'$ sur un
gris, toute différence $X' - Y'$ s'annule d'elle-même.

> **Vérifié par** — `tests/test_pipeline.py::test_ntsc_et_pal_n_emettent_rien_sur_une_image_grise`,
> qui contrôle que le signal de chrominance émis est nul à $10^{-9}$ près.

### 4.2 Pourquoi seulement deux, et pourquoi pas G−Y

Il n'est pas nécessaire d'en transmettre trois. De la définition de $Y'$ :

$$k_R R' + k_G G' + k_B B' = Y'$$

on tire immédiatement, en retranchant $(k_R + k_G + k_B)Y' = Y'$ :

$$
k_R (R'-Y') + k_G (G'-Y') + k_B (B'-Y') = 0
$$

donc

$$
G' - Y' = -\frac{k_R}{k_G}(R'-Y') - \frac{k_B}{k_G}(B'-Y')
        = -0{,}509\,(R'-Y') - 0{,}194\,(B'-Y')
$$

La troisième différence est une combinaison des deux autres. Mieux : ses
coefficients étant petits, c'est celle qui a la **plus faible amplitude** des
trois. La transmettre à la place d'une des deux autres coûterait du rapport
signal/bruit pour rien. On transmet donc les deux plus grandes, et le récepteur
reconstitue le vert.

### 4.3 D'où viennent 0,492 et 0,877

Les différences de couleur ne sont pas transmises telles quelles, mais mises à
l'échelle :

$$U = 0{,}492\,(B'-Y'), \qquad V = 0{,}877\,(R'-Y')$$

Ces deux nombres se démontrent. Le signal composite d'une couleur uniforme vaut

$$S(t) = Y' + \underbrace{\sqrt{U^2+V^2}}_{A}\,\sin(\omega t + \varphi)$$

et oscille donc entre $Y' - A$ et $Y' + A$.

Le cahier des charges impose que $S$ reste dans une excursion totale de $5/3$ de
l'amplitude vidéo : au plus $+4/3$ — au-delà, l'émetteur sature — et au moins
$-1/3$, au-delà commencerait la zone réservée aux signaux de synchronisation.

Cherchons les facteurs $u$ et $v$ tels que ces bornes soient atteintes
exactement. Deux couleurs les saturent :

**Le bleu pur** $(0,0,1)$ : $Y' = k_B = 0{,}114$, $B'-Y' = 1-k_B$,
$R'-Y' = -k_B$. Il doit toucher la borne basse :

$$
\big(u\,(1-k_B)\big)^2 + \big(v\,k_B\big)^2 = \left(k_B + \tfrac13\right)^2
$$

**Le rouge pur** $(1,0,0)$ : $Y' = k_R = 0{,}299$, $R'-Y' = 1-k_R$,
$B'-Y' = -k_R$. Même chose :

$$
\big(u\,k_R\big)^2 + \big(v\,(1-k_R)\big)^2 = \left(k_R + \tfrac13\right)^2
$$

C'est un système linéaire en $u^2$ et $v^2$. Sa résolution donne

$$\boxed{u = 0{,}492111 \qquad v = 0{,}877283}$$

— les constantes de la norme, à la sixième décimale.

Et la construction est élégante : les couleurs **complémentaires** (jaune,
cyan) ont la même amplitude de chrominance que leur primaire mais une luma
complémentaire $1-Y'$. Elles atteignent donc la borne haute exactement quand
les primaires atteignent la borne basse. Une seule contrainte suffisait pour
les deux.

![L'excursion du signal composite](figures/03_excursion.png)

> **Dans le code** — `matrices.deriver_facteurs_echelle`, qui refait ce calcul.
> **Vérifié par** — `tests/test_matrices.py::test_deriver_facteurs_echelle` et
> `::test_excursion_composite_des_couleurs_saturees`.

### 4.4 Les trois bases, en résumé

| Système | Composantes | Définition |
|---|---|---|
| PAL | $U$, $V$ | $U = 0{,}492(B'-Y')$, $V = 0{,}877(R'-Y')$ |
| NTSC | $I$, $Q$ | $U$, $V$ tournés de 33° |
| SECAM | $D'_B$, $D'_R$ | $D'_B = +1{,}505(B'-Y')$, $D'_R = -1{,}902(R'-Y')$ |

Matrices complètes en [annexe A](#a-tableau-des-constantes).

---

## 5. L'entrelacement spectral

C'est le cœur mathématique de toute l'affaire, et la partie qu'on explique le
plus mal. Prenons-la lentement.

### 5.1 Une image balayée n'occupe pas tout le spectre

Un signal vidéo est une image lue ligne par ligne. Deux lignes consécutives se
ressemblent énormément — c'est même la définition d'une image. Deux images
consécutives, plus encore.

Le signal est donc **quasi périodique**, de période $T_H = 1/f_H$ (la durée
d'une ligne). Or le spectre d'un signal périodique n'est pas continu : c'est
un **peigne de raies** aux multiples entiers de sa fréquence fondamentale.

Formellement, si le contenu d'une ligne est $a(t)$ et que toutes les lignes
sont identiques, le signal $s(t) = \sum_n a(t - nT_H)$ a pour spectre

$$
S(f) = f_H \, A(f) \sum_{m \in \mathbb{Z}} \delta(f - m f_H)
$$

soit des raies aux fréquences $m f_H$, d'amplitudes données par le spectre
$A$ d'une ligne. **Entre ces raies, il n'y a rien.**

Dans une vraie image, les lignes diffèrent un peu, ce qui élargit chaque raie
d'une quantité de l'ordre de la fréquence trame — quelques dizaines de hertz
face à un espacement de 15 625 Hz. Les creux restent béants.

La figure ci-dessous montre ce peigne sur un signal réellement simulé. Le
panneau du bas, agrandi, est la démonstration :

![L'entrelacement spectral](figures/05_entrelacement_spectral.png)

Dans la zone de luminance pure, les raies tombent sur les **entiers**. Autour
de la sous-porteuse, elles tombent sur les **demi-entiers** — exactement au
milieu des creux.

> **Vérifié par** — `tests/test_pipeline.py::test_entrelacement_spectral_des_peignes_luma_et_chroma`,
> qui détecte les pics du spectre simulé et contrôle leur partie fractionnaire.

### 5.2 Comment loger la chrominance dans les creux

Il suffit de moduler la chrominance sur une porteuse dont la fréquence est un
multiple **demi-entier** de $f_H$ :

$$f_{sc} = \left(m + \tfrac12\right) f_H$$

Le spectre de la chrominance est alors le peigne de la chrominance
(aux multiples de $f_H$) **translaté** de $f_{sc}$ : ses raies tombent en
$f_{sc} \pm k f_H$, c'est-à-dire sur des demi-entiers. Elles s'insèrent
exactement entre celles de la luminance.

Il y a mieux. Un décalage d'un demi-cycle par ligne signifie que **la
sous-porteuse s'inverse d'une ligne à la suivante**. Le motif de points qu'elle
produit sur l'écran est donc en damier plutôt qu'en bandes, et l'œil, qui
moyenne spatialement, le voit deux fois moins. Le même demi-cycle sur une image
complète (525 lignes, nombre impair) inverse aussi le motif d'une image à
l'autre : la persistance rétinienne l'atténue encore. C'est ce qui fait
« ramper » les points au lieu de les laisser fixes.

> **Dans le code** — `porteuse.phase`. La phase est calculée en **temps
> absolu**, jamais réinitialisée en début de ligne :
> $$\varphi(n, k) = 2\pi f_{sc}\left(n T_H + \frac{k}{f_e}\right)$$
> Toutes les propriétés ci-dessus en découlent arithmétiquement, sans qu'on ait
> rien à ajouter.
> **Vérifié par** — `tests/test_porteuse.py`, qui contrôle que l'écart de
> phase entre deux lignes vaut exactement $\pi$ à $10^{-9}$ près, y compris à
> la 480ᵉ ligne de la 100ᵉ image.

### 5.3 Pourquoi 455/2 en NTSC, et pourquoi 59,94 Hz

Le choix de $m$ résulte de trois contraintes qui se rencontrent.

**Assez haut** pour que le motif de points soit fin, donc peu visible.
**Assez bas** pour que les bandes latérales de la chrominance
($f_{sc} \pm 1{,}3$ MHz) tiennent dans les 4,2 MHz du canal.
**Et surtout** : il fallait éviter que la sous-porteuse couleur ne batte avec
la porteuse son, placée 4,5 MHz au-dessus de la porteuse image.

On a donc choisi de rendre l'écart entre les deux lui aussi demi-entier. En
posant

$$f_{son} = 286\, f_H$$

il vient $f_H = 4{,}5\ \text{MHz} / 286 = 15\,734{,}264$ Hz, et avec
$f_{sc} = \frac{455}{2} f_H = 3{,}579545$ MHz, le battement vaut

$$4{,}5 - 3{,}579545 = 0{,}920455\ \text{MHz} = \frac{117}{2} f_H$$

lui aussi demi-entier, donc lui aussi entrelacé, donc lui aussi invisible.

Le prix à payer : la fréquence ligne du noir et blanc, 15 750 Hz, a dû être
abaissée à 15 734,264 Hz, et la fréquence trame de 60 Hz à
$60 \times 1000/1001 = 59{,}94$ Hz. **C'est de là que viennent les 29,97
images par seconde**, le *timecode drop-frame*, et un demi-siècle de
complications dans les studios du monde entier — pour éviter un battement
entre deux porteuses.

### 5.4 Pourquoi un quart de ligne en PAL

Le PAL inverse la composante $V$ à chaque ligne. Cela change tout au calcul
précédent, car les deux composantes n'ont plus la même périodicité :

- $U$ n'est pas inversé : son motif se répète toutes les lignes, ses raies
  tombent en $f_{sc} \pm k f_H$ ;
- $V$ est inversé : son motif se répète toutes les **deux** lignes, ses raies
  tombent en $f_{sc} \pm (k + \tfrac12) f_H$.

Si l'on plaçait $f_{sc}$ sur un demi-entier comme en NTSC, $U$ serait
parfaitement entrelacé (partie fractionnaire 0,5) mais $V$ tomberait pile sur
les raies de luminance (partie fractionnaire 0). Le pire des cas.

La solution est le **quart de ligne** :

$$f_{sc} = \frac{1135}{4} f_H + 25\ \text{Hz} = 283{,}7516\, f_H = 4{,}433\,618\,75\ \text{MHz}$$

Avec une partie fractionnaire de 0,75 : $U$ se loge à 0,75 des entiers, $V$ à
0,25. **Les deux sont à égale distance des raies de luminance.** Ce n'est pas
aussi bon que le 0,5 du NTSC, mais c'est l'optimum quand il faut caser deux
peignes au lieu d'un.

Reste le mystérieux terme de +25 Hz. Il vaut exactement une demi-fréquence
trame, et sert à décaler le motif de sous-porteuse d'une image à la suivante,
pour que l'œil le moyenne au lieu de le voir immobile — le même raisonnement
que le demi-cycle du NTSC, appliqué au niveau de l'image.

> **Vérifié par** — `tests/test_porteuse.py::test_sous_porteuse_pal_et_son_decalage_de_25_hz`.

### 5.5 SECAM n'entrelace pas du tout

Les deux sous-porteuses SECAM sont des multiples **entiers** de la fréquence
ligne :

$$f_{OB} = 272\, f_H = 4{,}250\ \text{MHz}, \qquad
  f_{OR} = 282\, f_H = 4{,}406\,25\ \text{MHz}$$

Elles tombent donc **exactement sur les raies de luminance**. Il n'y a aucun
entrelacement spectral en SECAM, et il ne peut pas y en avoir : en modulation
de fréquence, la porteuse se déplace en permanence, un placement fin dans les
creux n'aurait aucun sens.

C'est une faiblesse réelle, et elle explique pourquoi le SECAM a dû recourir à
un autre moyen — le filtre « cloche » du §9.5 — pour rendre sa sous-porteuse
supportable.

> **Vérifié par** — `tests/test_porteuse.py::test_sous_porteuses_secam_sont_des_multiples_entiers`.

---

## 6. NTSC

### 6.1 La modulation en quadrature

Deux signaux indépendants doivent voyager sur une seule porteuse. La solution
est aussi vieille que la radio : les mettre en **quadrature**, c'est-à-dire sur
un sinus et un cosinus, qui sont orthogonaux.

$$C(t) = U \sin(\omega_{sc} t) + V \cos(\omega_{sc} t)$$

C'est une modulation d'amplitude **à porteuse supprimée** : quand $U = V = 0$,
$C$ est identiquement nul. La compatibilité noir et blanc est donc obtenue
gratuitement, par construction.

En écrivant $U = A\cos\delta$ et $V = A\sin\delta$, il vient

$$C(t) = A \sin(\omega_{sc} t + \delta)$$

d'où la lecture qui gouverne tout le reste :

> **L'amplitude de la sous-porteuse porte la saturation.
> Sa phase porte la teinte.**

C'est exactement ce qu'affiche un vectorscope, et c'est ce que montre le
panneau de droite de la figure suivante, où l'on distingue enfin la sinusoïde
sous l'escalier de luminance.

![Le signal composite d'une ligne](figures/06_signal_composite.png)

**Démodulation.** On multiplie par la référence locale :

$$
2\,C(t)\sin(\omega_{sc} t) = U\,(1 - \cos 2\omega_{sc} t) + V \sin 2\omega_{sc} t
\;\longrightarrow\; U + \text{termes à } 2\omega_{sc}
$$

$$
2\,C(t)\cos(\omega_{sc} t) = U \sin 2\omega_{sc} t + V\,(1 + \cos 2\omega_{sc} t)
\;\longrightarrow\; V + \text{termes à } 2\omega_{sc}
$$

Les produits à $2\omega_{sc}$ — vers 7,2 MHz — sont éliminés par le passe-bas
qui suit. Toute la précision du décodage repose donc sur **l'exactitude de
$\omega_{sc} t$**. Retenez cette phrase : c'est le sujet du chapitre 7.

> **Dans le code** — `porteuse.moduler_quadrature`, `porteuse.demoduler_quadrature`.

### 6.2 Le burst : d'où le récepteur tient sa référence de phase

Le récepteur doit régénérer localement une sous-porteuse **en phase** avec
celle de l'émetteur, alors que celle-ci n'est jamais transmise (porteuse
supprimée).

D'où le *burst* : neuf à dix cycles de sous-porteuse à phase de référence
(180°, soit l'axe $-U$), émis pendant le palier arrière de chaque ligne — dans
le temps de suppression, invisible à l'écran. Une boucle à verrouillage de
phase s'y accroche et maintient l'oscillateur local pendant les 52 µs de
l'image.

### 6.3 Les axes I et Q

NTSC ne module pas $U$ et $V$ directement, mais deux axes tournés de 33° :

$$
I = V\cos 33° - U\sin 33°, \qquad
Q = V\sin 33° + U\cos 33°
$$

soit, développé sur $R'G'B'$ :

$$
\begin{aligned}
I &= 0{,}596\,R' - 0{,}274\,G' - 0{,}322\,B' \\
Q &= 0{,}211\,R' - 0{,}523\,G' + 0{,}312\,B'
\end{aligned}
$$

Pourquoi 33° ? Parce que **l'acuité chromatique de l'œil n'est pas isotrope**.
Nous distinguons nettement mieux les variations fines le long de l'axe
orange–cyan que le long de l'axe vert–magenta. En alignant $I$ sur le premier
et $Q$ sur le second, on peut brider $Q$ beaucoup plus sévèrement :

| | bande | résolution horizontale utile |
|---|---|---|
| Luminance $Y'$ | 4,2 MHz | 442 points par ligne |
| $I$ (orange–cyan) | 1,3 MHz | 137 points par ligne |
| $Q$ (vert–magenta) | 0,4 MHz | **42 points par ligne** |

![Les axes I et Q du NTSC](figures/04_axes_iq.png)

Quarante-deux points de couleur par ligne. Personne ne s'en est jamais plaint,
et c'est la meilleure démonstration qui soit de la faiblesse de notre vision
chromatique.

**Ironie de l'histoire** : cette subtilité coûtait un filtre asymétrique et un
retard à compenser. La quasi-totalité des récepteurs grand public l'a
ignorée et a décodé les deux axes à la même bande étroite — le décodage dit
« I/Q égal ». L'un des plus beaux raffinements de la norme n'a presque jamais
été mis en œuvre.

### 6.4 Le piédestal de 7,5 IRE

En NTSC-M américain, le niveau de noir n'est pas au niveau de suppression : il
est 7,5 IRE au-dessus. Ce *setup* était destiné à garantir qu'aucune tolérance
de fabrication ne fasse descendre le noir dans la zone des synchros.

Il comprime l'excursion utile de 7,5 % et, surtout, il exige que le récepteur
en tienne compte. Un récepteur mal réglé — ou un signal NTSC-J, sans
piédestal, affiché sur un récepteur NTSC-M — donne des noirs gris.

![Le piédestal du NTSC-M](figures/19_piedestal.png)

Le Japon a normalisé le NTSC sans piédestal, ce qui explique en partie la
réputation d'images plus contrastées du NTSC-J.

> **Vérifié par** — `tests/test_pipeline.py::test_le_piedestal_remonte_le_niveau_de_noir`.

---

## 7. Le péché du NTSC : l'erreur de phase

### 7.1 La démonstration, en trois lignes

Supposons que le canal ait fait tourner la sous-porteuse d'un angle $\theta$.
Le récepteur démodule avec sa référence, décalée de $\theta$. On obtient :

$$
\begin{pmatrix} U' \\ V' \end{pmatrix} =
\begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix}
\begin{pmatrix} U \\ V \end{pmatrix}
$$

Une **rotation pure**. Le module — la saturation — est parfaitement conservé.
L'argument — la teinte — a tourné de $\theta$.

Et rien, absolument rien, ne permet au récepteur de faire la différence entre
un vert qui a tourné de 20° et un vert-jaune authentique. L'information est
détruite sans laisser de trace.

> **Vérifié par** — `tests/test_porteuse.py::test_une_erreur_de_phase_fait_tourner_la_teinte`.

### 7.2 Pourquoi cela arrive : la phase différentielle

L'étage de puissance d'un émetteur n'est pas parfaitement linéaire. Le
déphasage qu'il introduit dépend du **niveau instantané** du signal qui le
traverse. C'est ce qu'on appelle la *phase différentielle*, et on la mesure en
degrés de sous-porteuse par unité de luminance.

Conséquence : un même objet, dans l'ombre et en pleine lumière, n'a plus la
même teinte. Un visage devient vert dans les hautes lumières et magenta dans
les basses. Sur une longue liaison à plusieurs bonds, les erreurs
s'accumulent.

D'où le bouton **Tint** (ou *Hue*), présent sur tous les téléviseurs
américains et sur aucun téléviseur européen : il permettait au spectateur de
rattraper à la main la dérive du jour. Et d'où le surnom, dans les régies :

> *NTSC — Never Twice the Same Color.*

### 7.3 Modélisation honnête

Dans ce simulateur, la phase différentielle n'est pas appliquée en faisant
tourner artificiellement un vecteur de chrominance. Ce serait tricher, et
surtout cela fausserait la comparaison avec le SECAM.

On applique au signal composite entier un **retard variable avec le niveau** :

$$\tau(t) = \frac{\Delta\varphi}{360°} \cdot \frac{1}{f_{sc}} \cdot \text{niveau}(t)$$

C'est physiquement ce qu'est une phase différentielle, et cela a une
conséquence voulue : le SECAM y est naturellement insensible, puisqu'un retard
constant ne change pas une fréquence instantanée. Il n'y a aucun traitement de
faveur — le même signal traverse le même canal.

> **Dans le code** — `canal._erreurs_differentielles`.

![Vectorscope comparé](figures/08_vectorscope.png)

---

## 8. PAL

### 8.1 L'idée de Walter Bruch

*Phase Alternating Line.* À l'émission, **une ligne sur deux voit sa composante
$V$ inversée** :

$$C_n(t) = U \sin(\omega_{sc} t) \;\pm\; V \cos(\omega_{sc} t),
\qquad \text{signe} = (-1)^n$$

C'est tout. Une inversion de signe, un interrupteur électronique cadencé sur la
fréquence ligne. Et cela suffit à annuler l'erreur de phase.

### 8.2 La démonstration de l'annulation

Notons $s_n = \pm 1$ le signe de la ligne $n$. Le vecteur émis est $(U, s_n V)$.
Après une erreur de phase $\theta$ du canal, le récepteur démodule :

$$
\begin{aligned}
U'_n &= U\cos\theta - s_n V \sin\theta \\
V'_n &= s_n V\cos\theta + U \sin\theta
\end{aligned}
$$

Le récepteur, prévenu par le burst, rétablit le signe en multipliant $V'_n$
par $s_n$ (avec $s_n^2 = 1$) :

$$
\begin{aligned}
U'_n &= U\cos\theta - s_n V \sin\theta \\
V''_n &= V\cos\theta + s_n U \sin\theta
\end{aligned}
$$

Les termes parasites sont désormais **proportionnels à $s_n$**, donc de signes
opposés sur deux lignes consécutives. En moyennant la ligne $n$ et la ligne
$n-1$ :

$$
\bar U = U\cos\theta, \qquad \bar V = V\cos\theta
$$

$$
\boxed{\text{Erreur de teinte : nulle. Erreur de saturation : un facteur } \cos\theta.}
$$

C'est le tour de force du PAL : il ne supprime pas l'erreur, il la **convertit**
en une erreur d'une autre nature. Une dérive de teinte de 30° saute aux yeux ;
une perte de saturation de $1 - \cos 30° = 13\,\%$ est invisible.

> **Vérifié par** — `tests/test_porteuse.py::test_le_pal_annule_l_erreur_de_phase_en_moyennant_deux_lignes`,
> qui contrôle l'annulation à $10^{-9}$ près sur l'argument.

### 8.3 PAL-S et les barres de Hanover

Les premiers récepteurs PAL n'avaient pas de ligne à retard — un composant
coûteux à l'époque : une barre de verre de 64 µs de temps de propagation
ultrasonore. Ils s'en remettaient à **l'œil du spectateur** pour faire la
moyenne, en misant sur le fait que deux lignes voisines sont indiscernables à
distance normale. C'est le PAL-S, pour *simple*.

Cela fonctionne — tant que l'erreur reste petite. Au-delà, l'alternance de
teinte devient visible sous forme d'un striage horizontal : les **barres de
Hanover**, du nom de la ville où Bruch travaillait.

![Les barres de Hanover](figures/09_hanover.png)

À erreur identique, le NTSC (à droite) a vu toute son image dériver, le PAL-D
(à gauche) est intact, le PAL-S (au milieu) affiche des couleurs justes en
moyenne mais striées.

Le PAL-D — *delay* — généralise la ligne à retard et fait la moyenne
électroniquement. C'est ce que faisait tout récepteur à partir des années 1970.

> **Vérifié par** — `tests/test_pipeline.py::test_les_barres_de_hanover_apparaissent_sans_ligne_a_retard`.

### 8.4 Ce que le PAL paie

La moyenne de deux lignes n'est pas gratuite : **la résolution chromatique
verticale est divisée par deux.** En PAL-D, deux lignes consécutives partagent
leur chrominance.

Personne ne s'en est aperçu, pour la même raison que les 42 points de couleur
par ligne du NTSC : l'acuité chromatique de l'œil est trop faible pour en
souffrir. Mais c'est bien une perte, définitive, et le chapitre 11 la chiffre.

Le PAL paie aussi une seconde chose : **il est plus complexe**. Un interrupteur
de phase à l'émission, un burst oscillant, une ligne à retard et un
commutateur au récepteur. Cette complexité a longtemps été l'argument des
partisans du NTSC.

### 8.5 Le burst oscillant

Comment le récepteur sait-il quel est le signe de $V$ sur la ligne qui suit ?
Par le burst, dont la phase oscille de ±45° autour de la référence 180° :
**135° ou 225°**. Le récepteur en déduit à la fois sa référence de phase (la
moyenne des deux, 180°) et le signe de la ligne.

Sans cette indication, le récepteur afficherait les couleurs complémentaires
une ligne sur deux.

> **Dans le code** — `porteuse.signe_pal`, `porteuse.phase_burst_pal`.

---

## 9. SECAM

### 9.1 Un pari radicalement différent

Henri de France part du même constat que Bruch — l'erreur de phase est le
fléau du NTSC — mais en tire la conclusion inverse. Plutôt que de compenser
l'erreur de phase, **supprimons la phase comme porteuse d'information**.

*Séquentiel Couleur À Mémoire.* Deux décisions, chacune radicale :

1. **Séquentiel** : on n'émet plus les deux composantes en même temps. Chaque
   ligne n'en porte qu'une, en alternance : $D'_B$, puis $D'_R$, puis $D'_B$…
2. **À mémoire** : le récepteur conserve la ligne précédente dans une ligne à
   retard de 64 µs, et reconstitue ainsi le couple manquant.

Et puisqu'une seule composante occupe la ligne, on peut se permettre une
**modulation de fréquence**, qui aurait été impensable pour deux signaux
simultanés.

### 9.2 Le matriçage

$$D'_B = +1{,}505\,(B'-Y'), \qquad D'_R = -1{,}902\,(R'-Y')$$

Les facteurs sont plus grands qu'en PAL parce que l'amplitude n'a plus à
cohabiter avec la luminance dans la même excursion — c'est la fréquence qui
porte l'information. Le signe négatif de $D'_R$ est un choix de norme qui
équilibre les excursions positives et négatives après préaccentuation.

### 9.3 La modulation de fréquence

Deux sous-porteuses, une par type de ligne :

$$f_{OB} = 4{,}250\ \text{MHz}\ (272 f_H), \qquad f_{OR} = 4{,}406\,25\ \text{MHz}\ (282 f_H)$$

La fréquence instantanée s'écarte du repos proportionnellement au signal :

$$f(t) = f_{O\!X} + \Delta_X \cdot D'_X(t)$$

avec $\Delta_B = 280$ kHz et $\Delta_R = 230$ kHz par unité, et un écrêtage de
l'excursion à $-506$ / $+350$ kHz.

![La modulation de fréquence SECAM](figures/15_fm_secam.png)

Le panneau du haut montre la fréquence instantanée réellement mesurée sur le
signal simulé : chaque palier correspond à une barre de couleur. Le panneau du
bas montre, pour comparaison, un signal PAL où c'est **l'amplitude** qui porte
la saturation.

Comparez les deux panneaux inférieurs. En PAL, l'amplitude tombe **exactement à
zéro** sur le blanc et sur le noir. En SECAM, elle ne s'annule jamais.

### 9.4 La préaccentuation basse fréquence

Avant modulation, le signal de différence de couleur passe dans un filtre qui
relève ses hautes fréquences :

$$A(f) = \frac{1 + j f/f_1}{1 + j f/(3 f_1)}, \qquad f_1 = 85\ \text{kHz}$$

Gain unité en continu, plafond à un rapport 3 (9,5 dB) en haute fréquence. Au
décodage, la désaccentuation inverse rabaisse ces fréquences — **et avec elles
le bruit que le canal y a déposé**. C'est rigoureusement le principe du Dolby B
sur une cassette audio.

### 9.5 Le filtre cloche : l'astuce qui rend le SECAM regardable

Nous avons vu au §5.5 que les sous-porteuses SECAM tombent sur les raies de
luminance, sans le moindre entrelacement. Et §9.3 que la porteuse est émise en
permanence, même sur du gris. Sans précaution, un mur blanc afficherait donc un
motif de sous-porteuse parfaitement visible.

D'où le **filtre cloche**, appliqué à la sous-porteuse déjà modulée :

$$G(F) = M_0\,\frac{1 + 16\,jF}{1 + 1{,}26\,jF},
\qquad F = \frac{f}{f_0} - \frac{f_0}{f},
\qquad f_0 = 4{,}286\ \text{MHz}$$

$f_0$ est placé à mi-chemin entre les deux sous-porteuses, et la courbe a la
forme d'une cloche **inversée** : minimum au repos, remontée de part et d'autre.

![Les préaccentuations SECAM](figures/14_preaccentuations_secam.png)

Le résultat est exactement ce qu'on cherche :

> Plus la couleur est proche du gris, plus la fréquence instantanée est proche
> du repos, **et plus la sous-porteuse est atténuée**.

Sur les zones neutres — c'est-à-dire la majeure partie d'une image ordinaire —
le motif devient discret. Sur les zones saturées, il est plus fort, mais la
couleur elle-même le masque.

Mesuré sur le simulateur : l'amplitude crête de la sous-porteuse vaut 0,25 au
repos contre 0,64 à pleine excursion, soit un rapport de 2,6.

> **Vérifié par** — `tests/test_pipeline.py::test_secam_emet_sa_sous_porteuse_meme_sur_du_gris`.

### 9.6 Le décodage

1. passe-bande autour de 3,35 – 5,3 MHz ;
2. **anti-cloche**, inverse exact de la préaccentuation haute fréquence,
   appliqué **avant** le limiteur puisqu'il rétablit de l'amplitude ;
3. **limiteur** puis **discriminateur de fréquence** — dans le simulateur, un
   détecteur à quadrature : on ramène la sous-porteuse en bande de base avec un
   oscillateur local à la fréquence de repos, et l'écart de fréquence est la
   dérivée de l'argument du vecteur complexe obtenu. Prendre l'argument, c'est
   ignorer complètement le module : **le limiteur, gratuitement** ;
4. désaccentuation basse fréquence ;
5. **mémoire de ligne** : la composante manquante vient de la ligne précédente.

> **Dans le code** — `decodeur._decoder_secam`, `porteuse.demoduler_frequence`.

### 9.7 Les forces et les faiblesses, sans complaisance

**Ce que le SECAM gagne.**

- **Immunité totale aux erreurs de phase.** Un retard ne change pas une
  fréquence. Mesuré sur le simulateur : à 60° de phase différentielle, l'erreur
  de teinte SECAM est de 0,0° et la perte de saturation de 0,8 %, contre 17° de
  dérive de teinte en NTSC.
- **Immunité aux erreurs de gain.** Le limiteur écrase toute information
  d'amplitude avant le discriminateur.
- **Excellente tenue sur les longues liaisons** à multiples bonds — argument
  décisif pour un pays au relief accidenté et au réseau très ramifié.

> **Vérifié par** — `tests/test_pipeline.py::test_reponse_des_trois_normes_a_la_phase_differentielle`
> et `::test_secam_ignore_le_gain_differentiel`.

**Ce que le SECAM perd.**

- **La résolution chromatique verticale, divisée par deux**, comme le PAL-D —
  mais ici c'est structurel et irrécupérable : l'information n'a jamais été
  émise.
- **La compatibilité parfaite avec le noir et blanc.** La porteuse est toujours
  là.
- **Et surtout : on ne peut rien faire d'un signal SECAM.** Aucun fondu, aucun
  mélange, aucune incrustation, aucun trucage. Additionner deux signaux FM ne
  produit pas la somme des couleurs ; en atténuer un ne le désature pas, cela
  ne fait qu'affaiblir la porteuse. Les régies françaises travaillaient donc en
  composantes ou en PAL, et ne codaient en SECAM qu'au tout dernier moment,
  à l'émission.

C'est là le vrai jugement porté sur le SECAM par l'histoire : excellent pour
**transmettre**, inutilisable pour **produire**.

### 9.8 L'identification

Comment le récepteur sait-il si la ligne courante porte $D'_B$ ou $D'_R$ ? Par
des signaux d'identification placés dans la suppression : d'abord des
« bouteilles » — des salves à fréquence variable réparties sur neuf lignes de
la suppression trame — puis, à partir des années 1970, des salves de référence
aux fréquences de repos placées sur le palier arrière de chaque ligne.

---

## 10. Décoder : réjecteur, peigne, et les artefacts qui en naissent

Le récepteur reçoit un seul signal, $S = Y' + C$, et doit en extraire deux. La
tâche est **fondamentalement impossible à faire exactement** : les deux spectres
s'interpénètrent. Tout séparateur est un compromis, et chaque compromis engendre
son artefact.

### 10.1 Le réjecteur

Le plus simple : un filtre coupe-bande centré sur la sous-porteuse.

$$Y'_{\text{estimée}} = \text{coupe-bande}_{f_{sc}}(S), \qquad
  C_{\text{estimée}} = \text{passe-bande}_{f_{sc}}(S)$$

Détail qui a son importance et que beaucoup de simulateurs manquent : ces deux
filtres sont **indépendants**, pas complémentaires. Un vrai piège LC est étroit
(±0,6 MHz), tandis que la voie chroma est large (±1,3 MHz). Leur somme ne
reconstitue pas le composite.

Si l'on imposait la complémentarité, le piège devrait être aussi large que la
bande de chrominance et avalerait toute trace de sous-porteuse : **aucun dot
crawl n'apparaîtrait**. On aurait simulé un téléviseur qui n'a jamais existé.

> **Dans le code** — `decodeur.LARGEUR_TRAP` et la docstring qui l'accompagne.

**Le coût.** Toute la luminance située dans la bande rejetée disparaît. Une
chemise à fines rayures perd sa texture. Et les bandes latérales de la
chrominance, elles, passent dans la voie luminance : c'est le **dot crawl**.

### 10.2 Le filtre en peigne

En NTSC, la sous-porteuse tourne exactement de 180° d'une ligne à la suivante.
La chrominance change donc de signe, tandis que la luminance, elle, reste
presque identique. D'où :

$$
Y' = \frac{L_n + L_{n-1}}{2}, \qquad
C = \frac{L_n - L_{n-1}}{2}
$$

Une soustraction, une addition, et une ligne à retard. La séparation est
**exacte** partout où l'hypothèse « la luminance ne change pas d'une ligne à
l'autre » est vraie — c'est-à-dire partout sauf sur les contours horizontaux.

**En PAL**, une ligne de retard ne convient pas : l'avance de phase vaut
270,576°, pas 180°. Mais sur **deux** lignes elle vaut $2 \times 270{,}576 =
541{,}15° \equiv 181{,}15°$ modulo un tour — assez proche de l'inversion pour
que le peigne fonctionne. C'est exactement pourquoi les peignes PAL utilisent
un retard de 2H (128 µs) là où les peignes NTSC se contentent de 1H.

**En SECAM**, aucun peigne n'est possible : les sous-porteuses étant des
multiples entiers de $f_H$, elles retombent en phase à chaque ligne et ne
s'inversent jamais.

> **Vérifié par** — `tests/test_porteuse.py::test_ntsc_tourne_de_180_degres_par_ligne`
> et `::test_pal_tourne_de_270_degres_par_ligne`.

### 10.3 Le dot crawl : le peigne ne le supprime pas, il le déplace

![Dot crawl](figures/10_dot_crawl.png)

C'est l'une des figures les plus instructives de ce cours, et elle mérite qu'on
s'y arrête.

- **Réjecteur** (colonne de gauche) : le motif de points apparaît sur les
  contours **verticaux** des aplats colorés. Là, la chrominance a des bandes
  latérales larges qui débordent du piège étroit et fuient dans la luminance.
- **Peigne** (colonne du milieu) : ces contours-là sont impeccables. Mais
  l'hypothèse de similarité entre lignes s'effondre sur les contours
  **horizontaux**, où le motif réapparaît en damier.
- **Séparation parfaite** (colonne de droite) : ni l'un ni l'autre. Ce décodeur
  n'existe pas ; il sert de référence pour mesurer ce que les deux autres
  coûtent.

Mesuré sur le simulateur : sur le flanc vertical d'un pavé rouge, l'alternance
ligne à ligne de la luminance vaut 0,065 avec le réjecteur et 0,000 avec le
peigne. Sur l'arête horizontale, c'est l'inverse : 0,0001 contre 0,022.

> **Vérifié par** — `tests/test_pipeline.py::test_le_dot_crawl_apparait_et_le_peigne_le_deplace`.

### 10.4 Le cross-color

L'artefact symétrique. Si de la chrominance peut fuir dans la voie luminance,
de la luminance peut fuir dans la voie chrominance.

Un détail fin de l'image — une veste à rayures, une grille, un toit de tuiles —
produit dans le signal une composante à haute fréquence spatiale. Si cette
fréquence tombe près de la sous-porteuse, **le décodeur n'a aucun moyen de
savoir qu'il s'agit de luminance**. Il la démodule, et sort une couleur.

![Le cross-color](figures/11_cross_color.png)

La mire d'entrée est **strictement en noir et blanc** : sa fréquence spatiale
croît linéairement de 0 à 6 MHz. La courbe du bas mesure la saturation
parasite qui en ressort. Elle est nulle en basse fréquence, culmine autour de
la sous-porteuse, retombe au-delà.

C'est la hantise des présentateurs de journal télévisé, à qui l'on interdisait
les vestes à fines rayures et les cravates à motifs serrés.

> **Vérifié par** — `tests/test_pipeline.py::test_le_cross_color_colore_une_mire_en_noir_et_blanc`,
> qui contrôle qu'une mire monochrome ressort avec une saturation supérieure à
> 0,15 sur plus de 10 % de sa surface.

### 10.5 Le comportement au bruit

![Le comportement au bruit](figures/16_bruit.png)

Trois signatures différentes pour le même bruit :

- **NTSC** — le bruit perturbe la phase, donc la **teinte**. Les aplats
  colorés se mettent à moucheter en couleurs voisines.
- **PAL** — la ligne à retard convertit une partie de ce bruit de phase en
  bruit de saturation, moins visible. En revanche la moyenne de deux lignes
  bruitées améliore de 3 dB le rapport signal/bruit chromatique : le PAL est
  franchement meilleur que le NTSC sur ce terrain.
- **SECAM** — le discriminateur ignore le bruit tant qu'il reste inférieur au
  signal. Les couleurs restent parfaitement saturées et stables alors que la
  luminance, elle, est déjà bien grenue. Mais quand le bruit devient assez
  fort pour faire **décrocher** le discriminateur, l'écart de fréquence part
  brutalement et produit des taches colorées vives et isolées : le « feu »
  caractéristique des images SECAM très bruitées.

---

## 11. Ce que tout cela fait au RGB d'origine

Chapitre de synthèse. On rassemble ici tout ce que la chaîne a prélevé sur
l'image de départ, dans l'ordre où elle le prélève, avec les chiffres mesurés.

### 11.1 La non-constant-luminance

C'est la perte la plus profonde, et la moins connue.

Le codeur calcule $Y'$ à partir de composantes **déjà gamma-corrigées**. La
luminance que transporte réellement la voie $Y$ n'est donc pas la luminance de
la couleur, mais $(Y')^\gamma$. Ces deux quantités ne coïncident que sur les
gris — car $x^\gamma$ n'est pas linéaire, et la moyenne des racines n'est pas
la racine de la moyenne.

Sur les couleurs saturées, l'écart est vertigineux :

| Couleur | Part de la luminance portée par $Y'$ ($\gamma = 2{,}2$) | ($\gamma = 2{,}8$) |
|---|---|---|
| Jaune | 86,5 % | 80,4 % |
| Cyan | 65,3 % | 52,8 % |
| Vert | 52,8 % | 38,3 % |
| Magenta | 34,6 % | 20,4 % |
| Rouge | 23,5 % | 11,4 % |
| **Bleu** | **7,4 %** | **2,0 %** |
| Gris | 100,0 % | 100,0 % |

![La non-constant-luminance](figures/02_non_constant_luminance.png)

Sur un bleu saturé en PAL, **98 % de la luminance de la couleur voyage dans les
signaux de chrominance** — que l'on va justement filtrer à 1,3 MHz, six fois
moins large que la luminance.

C'est pour cela que les rouges et les bleus saturés de la télévision analogique
sont mous, baveux, et qu'un générique en lettres rouges sur fond noir est
illisible. Ce n'est pas un défaut de réglage : c'est inscrit dans le principe
même du système.

> **Dans le code** — `mesures.bilan_luminance`.
> **Vérifié par** — `tests/test_pipeline.py::test_bilan_de_non_constant_luminance`.

### 11.2 La résolution horizontale de la couleur

Une bande de $B$ hertz sur une ligne active de durée $T$ porte $B \cdot T$
alternances, soit $2BT$ points utiles.

| | Luminance | Chrominance 1 | Chrominance 2 |
|---|---|---|---|
| NTSC-M | 4,2 MHz → **442 pts/ligne** | $I$ : 1,3 MHz → 137 | $Q$ : 0,4 MHz → **42** |
| PAL-B/G | 5,0 MHz → **520 pts/ligne** | $U$ : 1,3 MHz → 135 | $V$ : 1,3 MHz → 135 |
| SECAM-L | 6,0 MHz → **623 pts/ligne** | $D'_B$ : 1,5 MHz → 156 | $D'_R$ : 1,5 MHz → 156 |

Autrement dit : **environ quatre fois moins de définition en couleur qu'en
luminance**, horizontalement. Une transition franche de couleur met quatre fois
plus de temps à s'établir qu'une transition de luminance.

![La chrominance bave](figures/12_bande_chroma.png)

Sur cette transition blanc → jaune mesurée, la luminance bascule en 70 ns
(temps de montée $0{,}35/B$ pour 5 MHz), la chrominance en 270 ns. La couleur
déborde donc du contour, et c'est très exactement ce que l'on voit quand un
générique rouge « bave » sur le noir.

> **Vérifié par** — `tests/test_pipeline.py::test_la_chrominance_bave_horizontalement`.

### 11.3 La résolution verticale de la couleur

![La résolution chromatique verticale](figures/13_resolution_verticale.png)

| | Lignes de chrominance |
|---|---|
| NTSC | 480 — pleine résolution |
| PAL-S (sans ligne à retard) | 576 — pleine résolution |
| **PAL-D** | **288** — la ligne à retard moyenne deux lignes |
| **SECAM** | **288** — le séquentiel n'en transmet qu'une sur deux |

PAL-D et SECAM paient tous deux leur robustesse de la même monnaie, pour des
raisons différentes : le PAL par le traitement du récepteur, le SECAM par
l'émission elle-même.

### 11.4 Les artefacts de diaphotie

Récapitulés au chapitre 10 : dot crawl, cross-color, motif de sous-porteuse.
Ils n'enlèvent rien à l'information — ils en **ajoutent** qui n'y était pas.
C'est pire, à certains égards, qu'une simple perte de résolution : une image
floue reste une image juste ; une image qui invente des couleurs est une image
fausse.

### 11.5 La rotation de teinte et la perte de saturation

![Erreur de teinte selon la phase différentielle](figures/07_erreur_teinte.png)

Cette figure est la synthèse quantitative de tout le cours. Le même canal
dégradé traverse les trois normes ; seule la façon de coder la couleur diffère.

| Phase différentielle du canal | 60° |
|---|---|
| NTSC — erreur de teinte | **−17°** |
| PAL-D — erreur de teinte | 0,0° |
| PAL-D — perte de saturation | 3,4 % |
| PAL-S — striage ligne à ligne | **30°** (barres de Hanover) |
| SECAM — erreur de teinte | 0,0° |
| SECAM — perte de saturation | 0,8 % |

### 11.6 L'écrêtage hors gamut

Après matriçage inverse, rien ne garantit que le triplet $(R', G', B')$ obtenu
soit dans le cube $[0,1]^3$. Le bruit, la limitation de bande, les dépassements
des filtres poussent régulièrement les valeurs au-delà.

Le tube ne sait pas produire une luminance négative, ni plus de lumière que son
maximum. On écrête. Et **l'écrêtage d'un seul canal déplace la teinte** : il ne
se contente pas de désaturer.

Mesuré sur une mire de barres à 75 %, avec un canal parfait : 24 % des pixels
en PAL, 31 % en NTSC sont écrêtés d'au moins un échelon sur huit bits — presque
exclusivement dans les zones de transition, où le dépassement atteint 0,29.

### 11.7 Le niveau de noir

Le piédestal de 7,5 IRE du NTSC-M comprime l'excursion utile d'autant. La
chaîne complète le compense correctement, mais toute désadaptation entre
l'émission et le récepteur se traduit par un noir gris ou des basses lumières
bouchées.

### 11.8 La dérive colorimétrique

Enfin, si l'image d'origine est interprétée dans les primaires de la norme
(§2.2), une désaturation globale s'ajoute à tout le reste — spectaculaire avec
les primaires NTSC 1953.

### 11.9 Le bilan chiffré

![Bilan](figures/18_bilan.png)

Et, sur une image continue plutôt qu'une mire, le résultat visuel :

![Les trois normes côte à côte](figures/17_comparaison.png)

**Écart colorimétrique moyen ΔE\*ab**, canal parfait, décodeur normal :

| Mire | NTSC-M | PAL-B/G | SECAM-L |
|---|---|---|---|
| Barres de couleur 75 % | 4,11 | **2,51** | 7,14 |
| Roue de teintes | 1,43 | **1,03** | 2,20 |
| Dégradé de saturation | **0,14** | 0,25 | 0,93 |

Rappel d'échelle : $\Delta E \approx 1$ est le seuil de perception d'un
observateur entraîné, $\Delta E \approx 3$ une différence évidente pour
quiconque.

**Comment lire ce tableau.** Les mires de barres et la roue de teintes sont
saturées de transitions franches : elles mesurent surtout le comportement aux
contours, où le SECAM est le plus faible (FM plus étalée, mémoire de ligne).
Le dégradé de saturation, lui, est presque partout plat : il mesure la
fidélité en régime établi, et l'ordre s'inverse — le NTSC y est le meilleur,
parce qu'il ne perd rien verticalement.

Et surtout : ces chiffres décrivent un **canal parfait**. C'est précisément la
situation qui n'existe jamais. Dès que le canal se dégrade — et c'était la
règle en hertzien, en réception d'antenne râteau, après plusieurs bonds de
faisceau — le classement change du tout au tout, comme le montre le §11.5.

> **C'est là toute la leçon de ce cours.** Chacun des trois systèmes est
> optimal pour la question qu'il s'est posée. Le NTSC a choisi la simplicité et
> l'a payée en fidélité de teinte. Le PAL a choisi de compenser et l'a payé en
> complexité et en résolution verticale. Le SECAM a choisi la robustesse et l'a
> payée en flexibilité de production. Aucun des trois n'a eu tort.

---

## 12. Annexes

### A. Tableau des constantes

| | NTSC-M | PAL-B/G | SECAM-L |
|---|---|---|---|
| Norme UIT-R | BT.470-M | BT.470-B/G | BT.470-L |
| Lignes totales / actives | 525 / 480 | 625 / 576 | 625 / 576 |
| Trames par seconde | 59,940 059… | 50 | 50 |
| Fréquence ligne $f_H$ | 15 734,264 Hz | 15 625 Hz | 15 625 Hz |
| Durée de ligne active | 52,6 µs | 51,95 µs | 51,95 µs |
| Sous-porteuse | 3,579 545 MHz = $\frac{455}{2} f_H$ | 4,433 618 75 MHz = $(\frac{1135}{4} + \frac{1}{625}) f_H$ | $f_{OB}$ 4,250 MHz = $272 f_H$ <br> $f_{OR}$ 4,406 25 MHz = $282 f_H$ |
| Rotation par ligne | 180,000° | 270,576° | 0° |
| Bande luminance | 4,2 MHz | 5,0 MHz | 6,0 MHz |
| Bande chrominance | $I$ 1,3 / $Q$ 0,4 MHz | $U$, $V$ 1,3 MHz | ≈ 1,5 MHz |
| Modulation | QAM sur $I$/$Q$ | QAM, $V$ alterné | FM séquentielle |
| Piédestal | 7,5 IRE (0 au Japon) | 0 | 0 |
| Burst | 9 cycles à 180° | 10 cycles à 135°/225° | identification en suppression |
| Primaires | SMPTE-C (1953 à l'origine) | EBU | EBU |
| Gamma supposé | 2,2 | 2,8 | 2,8 |

**Matrices de matriçage** (composantes gamma-corrigées) :

$$
\begin{pmatrix} Y' \\ U \\ V \end{pmatrix} =
\begin{pmatrix}
0{,}299 & 0{,}587 & 0{,}114 \\
-0{,}147 & -0{,}289 & 0{,}436 \\
0{,}615 & -0{,}515 & -0{,}100
\end{pmatrix}
\begin{pmatrix} R' \\ G' \\ B' \end{pmatrix}
$$

$$
\begin{pmatrix} Y' \\ I \\ Q \end{pmatrix} =
\begin{pmatrix}
0{,}299 & 0{,}587 & 0{,}114 \\
0{,}596 & -0{,}274 & -0{,}322 \\
0{,}211 & -0{,}523 & 0{,}312
\end{pmatrix}
\begin{pmatrix} R' \\ G' \\ B' \end{pmatrix}
$$

$$
\begin{pmatrix} Y' \\ D'_R \\ D'_B \end{pmatrix} =
\begin{pmatrix}
0{,}299 & 0{,}587 & 0{,}114 \\
-1{,}333 & 1{,}116 & 0{,}217 \\
-0{,}450 & -0{,}883 & 1{,}333
\end{pmatrix}
\begin{pmatrix} R' \\ G' \\ B' \end{pmatrix}
$$

Inverses :

$$
\begin{aligned}
R' &= Y' + 1{,}140\,V \\
G' &= Y' - 0{,}395\,U - 0{,}581\,V \\
B' &= Y' + 2{,}032\,U
\end{aligned}
\qquad\qquad
\begin{aligned}
R' &= Y' + 0{,}956\,I + 0{,}621\,Q \\
G' &= Y' - 0{,}272\,I - 0{,}647\,Q \\
B' &= Y' - 1{,}106\,I + 1{,}703\,Q
\end{aligned}
$$

> **Vérifié par** — `tests/test_matrices.py`, qui compare chacune de ces
> matrices aux valeurs publiées.

### B. Pourquoi la France a choisi le SECAM

Trois raisons, qu'il serait malhonnête de réduire à une seule.

**Technique.** Le SECAM est objectivement meilleur sur les longues liaisons
hertziennes à bonds multiples, où les erreurs de phase s'accumulent. Le réseau
français, dense en réémetteurs et servant un territoire au relief accidenté,
était précisément le cas d'usage le plus favorable. Le SECAM supporte aussi
mieux la transmission par câble long et les enregistreurs à bande de l'époque.

**Industrielle.** Henri de France et la Compagnie française de télévision
détenaient les brevets. Adopter le PAL, c'était payer des royalties à
Telefunken et laisser l'industrie allemande équiper le marché français.

**Politique.** L'adoption d'un standard national s'inscrivait dans la politique
d'indépendance technologique de la France gaullienne, au même titre que la
force de dissuasion ou le Concorde. Le choix du SECAM par l'URSS et le bloc de
l'Est en 1967, puis par une grande partie de l'Afrique francophone et du
Moyen-Orient, en a fait un instrument d'influence autant qu'une norme technique.

Les trois raisons sont vraies simultanément. Prétendre que le SECAM était
techniquement injustifié est faux ; prétendre que la technique seule a décidé
l'est tout autant.

### C. MESECAM

Au Moyen-Orient, les magnétoscopes VHS destinés au SECAM n'utilisaient pas la
méthode française. Un magnétoscope ne peut pas enregistrer la sous-porteuse
telle quelle : il la transpose vers le bas (*color under*). Les magnétoscopes
français transcodaient réellement le SECAM ; les magnétoscopes MESECAM se
contentaient de translater la bande de chrominance, comme pour du PAL.

Résultat : les deux méthodes sont **incompatibles**. Une cassette MESECAM lue
sur un magnétoscope français donne des couleurs fausses, et réciproquement.
C'est l'une des rares occasions où l'incompatibilité n'était pas voulue.

### D. Pour aller plus loin

**Normes.**
- UIT-R BT.470-6, *Conventional Television Systems* — la référence, qui
  contient tous les tableaux de constantes utilisés ici.
- UIT-R BT.601-7, *Studio encoding parameters of digital television*.
- SMPTE 170M-2004, *Composite Analog Video Signal — NTSC for Studio Applications*.
- EBU Tech. 3213, *EBU Standard for Chromaticity Tolerances for Studio Monitors*.

**Ouvrages.**
- Charles Poynton, *Digital Video and HD: Algorithms and Interfaces*. Le
  meilleur exposé moderne du gamma, de la non-constant-luminance et des
  matrices de matriçage.
- K. Blair Benson, *Television Engineering Handbook*. La référence classique
  sur les systèmes analogiques.
- Keith Jack, *Video Demystified*. Très pratique, plein de tableaux de valeurs
  numériques directement utilisables.

**Historique.**
- Donald Fink, *Color Television Standards* (1955) — les rapports du NTSC,
  publiés à chaud.
- Les brevets d'Henri de France sur le SECAM, et ceux de Walter Bruch sur le PAL.

---

## Le simulateur

Ce cours est indissociable du code qui l'accompagne.

```
tvcolor/          la bibliothèque de simulation (numpy pur, sans Qt)
  constantes.py     toutes les constantes normatives
  colorimetrie.py   primaires, blancs, gamma, CIELAB
  matrices.py       matriçage et dérivation des constantes
  filtres.py        limitation de bande, peignes, préaccentuations SECAM
  porteuse.py       l'horloge de sous-porteuse — le cœur horaire
  encodeur.py       R'G'B' → signal composite
  canal.py          bruit, phase et gain différentiels, écho
  decodeur.py       séparation Y/C, démodulation
  pipeline.py       la chaîne complète
  mires.py          les mires de test
  mesures.py        vectorscope, spectres, ΔE, résolutions

gui/              l'interface PyQt5
tests/            58 tests, dont ceux cités tout au long de ce cours
docs/             ce document et son générateur de figures
```

**Lancer l'interface :**

```bash
python -m gui
```

**Régénérer toutes les figures :**

```bash
python docs/generer_figures.py
```

**Vérifier que tout tient debout :**

```bash
python -m pytest tests/ -v
```

Le principe directeur du simulateur mérite d'être répété une dernière fois :
le signal composite est reconstruit ligne par ligne, échantillonné à quatre
fois la sous-porteuse, puis décodé comme le ferait un téléviseur. Les
artefacts — points rampants, moirages irisés, barres de Hanover, feu SECAM —
ne sont **jamais dessinés**. Ils émergent du calcul. C'est la seule façon
d'être sûr que ce que l'on regarde est vrai.
