"""
La caméra : le tube analyseur, sa rémanence, et la queue de comète.

Tout le reste de ce projet commence à l'image R'G'B' du studio, comme si elle
sortait parfaite d'un capteur idéal. Dans les années soixante-dix elle sortait
d'un **tube analyseur**, et le tube laissait sa signature bien avant que le
codeur n'y touche.

Le principe du tube
-------------------

Une cible photoconductrice — de l'oxyde de plomb pour le Plumbicon de Philips,
qui équipait la quasi-totalité des cars de reportage européens — est portée à
quelques dizaines de volts par sa face avant transparente. L'objectif y projette
l'image. Là où la lumière tombe, le photoconducteur devient conducteur et la
face arrière se **décharge** localement, d'autant plus que l'éclairement est
fort et que le temps de pose est long.

Un faisceau d'électrons balaie ensuite cette face arrière et y redépose les
électrons manquants, ramenant chaque point au potentiel de la cathode. **Le
courant qu'il faut pour cela EST le signal vidéo.** Il n'y a pas de conversion
intermédiaire : on mesure directement la charge que l'image a soutirée.

Ce mécanisme a deux conséquences, et ce module ne simule rien d'autre.

**Un — le faisceau ne peut pas rendre plus d'électrons qu'il n'en transporte.**
Son courant est réglé, en atelier, pour évacuer le blanc de référence avec une
marge d'environ 30 %. Un reflet spéculaire — le chrome d'une cymbale, le vernis
d'une guitare, une pièce de micro sous un projecteur de deux kilowatts — ne
dépasse pas le blanc de 30 %, il le dépasse de **vingt à cinquante fois**. Le
faisceau en évacue alors une tranche constante par trame, et il lui faut autant
de trames que le rapport de dépassement. Pendant ce temps le reflet s'est
déplacé : la charge restée en arrière se lit trame après trame, au maximum que
le faisceau sait fournir, c'est-à-dire au blanc écrêté. C'est la **queue de
comète**, et c'est ce qu'on voyait dans toutes les émissions musicales en
direct.

Deux points de cette description sont vérifiables à l'œil sur un enregistrement
d'époque, et tombent tout seuls du calcul ci-dessous :

- la traînée est **d'un blanc plat**, saturé, et l'image qu'elle traverse
  disparaît derrière elle — le faisceau donnant déjà tout, ce qui s'ajoute à la
  cible ne se lit pas ;
- elle **s'arrête net**. Une décroissance exponentielle s'éteint doucement ;
  celle-ci est arithmétique — une tranche fixe par trame — et la traînée a donc
  un bout franc, à la distance que le mobile a parcourue en `L / c` trames.

**Deux — le faisceau ne décharge jamais complètement.** Les électrons arrivent
avec une petite dispersion d'énergie ; à mesure que le potentiel de la cible se
rapproche de celui de la cathode, il en reste de moins en moins qui puissent
atterrir. La décharge se termine donc en traînant, et il subsiste une fraction
`r` de la charge. C'est la **rémanence**, ou lag, et elle a une propriété
contre-intuitive qu'il faut absolument reproduire : **elle est bien pire dans
les bas niveaux**. Un petit écart de potentiel se résorbe lentement. Une
image sombre traîne, une image bien éclairée ne traîne pas.

C'est de là que vient la **lumière de biais** : une petite lampe éclairant la
cible en permanence, quelques pour cent du blanc, pour que le point de
fonctionnement ne descende jamais dans la région paresseuse. Elle ne sert à
rien d'autre, et le simulateur la traite pour ce qu'elle est — un éclairement
ajouté à la scène, dont l'étage de niveau du noir se débarrasse ensuite.

L'équation
----------

Avec les charges exprimées en « blancs de référence par trame » :

    q      = q_reste + L + b                (intégration pendant la trame)
    r(q)   = r_max · q_0 / (q + q_0)        (décharge incomplète, pire en bas)
    s      = min( q · (1 − r(q)), c )       (ce que le faisceau évacue)
    q_reste ← q − s                          (ce qu'il laisse)
    signal = s − b                          (l'étage de niveau du noir)

Trois lignes, et tout est dedans. Un contrôle utile : sur une scène **fixe**,
le régime établi donne `q_reste = q·r(q)`, donc `s = q − q_reste = L + b`, donc
`signal = L` **exactement**, quelle que soit la rémanence. Un tube ne dégrade
pas une image immobile ; il ne fait que retarder les changements. C'est ce que
vérifie `tests/test_tube.py::test_tube_transparent_sur_image_fixe`, et c'est le
même critère de qualité que pour le reste de la chaîne : ce qui n'est pas un
phénomène simulé doit passer sans laisser de trace.

La reconstruction des hautes lumières
-------------------------------------

Il reste un problème, et c'est le seul endroit de ce module où l'on suppose
quelque chose plutôt que de le calculer. Un fichier huit bits a été écrêté par
celui qui l'a fabriqué : **aucun pixel n'y dépasse le blanc**. Sans rien faire,
la cible n'est jamais surchargée et il n'y a pas la moindre queue de comète.

Il faut donc rendre aux reflets l'éclairement qu'ils avaient. Ce qui distingue
un reflet spéculaire d'un drap blanc n'est pas son niveau — les deux sont à
100 % dans le fichier — mais sa **taille** : une surface diffuse ne renvoie pas
plus de lumière qu'elle n'en reçoit, et l'exposition la place au blanc ; un
reflet est l'image de la source elle-même, minuscule et démesurément brillante.
On compare donc chaque point à la moyenne de son voisinage, et l'on n'amplifie
que ce qui **excède localement**. Un drap blanc a un voisinage blanc et ne
bouge pas ; un éclat de chrome a un voisinage sombre et part à vingt-cinq fois
le blanc.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

# ---------------------------------------------------------------------------
# Constantes du modèle
# ---------------------------------------------------------------------------

CHARGE_DEMI = 0.10
"""Charge, en blancs, à laquelle la rémanence vaut la moitié de son maximum.

C'est la valeur du Plumbicon, et la valeur par défaut de `genou_remanence` —
mais **ce n'est pas une constante universelle**, et l'avoir crue telle a
d'abord empêché de distinguer un tube d'un autre. Voir la docstring du champ.

Avec `remanence = 0,35` et ce genou, le résidu de troisième trame vaut 0,18 %
à pleine lumière et 1,84 % à 5 % du blanc — un Plumbicon était spécifié à
« moins de 3 % en troisième trame », et c'était son argument de vente."""

