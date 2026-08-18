# Arty : écrire du son dans l'onde de l'image

### Six opérateurs à modulation de fréquence, injectés dans le composite

---

Un signal composite est une onde. Une pile d'opérateurs à modulation de
fréquence — celle d'un DX7 — en est une autre. Les additionner revient
exactement à ce que fait un brouilleur sur une antenne.

Et le résultat n'est pas un effet plaqué sur l'image : c'est le **décodeur du
téléviseur** qui interprète l'intrus, et qui en fait des barres, des damiers ou
de la couleur selon la fréquence. La géométrie qu'on voit n'est pas dessinée,
elle est *déduite* du rapport entre la fréquence du son et celle du balayage.

**Table des matières**

1. [Où le son rencontre l'image](#1-où-le-son-rencontre-limage)
2. [Les trois cas, et le quatrième](#2-les-trois-cas-et-le-quatrième)
3. [La synthèse : ce qui est du DX7, ce qui ne l'est pas](#3-la-synthèse--ce-qui-est-du-dx7-ce-qui-ne-lest-pas)
4. [L'enveloppe se lit de haut en bas](#4-lenveloppe-se-lit-de-haut-en-bas)
5. [Ce que cet outil ne touche pas](#5-ce-que-cet-outil-ne-touche-pas)

---

## 1. Où le son rencontre l'image

Tout tient dans une formule. Un composite est un signal **à une dimension** ; le
tableau à deux dimensions qu'on manipule n'est qu'un pliage. L'échantillon $k$
de la ligne $n$ est émis à l'instant

$$t(n, k) = \frac{n}{f_H} + \frac{k}{f_e}$$

Une sinusoïde de fréquence $f$ ajoutée à ce signal y dessine donc :

- $f / f_H$ **cycles par ligne**, c'est-à-dire autant de barres verticales ;
- et une avance de phase d'une ligne à la suivante de $2\pi f / f_H$, dont seule
  la partie fractionnaire compte.

Un détail du pliage vaut d'être noté, parce qu'il remonte de loin. À quatre fois
la sous-porteuse, une ligne de 625 lignes vaut **1135,0064** périodes
d'échantillonnage, et non 1135 tout rond : la grille n'est pas verrouillée sur
la ligne. C'est ce quatre-millième qui donne à la sous-porteuse son avance de
270,576° par ligne — le décalage en $+1/625$ du chapitre 8 du cours, qu'on
retrouve ici sous une autre forme.

## 2. Les trois cas, et le quatrième

| $f / f_H$ | avance par ligne | ce qu'on voit |
|---|---|---|
| entier | 0° | barres verticales **immobiles** |
| demi-entier | 180° | damier, une ligne sur deux inversée |
| quelconque | le reste | barres **penchées**, d'autant plus que le reste est grand |

Ces trois-là sont vérifiés par la mesure et non par l'œil : à $8\,f_H$, deux
lignes voisines de la perturbation sont identiques à $10^{-9}$ près ; à
$8{,}5\,f_H$, elles sont exactement **opposées** ; et le nombre d'alternances
comptées sur une ligne vaut $f / f_H$ à une barre près.

Le quatrième cas est le plus spectaculaire. Si $f$ tombe près de la
sous-porteuse, le décodeur ne peut plus faire la différence entre l'intrus et de
la chrominance. **Il choisit la couleur.** Une mire en niveaux de gris se met
alors à teinter, sans qu'on l'ait demandé — c'est le cross-color du chapitre 10,
provoqué exprès.

La mesure est nette. Saturation moyenne de l'image rendue, même onde, même
niveau (0,20), mire en niveaux de gris :

| fréquence injectée | saturation moyenne |
|---|---|
| 600 kHz | 7·10⁻¹⁴ |
| 2,0 MHz | 7·10⁻¹⁴ |
| 3,5 MHz | 6·10⁻¹³ |
| $f_{sc} - 300$ kHz | 0,017 |
| $f_{sc}$ | 0,085 |

Sous la bande de chrominance il n'en sort **rien du tout** — les valeurs à
10⁻¹³ sont le bruit de calcul en virgule flottante, pas un résidu. Le
séparateur peigne fait proprement son travail. Puis, dans la bande, la couleur
apparaît d'un coup.

## 3. La synthèse : ce qui est du DX7, ce qui ne l'est pas

Un opérateur est une sinusoïde dont la phase est modulée par la sortie d'un
autre :

$$\text{out}_i(t) = A_i(t)\, \sin\Big( 2\pi f_i t + \varphi_i + \sum_j M_{ij}\, \text{out}_j(t) \Big)$$

C'est tout. La richesse vient de l'agencement.

**Pourquoi la modulation de fréquence** plutôt qu'une somme de sinus : parce que
le nombre d'harmoniques y est réglable d'un seul bouton. Une porteuse $f_p$
modulée par $f_m$ avec l'indice $\beta$ contient les raies $f_p \pm k f_m$, dont
l'amplitude est la fonction de Bessel $J_k(\beta)$ — au-delà de $k = \beta + 1$,
elles décroissent. Monter l'indice, c'est ouvrir l'éventail des harmoniques, et
donc passer d'une barre franche à une texture fine. Un test le mesure, sur une
modulante de 1 kHz, en cherchant la dernière raie au-dessus de 2 % du maximum :
$\beta = 0{,}5 \to 3$ kHz, $\beta = 2 \to 5$ kHz, $\beta = 6 \to 10$ kHz. Le
seuil de 2 % est généreux — $\beta + 1$ marque le début de la chute, pas la fin
du spectre.

**Sont repris du DX7** : six opérateurs, les rapports de fréquence entiers ou
fractionnaires, le mode à fréquence fixe, les enveloppes à quatre segments, et
la rétroaction d'un opérateur sur lui-même.

**N'est pas repris : la table des trente-deux algorithmes.** On lui préfère une
matrice de modulation $6 \times 6$ quelconque, qui les contient tous et bien
d'autres. Les agencements proposés sont donc nommés d'après ce qu'ils font —
*additif*, *chaîne*, *deux piles*, *éventail*, *cloche* — et non d'après un
numéro de la façade du DX7 : prétendre reproduire la table exacte demanderait de
la vérifier, et elle ne l'a pas été.

Ne sont pas repris non plus la quantification à douze bits des tables de sinus,
l'échelle logarithmique des enveloppes, et le retard d'un échantillon de la
boucle de rétroaction. Ce dernier est remplacé par une itération de point fixe :
même spectre, à un déphasage près, et pas de boucle séquentielle sur un
demi-million de points.

## 4. L'enveloppe se lit de haut en bas

C'est la conséquence la plus jolie du pliage. Une trame dure vingt millisecondes
en 625 lignes, et l'axe du temps de l'enveloppe **est** la hauteur de l'image :
une attaque de deux millisecondes, c'est le dixième supérieur de la trame.

On peut donc écrire une forme verticale avec une enveloppe de synthétiseur —
une attaque qui s'éteint vers le bas, une montée, une bande unique au milieu.
C'est là qu'« entendre avec les yeux » cesse d'être une image.

Un détail qui a coûté un test : l'enveloppe *plate* rampait de zéro à un sur le
haut de l'image, parce qu'une enveloppe de DX7 part du silence. Les motifs
censés être immobiles ne l'étaient donc pas tout à fait. D'où un champ `depart`,
et une enveloppe plate qui vaut vraiment un partout.

## 5. Ce que cet outil ne touche pas

**Il ne touche pas au son.** La voie audio d'un téléviseur a sa propre porteuse,
plusieurs mégahertz plus haut ; ce qu'on injecte ici va dans le composite vidéo,
exactement là où un brouilleur agirait. Un test le vérifie en faisant passer le
même signal par la chaîne son avant et après un rendu à niveau maximal, et
exige le bit près — ce qui garantit du même coup qu'aucun état global ne fuit
d'un module à l'autre.

**Il ne dessine rien.** L'injection se fait sur le composite, entre le codeur et
le canal, par le champ `perturbation` de `tvcolor.pipeline.Parametres`. Tout ce
qui suit — canal, magnétoscope, séparation Y/C, démodulation, matriçage
inverse — est la chaîne ordinaire du simulateur. Une onde à niveau nul rend donc
l'image **au bit près**, ce qu'un test contrôle.

Le bouton « exporter la voix » écrit un WAV : c'est la même pile d'opérateurs,
les mêmes rapports et les mêmes enveloppes, rejoués à une fondamentale
transposée à 110 Hz pour être audibles. C'est littéralement le son qu'on est en
train de regarder.

> **Dans le code** — `arty/dx7.py` pour les opérateurs, `arty/injection.py` pour
> la base de temps et la prédiction du motif, `arty/app.py` pour la fenêtre.
> `tests/test_arty.py` compare chaque prédiction à la mesure.