CHARGE_MAXIMALE = 6.0
"""Charge maximale que la cible peut retenir, en blancs de référence.

**La cible sature, et l'oublier ruine tout le chapitre.** Le faisceau maintient
la face arrière au potentiel de la cathode ; la lumière la fait remonter vers
celui de la face avant, et elle ne peut pas aller plus loin. Une fois le point
entièrement déchargé, l'éclairement supplémentaire ne dépose plus rien.

Sans ce plafond, la charge s'accumule sans borne. Mesuré sur la version qui en
manquait : un reflet à vingt-cinq fois le blanc resté quarante trames dans le
champ — moins d'une seconde — avait accumulé 989 unités, de quoi traîner **plus
de quinze secondes** derrière lui. Aucune caméra n'a jamais fait cela, et c'est
le genre de faute qui ne se voit pas sur une mesure faite en trames, seulement
à la montre.

D'où vient le chiffre, à un ordre de grandeur près et pas davantage :

| grandeur | valeur d'exploitation |
|---|---|
| potentiel de la face avant | 45 V |
| courant de signal au blanc | 300 nA |
| capacité de la cible | 1,3 nF |
| durée d'une trame | 20 ms |

Le blanc de référence dépose donc `300 nA × 20 ms = 6 nC` par trame, soit
`6 nC / 1,3 nF = 4,6 V` d'excursion ; et `45 / 4,6 = 9,8`, soit une dizaine de
blancs avant saturation. Les trois premières valeurs sont des points de
fonctionnement usuels et non des mesures : le produit vaut ce que valent ses
facteurs, et c'est dit plutôt que caché.

Conséquence à retenir : **au-delà de la saturation, un reflet plus brillant ne
fait pas une traînée plus longue.** La durée ne dépend plus que du rapport entre
cette capacité et le courant du faisceau."""

RAYON_DIFFUSION = 0.009
"""Rayon de la tache de diffusion de l'objectif, en fraction de la hauteur.

**C'est l'optique, et l'oublier donnait des taches blanches à bords francs.**
Un reflet ne se pose pas sur la cible en carré net : l'objectif le répand —
diffraction, aberrations, et surtout la lumière parasite des huit à quinze
lentilles d'un zoom de reportage. Ce qui arrive sur la cible est une bosse
lisse, pas un créneau.

Sans elle, l'éclairement reconstruit passait de 0,1 à 26 d'un pixel à l'autre :
tout le pâté saturait la cible, tout traînait exactement aussi longtemps, et la
tache blanche n'avait aucun dégradé. Mesuré sur un reflet de 6 × 6 pixels :

| | profil de l'éclairement | pixels saturés | pixels qui traînent |
|---|---|---|---|
| sans optique | 0,1 → 26 → 0,1 | 36 | 36, tous de même durée |
| avec | 0,3 · 2,4 · 8,7 · 10,3 · 6,4 · 1,5 · 0,3 | 4 | 156, de durées échelonnées |

Le dégradé spatial et l'étalement des durées viennent tous deux de là. Et
comme l'énergie est conservée, le sommet retombe de 26 à 10 : un reflet
marginal cesse de saturer, ce qui règle du même coup la question de la force de
l'effet."""

RAYON_VOILE = 0.06
PART_VOILE = 0.35
"""Le VOILE de l'objectif : sa jupe, large et basse, et la part de lumière
qu'elle emporte.

Une gaussienne n'a pas de jupe — elle retombe à rien en trois écarts-types — et
c'est ce qui laissait les flancs de la traînée aussi francs qu'avant. La lumière
parasite d'un objectif, elle, décroît en raison inverse du carré de la distance :
les huit à quinze lentilles d'un zoom de reportage renvoient un voile qui
s'étend sur toute l'image. C'est lui qui fait le halo autour d'une lampe dans un
plan, et lui qui donne à une queue de comète ses bords fondus.

On le modélise par une seconde gaussienne, six fois plus large, portant 35 % de
l'énergie. Deux gaussiennes ne font pas une loi en 1/r², mais elles en ont ce
qui compte ici : un cœur étroit et une jupe qui va loin."""

RAYON_REFLET = 0.03
"""Rayon du voisinage servant à décider qu'un point est un reflet, en fraction
de la hauteur d'image. Trois pour cent, soit une vingtaine de pixels sur 576
lignes : plus large qu'un éclat spéculaire, bien plus étroit qu'un vêtement."""

EXPOSANT_REFLET = 5.0
"""Raideur de la reconstruction.

À la puissance cinq, un point à mi-chemin du seuil ne reçoit qu'un trentième de
l'amplification : seuls les points **vraiment** écrêtés partent en surcharge.

C'était 3, et c'était trop mou. Mesuré sur une image exposée un tiers trop haut
— ce que fait n'importe quelle caméra devant un ciel — 4,90 % de l'image partait
en surcharge et traînait, soit d'énormes plages blanches. Avec l'exposant à 5 et
le seuil relevé, on tombe à 0,94 %, en gardant 83 % des vrais éclats
spéculaires."""

SEUIL_COUVERTURE = 0.75
"""Niveau à partir duquel un pixel COMPTE dans le voisinage, pour la porte.

Séparé de `seuil_reflets`, et c'est une correction et non un raffinement. Les
deux étaient le même réglage, si bien que relever le seuil des reflets — pour
n'amplifier que ce qui est vraiment écrêté — abaissait du même coup ce qui
compte comme voisinage clair, **ouvrait la porte partout**, et empirait les
choses au lieu de les arranger. Mesuré : à seuil 0,90 et les deux liés, l'image
en surcharge montait au lieu de descendre ; une fois séparés, elle tombe de
4,90 % à 1,29 %."""

COUVERTURE_BASSE, COUVERTURE_HAUTE = 0.08, 0.22
"""Fraction écrêtée du voisinage entre lesquelles l'amplification s'éteint.

Le critère de niveau ne suffit pas : le bord d'un drap blanc est écrêté lui
aussi, et sans ce second garde-fou il partirait en surcharge comme un éclat de
chrome. Ce qui les sépare est **la part du voisinage qui est écrêtée avec eux**.
Sur un rayon de 3 % de la hauteur d'image :

| ce qu'on regarde | couverture | amplification |
|---|---|---|
| éclat de chrome, 4 pixels | 0,033 | × 1,00 |
| reflet filiforme sur une corde | 0,092 | × 0,98 |
| coin d'un aplat blanc | 0,324 | × 0,00 |
| bord d'un aplat blanc | 0,569 | × 0,00 |
| centre d'un aplat blanc | 1,000 | × 0,00 |

C'est bien une mesure de forme, pas de niveau : les quatre cas ci-dessus sont
tous à 100 % dans le fichier."""

GAIN_ANTI_COMETE = 300.0
"""Capacité supplémentaire offerte par un circuit anti-comète, au maximum.

Philips a introduit l'ACT vers 1975 : pendant la suppression ligne, le faisceau
est défocalisé et son courant fortement augmenté, le temps d'évacuer l'excès de
charge sans que le surcroît de bruit et la perte de définition n'apparaissent
dans l'image utile. Une caméra ainsi équipée encaissait **quelques centaines de
fois** le blanc. C'est pour cela que les traînées ont disparu des émissions vers
la fin de la décennie, sans que personne n'ait changé de tube.

La loi est **quadratique**, et pas par coquetterie : linéaire, le curseur
passait de 1 à 391 en ligne droite et tout le bas de course était inutilisable.
Au carré, avec un faisceau de 1,30 :

| position | encaisse |
|---|---|
| 0,00 | 1 × le blanc |
| 0,25 | 26 × |
| 0,40 | 64 × |
| 0,55 | 119 × |
| 0,75 | 221 × |
| 1,00 | 391 × |"""


CONTAMINATION = np.array([
    [0.88, 0.10, 0.02],
    [0.08, 0.86, 0.06],
    [0.02, 0.10, 0.88],
])
"""Ce que les filtres dichroïques d'une caméra à tubes récoltent en trop.

**Pourquoi il y a forcément une erreur.** Les courbes d'analyse idéales d'une
caméra sont les fonctions colorimétriques des primaires de restitution — et
celles-ci ont des **lobes négatifs**. Aucun filtre ne peut soustraire de la
lumière : on ne sait fabriquer que des courbes tout-positives, qui les
approchent. Chaque voie récolte donc une part de ses voisines, et le résultat
est une image **désaturée**.

Les lignes somment à 1, ce qui n'est pas un détail : le blanc reste blanc.
L'erreur ne porte que sur la saturation et, marginalement, sur la teinte.

**D'où viennent ces six coefficients.** Pas d'une fiche technique, et il faut
le dire : ils sont choisis pour reproduire le comportement documenté — une
désaturation nette, plus marquée sur le vert et le cyan, le bleu étant le mieux
séparé parce que son filtre est le plus étroit. Leur effet, lui, est mesuré et
chiffré au §15.14 du cours ; c'est cet effet qui engage, pas les coefficients.
"""


def matrice_masquage(masquage: float) -> np.ndarray:
    """Matrice de masquage de la caméra, d'inefficace (0) à parfaite (1).

    Les caméras portaient une matrice 3 × 3 dans leur électronique, dite de
    masquage, chargée de rattraper l'erreur des filtres. Elle a des coefficients
    hors diagonale NÉGATIFS — c'est ainsi qu'on refabrique les lobes manquants,
    par soustraction électronique plutôt qu'optique.

    À 1, elle est l'inverse exacte de `CONTAMINATION` et la caméra est
    colorimétriquement juste. À 0, il n'y a pas de matrice du tout et l'image
    sort telle que les filtres l'ont vue. Entre les deux, on interpole : c'est
    l'histoire de vingt ans d'électronique de caméra, où la matrice est passée
    d'inexistante à réglable voie par voie.
    """
    t = float(np.clip(masquage, 0.0, 1.0))
    return (1.0 - t) * np.eye(3) + t * np.linalg.inv(CONTAMINATION)


def _appliquer_matrice(image: np.ndarray, matrice: np.ndarray) -> np.ndarray:
    """Applique une matrice 3 × 3 à une image (H, W, 3), en lumière linéaire."""
    return image @ np.asarray(matrice, dtype=np.float64).T

# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------

@dataclass
class ParametresTube:
    """Réglages de la caméra."""

    actif: bool = False

    faisceau: float = 1.3
    """Courant du faisceau, en blancs de référence évacuables par trame.

    C'est le réglage le plus lourd de conséquences, et c'était un arbitrage
    d'exploitation : monter le courant supprime les traînées, mais grossit le
    spot et ramollit l'image. Les réglages d'atelier tournaient autour de 130 %
    du blanc — de quoi encaisser un blanc un peu chaud, rien de plus."""

    anti_comete: float = 0.0
    """Efficacité du circuit anti-comète, de 0 (aucun, une caméra de 1970) à 1
    (ACT complet, à partir de 1976)."""

    remanence: float = 0.35
    """Fraction maximale de charge que le faisceau laisse derrière lui, atteinte
    dans les très bas niveaux. 0,35 pour un Plumbicon, 0,85 pour un vidicon."""

    voile: float = PART_VOILE
    voile_rayon: float = RAYON_VOILE
    """Part de l'énergie emportée par le voile de l'objectif, et son rayon."""

    diffusion: float = RAYON_DIFFUSION
    """Rayon de la tache de diffusion de l'objectif, en fraction de la hauteur.
    À zéro, les reflets reprennent leurs bords francs — instructif, et faux."""

    charge_maximale: float = CHARGE_MAXIMALE
    """Charge que la cible retient au plus, en blancs. Voir `CHARGE_MAXIMALE` :
    c'est elle, et non l'éclat du reflet, qui fixe la longueur des traînées."""

    genou_remanence: float = CHARGE_DEMI
    """Charge à laquelle la rémanence vaut la moitié de son maximum.

    Ce champ a d'abord été une constante du module, et c'était une faute : avec
    un genou figé à 0,10, le résidu de troisième trame plafonne à 0,7 % **à
    niveau nominal**, quelle que soit la rémanence. Autrement dit, tous les
    tubes se ressemblaient dans les hautes lumières, et l'on ne pouvait pas
    distinguer un vidicon d'un Plumbicon — ce qui est pourtant la différence la
    plus voyante de toute l'histoire des caméras.

    Le genou est bien une propriété du tube : il dit à quelle échelle de charge
    le faisceau commence à peiner, ce qui dépend de l'épaisseur et de la nature
    du photoconducteur. Le sortir en paramètre ouvre toute la gamme observée :

    | rémanence | genou | résidu 3ᵉ trame @100 % | @20 % | @5 % |
    |---|---|---|---|---|
    | 0,20 | 0,06 | 0,03 % | 0,13 % | 0,33 % |
    | 0,35 | 0,10 | 0,18 % | 0,73 % | 1,84 % |
    | 0,50 | 0,30 | 0,98 % | 3,42 % | 7,11 % |
    | 0,85 | 0,80 | 4,54 % | 14,26 % | 28,90 % |
    """

    lumiere_de_biais: float = 0.02
    """Éclairement permanent de la cible, en fraction du blanc. Ne sert qu'à
    remonter le point de fonctionnement hors de la zone paresseuse."""

    eclat_reflets: float = 2.5
    """Éclairement réel des reflets écrêtés, en multiples du blanc.

    **C'est la seule hypothèse du module, et c'est le curseur qui décide de la
    force de tout l'effet.** Le fichier ne contient plus l'information : un
    pixel à 255 pouvait valoir 1,05 fois le blanc ou cinquante fois, et rien ne
    permet de trancher.

    La valeur par défaut a été calée sur une capture d'émission de 1972 — un
    groupe sur scène, éclairage de concert, mouvement partout. Ce qu'on y voit
    est **léger** : aucune plage blanche, aucun pixel écrêté, et des traînées
    qui sont celles du sujet lui-même. À 25, un éclat de chrome de douze pixels
    fabriquait une tache blanche de quatre-vingt-dix ; à 2,5, il en fait
    vingt-six, entourées d'un halo dégradé.

    Monter ce curseur, c'est supposer un projecteur dans l'axe — ce qui arrivait,
    et donnait alors les comètes spectaculaires du §15.2. Mais ce n'était pas
    l'ordinaire."""

    seuil_reflets: float = 0.94
    """Niveau au-dessous duquel rien n'est amplifié, quel que soit le voisinage.

    C'était 0,75, et c'était la cause des grandes plages blanches : un pixel à
    trois quarts du blanc n'est pas un reflet spéculaire, c'est un mur éclairé.
    Relevé à 0,94, seul ce qui est à un cheveu de l'écrêtage est candidat.

    C'est le curseur de sensibilité de toute la reconstruction, et le baisser
    fait réapparaître les plages blanches — instructif, mais ce n'est pas ce que
    voyait un opérateur."""

    masquage: float = 1.0
    """Efficacité de la matrice de masquage de la caméra, de 0 à 1.

    À 1, la caméra est colorimétriquement juste et n'ajoute rien. À 0, elle n'a
    pas de matrice du tout et rend l'image telle que ses filtres l'ont vue —
    nettement désaturée. Voir `CONTAMINATION` et `matrice_masquage`."""

    pont_temporel: float = 0.0
    """Déplacement maximal, en pixels, que le pont temporel sait combler.

    Zéro le désactive, et c'est le bon réglage pour l'outil image fixe : celui-là
    fabrique le mouvement, donc il le connaît, et `_filer` étale l'éclairement
    exactement de ce qu'il faut. Le moteur temps réel, lui, reçoit une vidéo dont
    il ignore le mouvement — voir `_pont`."""

    desalignement: float = 0.0
    """Erreur de superposition des trois tubes, en pixels au coin de l'image.

    Trois tubes, trois faisceaux, trois déviations à régler l'une sur l'autre.
    Le réglage tenait quelques heures, puis dérivait avec la température ; d'où
    les liserés colorés sur les contours, nuls au centre et croissants vers les
    bords. Modélisé comme une erreur d'échelle, ce qu'elle était le plus
    souvent."""

    # -- pour l'outil image fixe -------------------------------------------

    mouvement: tuple[float, float] = (6.0, 0.0)
    """Déplacement de l'image sur la cible, en pixels par trame.

    Sans mouvement il n'y a pas de traînée : la queue de comète est la trace du
    passé d'un point qui a bougé. L'outil image fixe simule donc un travelling,
    et n'affiche que la dernière trame."""

    champs: int = 14
    """Nombre de trames intégrées avant l'affichage. Il en faut assez pour que
    la traînée ait sa longueur définitive — `eclat_reflets / faisceau` trames,
    soit 19 aux valeurs par défaut."""

    def capacite(self) -> float:
        """Charge réellement évacuable par trame, anti-comète compris."""
        return float(self.faisceau) * (
            1.0 + GAIN_ANTI_COMETE * float(self.anti_comete) ** 2
        )

    def trainee_en_trames(self) -> float:
        """Durée de la traînée d'un reflet à `eclat_reflets`, en trames.

        Le minimum est ce qui compte : au-delà de la saturation de la cible, un
        reflet plus brillant ne fait pas une traînée plus longue. Il ne peut
        pas déposer davantage que ce que la cible retient.
        """
        stockee = min(1.0 + self.eclat_reflets, self.charge_maximale)
        return max(0.0, stockee / self.capacite() - 1.0)

    def trainee_en_pixels(self) -> float:
        """Longueur de cette traînée, en pixels."""
        vitesse = float(np.hypot(*self.mouvement))
        return self.trainee_en_trames() * vitesse


# ---------------------------------------------------------------------------
# Les caméras
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModeleCamera:
    """Un matériel d'époque, et les réglages qui le reproduisent.

    **Ces valeurs ne sont pas recopiées de fiches techniques.** Ce qui est
    documenté, c'est le *comportement* de chaque génération : quel
    photoconducteur, quelle classe de rémanence, la présence ou l'absence d'un
    circuit anti-comète, la pratique d'alignement de l'époque. Les paramètres
    sont choisis pour que le simulateur reproduise ce comportement, et chaque
    entrée porte sa rémanence **mesurée** — que
    `tests/test_tube.py::test_chaque_camera_a_la_remanence_annoncee` recalcule,
    de sorte qu'une valeur retouchée sans mesure fait rougir la suite.

    Ce qui sert d'ancrage documentaire : le Plumbicon de Philips (1963) était
    spécifié à moins de 3 % de résidu en troisième trame, et ce fut son argument
    de vente face au vidicon au sulfure d'antimoine, qui dépassait 20 % et
    rendait tout mouvement illisible ; Philips a livré le circuit anti-comète
    vers 1975-76 ; le Saticon de Hitachi et de la NHK (1973) gagnait en
    définition ce qu'il perdait un peu en rémanence, et son canon diode du début
    des années 80 a réglé la question ; l'alignement automatique des trois tubes
    est apparu vers 1980.

    Aucun nom de produit dans les libellés, et c'est délibéré : attribuer des
    paramètres inventés à un LDK-25 ou à un HL-79 nommément serait exactement le
    genre d'affirmation que ce projet s'interdit. Le type de tube et l'époque
    suffisent à situer le matériel.
    """

    code: str
    nom: str
    annee: int
    tube: str

    caractere: str
    """Ce qui distingue cette caméra, en une phrase — affiché sous le menu."""

    faisceau: float
    anti_comete: float
    remanence: float
    genou_remanence: float
    lumiere_de_biais: float
    desalignement: float

    masquage: float = 1.0
    """Efficacité de la matrice de masquage, de 0 (aucune) à 1 (exacte).

    C'est le seul champ de cette table qui ne décrive pas la cible mais
    l'électronique, et c'est celui qui a le plus progressé : une caméra de 1966
    n'avait pas de matrice du tout et rendait une image franchement désaturée ;
    en 1984, elle était réglable voie par voie et la colorimétrie était juste."""

    charge_maximale: float = CHARGE_MAXIMALE
    """Capacité de la cible, identique pour tous les modèles — et c'est dit
    plutôt qu'inventé. Elle dépend de l'épaisseur du photoconducteur et de la
    tension de la face avant, et rien de ce qu'on peut documenter ne permet de
    différencier les sept entrées sur ce point. Sept valeurs distinctes auraient
    fait passer pour une mesure ce qui n'aurait été qu'une décoration."""

    lag_troisieme_trame: float = 0.0
    """Résidu de troisième trame après extinction, en pour-cent, mesuré à 5 % du
    blanc et **sans lumière de biais** : c'est une propriété du tube, et non du
    réglage d'exploitation."""

    def appliquer(self, base: ParametresTube | None = None) -> ParametresTube:
        """Pose les caractéristiques du matériel, sans toucher à la scène.

        `eclat_reflets`, `seuil_reflets`, `mouvement` et `champs` décrivent ce
        que la caméra REGARDE, et non ce qu'elle est. Choisir un modèle ne doit
        donc rien en dire : deux caméras différentes filmant le même plateau y
        voient les mêmes reflets.
        """
        import copy

        sortie = copy.copy(base) if base is not None else ParametresTube()
        sortie.faisceau = self.faisceau
        sortie.anti_comete = self.anti_comete
        sortie.remanence = self.remanence
        sortie.genou_remanence = self.genou_remanence
        sortie.charge_maximale = self.charge_maximale
        sortie.masquage = self.masquage
        sortie.lumiere_de_biais = self.lumiere_de_biais
        sortie.desalignement = self.desalignement
        return sortie

    def parametres(self) -> ParametresTube:
        """Les mêmes réglages seuls, pour interroger `capacite` ou `trainee`."""
        return self.appliquer()

    def encaisse(self) -> float:
        """Éclairement maximal, en blancs, absorbé sans laisser de traînée."""
        return self.parametres().capacite()


CAMERAS: dict[str, ModeleCamera] = {
    m.code: m
    for m in (
        ModeleCamera(
            code="vidicon", nom="Vidicon 3 tubes", annee=1966, tube="vidicon",
            caractere=(
                "Le tube d'avant le Plumbicon. Sa rémanence est telle qu'un "
                "mouvement rapide devient illisible : c'est ce qui l'a cantonné "
                "à la surveillance et aux usages industriels."
            ),
            faisceau=1.15, anti_comete=0.00, remanence=0.85, genou_remanence=0.80,
            lumiere_de_biais=0.00, desalignement=3.0, masquage=0.00, lag_troisieme_trame=28.90,
        ),
        ModeleCamera(
            code="plumbicon-reportage", nom="Plumbicon, car de reportage",
            annee=1970, tube="Plumbicon",
            caractere=(
                "La caméra des émissions musicales en direct. Rémanence enfin "
                "négligeable, mais aucun circuit anti-comète : c'est elle qui "
                "laissait les grandes traînées blanches sur les cymbales."
            ),
            faisceau=1.30, anti_comete=0.00, remanence=0.35, genou_remanence=0.10,
            lumiere_de_biais=0.02, desalignement=2.0, masquage=0.35, lag_troisieme_trame=1.84,
        ),
        ModeleCamera(
            code="plumbicon-studio", nom="Plumbicon de studio, bien réglé",
            annee=1973, tube="Plumbicon",
            caractere=(
                "Le même tube, mais un faisceau plus généreux, une lumière de "
                "biais plus franche et un alignement refait le matin même. Les "
                "comètes sont plus courtes, les contours plus propres."
            ),
            faisceau=1.45, anti_comete=0.00, remanence=0.30, genou_remanence=0.09,
            lumiere_de_biais=0.04, desalignement=0.8, masquage=0.55, lag_troisieme_trame=1.19,
        ),
        ModeleCamera(
            code="plumbicon-act", nom="Plumbicon à anti-comète", annee=1977,
            tube="Plumbicon + ACT",
            caractere=(
                "L'ACT de Philips. Pendant la suppression ligne, le faisceau "
                "est défocalisé et son courant décuplé, le temps de vider "
                "l'excès de charge. Les traînées disparaissent sans qu'on ait "
                "changé de tube — voilà pourquoi on ne les voit plus après 1978."
            ),
            faisceau=1.40, anti_comete=0.55, remanence=0.30, genou_remanence=0.09,
            lumiere_de_biais=0.03, desalignement=1.0, masquage=0.70, lag_troisieme_trame=1.19,
        ),
        ModeleCamera(
            code="saticon-eng", nom="Saticon d'ENG", annee=1981, tube="Saticon",
            caractere=(
                "La caméra d'épaule du journal télévisé. Plus de définition que "
                "le Plumbicon, un peu plus de rémanence — ce qui se voyait dans "
                "les reportages tournés en intérieur sombre."
            ),
            faisceau=1.35, anti_comete=0.45, remanence=0.50, genou_remanence=0.16,
            lumiere_de_biais=0.05, desalignement=1.5, masquage=0.80, lag_troisieme_trame=5.34,
        ),
        ModeleCamera(
            code="saticon-diode", nom="Saticon à canon diode", annee=1984,
            tube="Saticon à canon diode",
            caractere=(
                "Le canon diode efface la rémanence, et l'alignement "
                "automatique les liserés colorés. À ce stade il ne reste plus "
                "grand-chose à reprocher au tube."
            ),
            faisceau=1.60, anti_comete=0.75, remanence=0.20, genou_remanence=0.06,
            lumiere_de_biais=0.02, desalignement=0.4, masquage=0.95, lag_troisieme_trame=0.33,
        ),
        ModeleCamera(
            code="ccd", nom="CCD", annee=1987, tube="CCD",
            caractere=(
                "Plus de tube du tout : ni rémanence, ni queue de comète, ni "
                "désalignement. ATTENTION — le défaut propre au CCD, la colonne "
                "verticale de lumière qui traverse l'image sur les très hautes "
                "lumières, n'est PAS simulé. Cette entrée montre ce qui a tué le "
                "phénomène ; elle ne simule pas un capteur à transfert de charge."
            ),
            faisceau=4.00, anti_comete=1.00, remanence=0.00, genou_remanence=0.10,
            lumiere_de_biais=0.00, desalignement=0.0, masquage=1.00, lag_troisieme_trame=0.00,
        ),
    )
}

CAMERA_PAR_DEFAUT = "plumbicon-reportage"
"""Celle des émissions musicales des années soixante-dix, et donc celle par
laquelle commencer si l'on cherche à retrouver ce qu'on a vu."""


def obtenir_camera(code: str) -> ModeleCamera:
    """Retourne le modèle de caméra correspondant au code."""
    try:
        return CAMERAS[code]
    except KeyError:
        connus = ", ".join(CAMERAS)
        raise KeyError(f"caméra inconnue : {code!r}. Modèles connus : {connus}") from None


# ---------------------------------------------------------------------------
# Le modèle, terme à terme
# ---------------------------------------------------------------------------

def fraction_residuelle(
    charge: np.ndarray, remanence: float, genou: float = CHARGE_DEMI
) -> np.ndarray:
    """Part de la charge que le faisceau laisse en place : `r_max·q₀/(q+q₀)`.

    Croissante quand la charge diminue, et c'est tout le point : la rémanence
    d'un tube est un défaut des bas niveaux. À pleine lumière elle est
    négligeable, à 5 % du blanc elle est de 23 %.
    """
    charge = np.asarray(charge, dtype=np.float64)
    genou = max(float(genou), 1e-6)
    return remanence * genou / (charge + genou)


def eclairement_scene(lineaire: np.ndarray, params: ParametresTube) -> np.ndarray:
    """Rend aux reflets écrêtés l'éclairement que le fichier ne contient plus.

    L'amplification ne porte pas sur le niveau mais sur l'**excès local** : un
    point n'est reconnu comme reflet que s'il domine son voisinage. Voir
    l'entête du module.
    """
    lineaire = np.asarray(lineaire, dtype=np.float64)
    if params.eclat_reflets <= 0.0:
        return lineaire

    marge = np.maximum(1.0 - params.seuil_reflets, 1e-6)
    exces = np.clip((lineaire - params.seuil_reflets) / marge, 0.0, 1.0)
    exces = exces**EXPOSANT_REFLET

    luminance = 0.299 * lineaire[..., 0] + 0.587 * lineaire[..., 1] + 0.114 * lineaire[..., 2]
    masque = np.clip(
        (luminance - SEUIL_COUVERTURE) / max(1.0 - SEUIL_COUVERTURE, 1e-6), 0.0, 1.0
    )

    sigma = max(1.0, RAYON_REFLET * lineaire.shape[0])
    couverture = ndimage.gaussian_filter(masque, sigma, mode="nearest")
    porte = _fondu(couverture, COUVERTURE_HAUTE, COUVERTURE_BASSE)[..., None]

    # L'ORDRE COMPTE, et l'inverse a coûté une transparence. La porte dit si un
    # point EST un reflet spéculaire ; l'optique étale ensuite ce que ce reflet
    # émet. Étaler d'abord et fermer la porte ensuite laissait l'excès d'une
    # barre blanche — que la porte rejetait pourtant en son centre — déborder
    # sur la barre voisine, où la porte était ouverte : ΔE\*ab de 2,51 à 3,84
    # sur une mire immobile, alors que rien n'avait bougé.
    emis = porte * exces

    # La tache de diffusion de l'objectif : un cœur étroit, et un voile large.
    # L'énergie est conservée — c'est un étalement, pas une amplification — et
    # c'est pour cela que le sommet retombe.
    sigma_coeur = params.diffusion * lineaire.shape[0]
    if sigma_coeur > 0.3:
        coeur = ndimage.gaussian_filter(
            emis, (sigma_coeur, sigma_coeur, 0), mode="nearest"
        )
        sigma_voile = params.voile_rayon * lineaire.shape[0]
        voile = ndimage.gaussian_filter(
            emis, (sigma_voile, sigma_voile, 0), mode="nearest"
        )
        emis = (1.0 - params.voile) * coeur + params.voile * voile

    return lineaire + params.eclat_reflets * emis


def _fondu(x: np.ndarray, un: float, zero: float) -> np.ndarray:
    """`smoothstep` de GLSL, dans le sens décroissant : 1 en `zero`, 0 en `un`."""
    t = np.clip((un - x) / (un - zero), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _desaligner(lineaire: np.ndarray, pixels: float) -> np.ndarray:
    """Décale radialement le rouge et le bleu : l'erreur de superposition.

    Une erreur d'échelle, donc nulle au centre et maximale aux coins — la forme
    qu'elle prenait presque toujours, la déviation des trois tubes n'étant
    jamais rigoureusement identique.
    """
    if abs(pixels) < 1e-9:
        return lineaire

    hauteur, largeur = lineaire.shape[:2]
    demi_diagonale = 0.5 * float(np.hypot(hauteur, largeur))
    ecart = pixels / demi_diagonale

    y, x = np.meshgrid(
        np.arange(hauteur, dtype=np.float64) - 0.5 * (hauteur - 1),
        np.arange(largeur, dtype=np.float64) - 0.5 * (largeur - 1),
        indexing="ij",
    )

    sortie = lineaire.copy()
    for canal, signe in ((0, +1.0), (2, -1.0)):
        facteur = 1.0 + signe * ecart
        coords = np.stack(
            [y / facteur + 0.5 * (hauteur - 1), x / facteur + 0.5 * (largeur - 1)]
        )
        sortie[..., canal] = ndimage.map_coordinates(
            lineaire[..., canal], coords, order=1, mode="nearest"
        )
    return sortie


DIRECTIONS_PONT = ((0, 1), (1, 0), (1, 1), (1, -1))
"""Les quatre axes du pont temporel, parcourus dans les deux sens — soit huit
directions. Une traînée peut aller n'importe où ; quatre axes suffisent parce
que le pont retient le meilleur, et qu'une direction à 22° de la bonne perd peu."""

ECHANTILLONS_PONT = 8
"""Points de sondage le long de chaque direction."""

# Le pont ne consulte QUE l'éclairement — celui-ci et celui de l'image
# précédente — et jamais la charge. C'est structurel, et c'est ce qui l'empêche
# de s'emballer : un point comblé n'entre dans aucune des deux textures qu'il
# consulte, et ne peut donc pas devenir la source d'un comblement voisin.
#
# La première version lisait la charge, et se nourrissait de sa propre sortie.
# Mesuré sur une scène chaude en mouvement : 23 % de l'écran en blanc saturé à
# la première image, 85 % à la dixième — la tache mangeait l'image. Amortir le
# comblement n'y suffisait pas : à gain 0,55 elle atteignait encore 61 %. Il
# fallait couper la boucle, pas la freiner.


def _pont(
    eclairement: np.ndarray, precedent: np.ndarray, params: ParametresTube
) -> np.ndarray:
    """Comble ce que l'échantillonnage temporel de la source a laissé vide.

    **Le problème.** La cible intègre en continu pendant toute la trame ; un
    reflet qui la traverse y balaie un segment. Une vidéo, elle, n'a que
    vingt-cinq images par seconde : le reflet y saute d'une position à l'autre,
    et ce qui s'est passé entre les deux **n'est pas dans le fichier**. La
    charge se dépose donc par paquets espacés, et la traînée sort en chapelet
    au lieu d'être continue. Mesuré sur un reflet de 4 pixels avançant de 24 par
    image : 21 % de la traînée allumée, le reste étant du trou.

    L'outil image fixe n'a pas ce problème — il fabrique le mouvement, donc il
    le connaît, et `_filer` étale l'éclairement de la bonne longueur. Ici on ne
    le connaît pas.

    **Le principe.** On ne cherche pas le mouvement, on constate son résultat.
    Un point qui se trouve **entre un reflet présent et une trace passée** a été
    traversé, et l'on remplit le segment :

        pont(x) = max sur les directions d de
                  min( max sur +d de « reflet neuf », max sur −d de « trace abandonnée » )

    Les deux qualificatifs sont ce qui fait tout marcher, et la première version
    s'en passait — pour ce résultat : **deux reflets immobiles distants de 24
    pixels se retrouvaient reliés par un trait**, purement inventé. On exige donc

    - « neuf » : un reflet ICI qui n'était pas là à l'image d'avant ;
    - « abandonné » : un reflet qui était LÀ et qui n'y est plus.

    Un reflet immobile est dans les deux images au même endroit : les deux
    termes s'annulent, et rien n'est relié. Un reflet qui a bougé a l'un d'un
    côté et l'autre de l'autre : le segment se remplit. Vérifié dans les deux
    sens par `tests/test_tube.py`.

    **Ce que c'est, et ce que ce n'est pas.** C'est une interpolation, pas un
    phénomène. Elle reconstruit une information que la source ne contient plus,
    et elle échoue au-delà de `pont_temporel` pixels de déplacement — la
    traînée y redevient un chapelet, faute de quoi que ce soit à interpoler.
    """
    pose = float(params.pont_temporel)
    if pose <= 0.0:
        return eclairement

    q_max = max(params.charge_maximale, 1e-6)

    # On ne compte que ce qui DÉPASSE le blanc, des deux côtés. Sans ce seuil,
    # le pont fuyait sur n'importe quelle image : un pixel sombre voyait un
    # voisin clair d'un côté, un autre voisin clair de l'autre, et se trouvait
    # relevé. Une queue de comète est par définition un dépôt en surcharge ;
    # rien d'autre n'a le droit de déclencher le pont.
    #
    # « neuf » : un reflet ICI qui n'était pas là à l'image d'avant.
    # « abandonné » : un reflet qui était LÀ et qui n'y est plus.
    neuf = np.maximum(eclairement - 1.0, 0.0) * np.clip(
        1.0 - precedent / q_max, 0.0, 1.0
    )
    abandonnee = np.maximum(precedent - 1.0, 0.0) * np.clip(
        1.0 - eclairement / q_max, 0.0, 1.0
    )

    meilleur = np.zeros_like(eclairement)
    for dy, dx in DIRECTIONS_PONT:
        for signe in (+1, -1):
            devant = np.zeros_like(eclairement)
            derriere = np.zeros_like(eclairement)
            for k in range(1, ECHANTILLONS_PONT + 1):
                r = int(round(pose * k / ECHANTILLONS_PONT))
                if r == 0:
                    continue
                devant = np.maximum(
                    devant, np.roll(neuf, (-signe * dy * r, -signe * dx * r), (0, 1))
                )
                derriere = np.maximum(
                    derriere, np.roll(abandonnee, (signe * dy * r, signe * dx * r), (0, 1))
                )
            meilleur = np.maximum(meilleur, np.minimum(devant, derriere))

    # Le « + 1 » rend le piédestal que le seuil avait retiré : un point comblé
    # doit recevoir de quoi saturer la cible, comme le reflet qui l'a traversé.
    return np.where(meilleur > 0.0, np.maximum(eclairement, meilleur + 1.0), eclairement)

# ---------------------------------------------------------------------------
# La chaîne, en flux
# ---------------------------------------------------------------------------

class ChaineTube:
    """Un tube analyseur, avec la charge qui reste sur sa cible.

    À utiliser image par image : c'est un objet à état, comme `ChaineSon`. La
    charge résiduelle est toute la mémoire du système, et c'est elle qui fait
    la traînée.
    """

    def __init__(self, params: ParametresTube | None = None):
        self.params = params or ParametresTube()
        self._charge: np.ndarray | None = None
        self._eclairement_precedent: np.ndarray | None = None

    def reinitialiser(self) -> None:
        """Cible vide — l'état d'une caméra qu'on vient d'allumer."""
        self._charge = None
        self._eclairement_precedent = None

    @property
    def charge(self) -> np.ndarray | None:
        return self._charge

    def amorcer(self, lineaire: np.ndarray, champs: int = 16) -> None:
        """Amène la cible au régime établi de l'image donnée.

        Sans cela la première image sortirait trop sombre : la cible part vide,
        et la première décharge est incomplète. Une vraie caméra a toujours
        quelques trames de retard sur l'allumage ; le simulateur ne peut pas se
        le permettre quand l'image ne bouge pas.
        """
        self.reinitialiser()
        for _ in range(champs):
            self.traiter(lineaire)

    def eclairement(self, lineaire: np.ndarray) -> np.ndarray:
        """Ce que l'objectif dépose vraiment sur la cible.

        Séparé de `integrer` parce que le filé de pose s'applique ICI et pas
        avant : un reflet est petit et brillant AVANT que le mouvement ne
        l'étale, et le reconstruire après l'étalement ne le reconnaîtrait plus.
        """
        p = self.params
        scene = _desaligner(np.asarray(lineaire, dtype=np.float64), p.desalignement)
        # La contamination des filtres agit AVANT la cible : c'est le prisme
        # séparateur qui la produit, pas l'électronique.
        scene = np.clip(_appliquer_matrice(scene, CONTAMINATION), 0.0, None)
        return eclairement_scene(scene, p)

    def integrer(self, eclairement: np.ndarray) -> np.ndarray:
        """Le tube proprement dit : une trame de pose, et ce que le faisceau lit.

        `eclairement` est en blancs de référence, et peut largement dépasser 1 —
        c'est même toute l'affaire.
        """
        p = self.params
        eclairement = np.asarray(eclairement, dtype=np.float64) + p.lumiere_de_biais

        if self._charge is None or self._charge.shape != eclairement.shape:
            self._charge = np.zeros_like(eclairement)

        # La cible sature : la face arrière ne peut pas remonter au-delà du
        # potentiel de la face avant, et l'éclairement excédentaire ne dépose
        # plus rien. Sans cette borne, un projecteur resté dans le champ
        # accumule sans fin et traîne pendant des secondes.
        charge = np.minimum(self._charge + eclairement, p.charge_maximale)
        residu = fraction_residuelle(charge, p.remanence, p.genou_remanence)
        lecture = np.minimum(charge * (1.0 - residu), p.capacite())

        self._charge = charge - lecture

        # L'écrêteur de blanc de la caméra. Le faisceau peut évacuer 130 % du
        # blanc ; l'amplificateur vidéo, lui, n'a jamais laissé passer cela sur
        # la ligne. La capacité du faisceau décide de ce que le tube ENCAISSE,
        # pas de ce qu'il émet — et c'est pourquoi une traînée est plate.
        signal = np.clip(lecture - p.lumiere_de_biais, 0.0, 1.0)

        # La matrice de masquage, elle, est APRÈS la cible : c'est de
        # l'électronique. L'ordre compte — entre les deux il y a l'écrêteur de
        # blanc, et la correction ne peut donc pas rattraper ce qu'il a coupé.
        if p.masquage < 1.0 or not np.allclose(CONTAMINATION, np.eye(3)):
            signal = np.clip(
                _appliquer_matrice(signal, matrice_masquage(p.masquage)), 0.0, 1.0
            )
        return signal

    def ponter(self, eclairement: np.ndarray) -> np.ndarray:
        """Applique le pont temporel, en comparant à l'éclairement précédent."""
        precedent = self._eclairement_precedent
        self._eclairement_precedent = eclairement
        if precedent is None or precedent.shape != eclairement.shape:
            return eclairement
        return _pont(eclairement, precedent, self.params)

    def traiter(self, lineaire: np.ndarray) -> np.ndarray:
        """Fait poser une trame à la caméra, et rend le signal lu.

        `lineaire` est la scène en lumière linéaire, (H, W, 3), le blanc de
        référence valant 1. Le résultat est dans les mêmes unités.
        """
        return self.integrer(self.ponter(self.eclairement(lineaire)))


# ---------------------------------------------------------------------------
# Commodité pour une image fixe
# ---------------------------------------------------------------------------

def _filer(eclairement: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Étale l'éclairement du déplacement d'une trame : la pose n'est pas un instant.

    Sans cela, une image qui avance de cinq pixels par trame déposerait sa
    charge cinq pixels plus loin sans rien laisser entre les deux, et la
    traînée sortirait **pointillée**. La cible, elle, intègre pendant toute la
    durée de la trame, et le reflet y balaie un segment continu.

    Une moyenne glissante est exactement cette intégrale, et elle est séparable
    tant que le mouvement est horizontal ou vertical — le seul cas que
    l'interface propose. En diagonale on obtient un rectangle au lieu d'un
    segment, ce qui étale un peu trop : c'est dit ici plutôt que caché.
    """
    sortie = eclairement
    largeur_x, largeur_y = int(round(abs(dx))), int(round(abs(dy)))
    if largeur_x > 1:
        sortie = ndimage.uniform_filter1d(sortie, largeur_x, axis=1, mode="nearest")
    if largeur_y > 1:
        sortie = ndimage.uniform_filter1d(sortie, largeur_y, axis=0, mode="nearest")
    return sortie


def filmer(lineaire: np.ndarray, params: ParametresTube) -> np.ndarray:
    """Filme un travelling sur une image fixe, et rend la dernière trame.

    Une image fixe ne peut pas montrer de queue de comète : il n'y a pas de
    passé. On simule donc le seul mouvement dont on dispose — celui de la
    caméra — en translatant la scène de `mouvement` pixels par trame, et l'on
    n'affiche que la dernière. La traînée qui apparaît alors est le résultat
    d'un calcul sur `champs` trames, pas un flou directionnel.
    """
    lineaire = np.asarray(lineaire, dtype=np.float64)
    chaine = ChaineTube(params)

    dy, dx = float(params.mouvement[1]), float(params.mouvement[0])
    champs = max(1, int(params.champs))

    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        chaine.amorcer(lineaire, champs)
        return chaine.traiter(lineaire)

    # L'éclairement ne dépend pas de la trame : on le calcule une fois, on
    # l'étale du filé de pose, et l'on ne fait plus que le déplacer.
    eclairement = _filer(chaine.eclairement(lineaire), dx, dy)

    signal = lineaire
    for n in range(champs):
        # Le décalage est cumulé depuis le début, et repris de l'original à
        # chaque trame : translater le résultat précédent reviendrait à filtrer
        # l'image autant de fois qu'il y a de trames.
        avance = n - (champs - 1)
        decale = ndimage.shift(
            eclairement, (avance * dy, avance * dx, 0.0), order=1, mode="nearest"
        )
        signal = chaine.integrer(decale)
    return signal


def appliquer(lineaire: np.ndarray, params: ParametresTube | None = None) -> np.ndarray:
    """Point d'entrée de `pipeline` : ne fait rien si la caméra est désactivée."""
    params = params or ParametresTube()
    if not params.actif:
        return lineaire
    return filmer(lineaire, params)
