"""
Mires de test — les images qui font parler les défauts.

Une photographie ordinaire cache les artefacts autant qu'elle les montre.
Les mires, elles, sont conçues pour qu'un défaut précis devienne impossible à
manquer : le piège à cross-color contient des fréquences spatiales choisies
pour tomber exactement sur la sous-porteuse, la mire de points rampants
n'offre que des contours horizontaux, la roue de teintes rend une rotation de
5° parfaitement lisible.

Toutes les fonctions renvoient une image sRGB de forme (h, w, 3) dans [0, 1].
"""

from __future__ import annotations

import numpy as np

from .constantes import Norme, obtenir_norme

# Les six couleurs saturées, dans l'ordre de luminance décroissante — c'est
# cet ordre qui donne aux barres de couleur leur allure d'escalier sur un
# oscilloscope, et qui permet de les régler à l'œil sur un récepteur N&B.
ORDRE_BARRES = [
    (1, 1, 1),   # blanc
    (1, 1, 0),   # jaune
    (0, 1, 1),   # cyan
    (0, 1, 0),   # vert
    (1, 0, 1),   # magenta
    (1, 0, 0),   # rouge
    (0, 0, 1),   # bleu
    (0, 0, 0),   # noir
]

NOMS_BARRES = ["blanc", "jaune", "cyan", "vert", "magenta", "rouge", "bleu", "noir"]


def _colonnes(couleurs, h: int, w: int) -> np.ndarray:
    n = len(couleurs)
    bornes = np.round(np.linspace(0, w, n + 1)).astype(int)
    image = np.zeros((h, w, 3))
    for k, couleur in enumerate(couleurs):
        image[:, bornes[k] : bornes[k + 1]] = couleur
    return image


# ---------------------------------------------------------------------------
# Barres de couleur
# ---------------------------------------------------------------------------

def barres_couleur(h: int = 576, w: int = 768, niveau: float = 0.75) -> np.ndarray:
    """Barres de couleur normalisées, à 75 % par défaut.

    Pourquoi 75 % et non 100 % ? Parce qu'à 100 % le jaune et le cyan portent
    le signal composite à 133 IRE (cf. `matrices.deriver_facteurs_echelle`),
    au-delà de ce qu'un émetteur peut transmettre sans distorsion. Les barres
    à 75 % restent dans l'excursion légale — c'est la mire de référence de
    toute l'exploitation broadcast.
    """
    couleurs = [tuple(niveau * c for c in rgb) for rgb in ORDRE_BARRES]
    couleurs[0] = (1.0, 1.0, 1.0)   # la barre de blanc reste à 100 %
    return _colonnes(couleurs, h, w)


def barres_smpte(h: int = 576, w: int = 768) -> np.ndarray:
    """Mire SMPTE ECR 1-1978 : barres, bandes inversées, et PLUGE.

    Les trois bandes horizontales servent chacune à un réglage :

    * en haut, les barres à 75 % pour la saturation et la teinte ;
    * au milieu, les mêmes couleurs en ordre inversé, pour vérifier la
      pureté du bleu au décodage (astuce du « blue only ») ;
    * en bas, le PLUGE — trois rectangles à -4, 0 et +4 IRE autour du niveau
      de noir. Sur un écran correctement réglé, seul celui de droite est
      visible. C'est la mire qui permet de régler la luminosité à l'œil nu.
    """
    image = np.zeros((h, w, 3))
    h1, h2 = int(h * 0.67), int(h * 0.75)

    image[:h1] = barres_couleur(h1, w, 0.75)[:h1]

    inverse = [(0, 0, 0.75), (0, 0, 0), (0.75, 0, 0.75), (0, 0, 0),
               (0, 0.75, 0.75), (0, 0, 0), (0.75, 0.75, 0.75)]
    image[h1:h2] = _colonnes(inverse, h2 - h1, w)

    bas = np.zeros((h - h2, w, 3))
    largeur = w // 7
    bas[:, : 5 * largeur // 2] = (0.0, 0.13, 0.24)     # -I
    bas[:, 5 * largeur // 2 : 5 * largeur] = 1.0        # blanc 100 %
    bas[:, 5 * largeur : 15 * largeur // 2] = (0.19, 0.0, 0.24)   # +Q
    # PLUGE : noir légèrement sous, égal, légèrement au-dessus du niveau de noir.
    debut = 15 * largeur // 2
    tiers = (w - debut) // 3
    bas[:, debut : debut + tiers] = 0.0
    bas[:, debut + tiers : debut + 2 * tiers] = 0.035
    bas[:, debut + 2 * tiers :] = 0.070
    image[h2:] = bas
    return image


# ---------------------------------------------------------------------------
# Mires de résolution et pièges à artefacts
# ---------------------------------------------------------------------------

def balayage_frequentiel(
    h: int = 576, w: int = 768, norme: str | Norme = "PAL-BG",
    f_max: float = 6.0e6, marquer_sous_porteuse: bool = True,
) -> np.ndarray:
    """Balayage de fréquence horizontal — le piège à cross-color.

    L'image est un signal de luminance dont la fréquence croît linéairement de
    0 à `f_max` de gauche à droite. Un vrai balayage vidéo, calé sur la durée
    de ligne active de la norme : la position horizontale correspond donc
    exactement à une fréquence en mégahertz.

    Là où la fréquence spatiale de l'image croise la sous-porteuse, le
    décodeur ne peut plus faire la différence entre un détail fin de
    luminance et une couleur. Il choisit la couleur. C'est le **cross-color**
    — les moirages irisés sur les vestes à fines rayures, la hantise des
    présentateurs de journal télévisé.

    Un repère vertical est tracé à la position de la sous-porteuse.
    """
    n = norme if isinstance(norme, Norme) else obtenir_norme(norme)
    t = np.linspace(0.0, n.duree_ligne_active, w)
    # Fréquence instantanée linéaire → phase quadratique.
    phase = 2.0 * np.pi * (0.5 * f_max / n.duree_ligne_active) * t**2
    ligne = 0.5 + 0.4 * np.sin(phase)

    image = np.repeat(ligne[None, :, None], h, axis=0).repeat(3, axis=2)

    if marquer_sous_porteuse:
        for f, couleur in ((n.f_sc, 1.0), (n.bande_y, 0.0)):
            x = int(round(w * f / f_max))
            if 0 <= x < w:
                image[: h // 12, max(0, x - 1) : x + 2] = couleur
    return image


def multiburst(
    h: int = 576, w: int = 768, norme: str | Norme = "PAL-BG",
    frequences: tuple[float, ...] = (0.5e6, 1.0e6, 2.0e6, 3.0e6, 4.0e6, 5.0e6),
) -> np.ndarray:
    """Salves de fréquences fixes — mesure directe de la bande passante.

    Chaque salve est un train sinusoïdal à une fréquence précise. Après
    passage dans la chaîne, l'amplitude qui subsiste dans chaque salve donne
    la réponse en fréquence du système. Les salves au-delà de la coupure
    disparaissent purement et simplement ; celle qui coïncide avec la
    sous-porteuse ressort en couleur.
    """
    n = norme if isinstance(norme, Norme) else obtenir_norme(norme)
    image = np.full((h, w, 3), 0.5)
    n_salves = len(frequences)
    bornes = np.round(np.linspace(0, w, n_salves + 1)).astype(int)
    for k, f in enumerate(frequences):
        a, b = bornes[k], bornes[k + 1]
        t = np.linspace(0.0, n.duree_ligne_active * (b - a) / w, b - a)
        image[:, a:b] = (0.5 + 0.4 * np.sin(2 * np.pi * f * t))[None, :, None]
    return image


def piege_dot_crawl(h: int = 576, w: int = 768) -> np.ndarray:
    """Pavés de couleur saturée sur fond neutre — la mire du dot crawl.

    Le filtre en peigne suppose que la luminance ne change pas d'une ligne à
    la suivante. Cette mire est faite de contours **horizontaux** francs, où
    l'hypothèse est violée frontalement : la chrominance résiduelle qui fuit
    dans le canal de luminance dessine alors le motif de points rampants.
    """
    image = np.full((h, w, 3), 0.5)
    couleurs = [(0.75, 0, 0), (0, 0.75, 0), (0, 0, 0.75), (0.75, 0.75, 0),
                (0, 0.75, 0.75), (0.75, 0, 0.75)]
    lignes, colonnes = 2, 3
    for k, couleur in enumerate(couleurs):
        r, c = divmod(k, colonnes)
        y0 = int(h * (r + 0.15) / lignes)
        y1 = int(h * (r + 0.85) / lignes)
        x0 = int(w * (c + 0.12) / colonnes)
        x1 = int(w * (c + 0.88) / colonnes)
        image[y0:y1, x0:x1] = couleur
    return image


def grille(h: int = 576, w: int = 768, pas: int = 48) -> np.ndarray:
    """Quadrillage blanc sur noir — géométrie et suréquilibrage des contours."""
    image = np.zeros((h, w, 3))
    image[::pas, :] = 1.0
    image[:, ::pas] = 1.0
    image[-1, :] = 1.0
    image[:, -1] = 1.0
    return image


# ---------------------------------------------------------------------------
# Mires colorimétriques
# ---------------------------------------------------------------------------

def roue_de_teintes(h: int = 576, w: int = 768, saturation: float = 0.9) -> np.ndarray:
    """Disque de teintes — pour lire une rotation de teinte au degré près.

    Sur un décodage sans erreur, la couleur en haut du disque est exactement
    la même à l'entrée et à la sortie. Une erreur de phase NTSC fait tourner
    tout le disque ; le PAL, à erreur identique, se contente de le pâlir.
    """
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = w / 2.0, h / 2.0
    rayon = min(cx, cy) * 0.92
    dx, dy = (xx - cx) / rayon, (yy - cy) / rayon
    r = np.hypot(dx, dy)
    teinte = (np.arctan2(dy, dx) / (2 * np.pi)) % 1.0
    return np.where(
        (r <= 1.0)[..., None],
        _hsv_vers_rgb(teinte, np.clip(r, 0, 1) * saturation, np.ones_like(r)),
        0.5,
    )


def degrade_saturation(h: int = 576, w: int = 768) -> np.ndarray:
    """Six teintes en colonnes, saturation croissante du haut vers le bas.

    Rend visible d'un coup d'œil l'écrêtage hors gamut : les cases du bas,
    les plus saturées, sont celles dont la chrominance déborde du cube RGB
    après matriçage inverse.
    """
    teintes = np.linspace(0.0, 1.0, w, endpoint=False)[None, :]
    saturations = np.linspace(0.0, 1.0, h)[:, None]
    return _hsv_vers_rgb(
        np.broadcast_to(teintes, (h, w)),
        np.broadcast_to(saturations, (h, w)),
        np.full((h, w), 0.85),
    )


def rampe(h: int = 576, w: int = 768) -> np.ndarray:
    """Rampe de luminance de 0 à 100 % — révèle le piédestal et le gamma."""
    return np.broadcast_to(
        np.linspace(0.0, 1.0, w)[None, :, None], (h, w, 3)
    ).copy()


def _hsv_vers_rgb(teinte, saturation, valeur):
    """Conversion TSV → RGB vectorisée, sans dépendance externe."""
    h6 = (teinte % 1.0) * 6.0
    i = np.floor(h6).astype(int) % 6
    f = h6 - np.floor(h6)
    p = valeur * (1.0 - saturation)
    q = valeur * (1.0 - saturation * f)
    t = valeur * (1.0 - saturation * (1.0 - f))
    choix = np.stack(
        [
            np.stack([valeur, t, p], -1), np.stack([q, valeur, p], -1),
            np.stack([p, valeur, t], -1), np.stack([p, q, valeur], -1),
            np.stack([t, p, valeur], -1), np.stack([valeur, p, q], -1),
        ]
    )
    return np.take_along_axis(choix, i[None, ..., None], axis=0)[0]


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Mires nationales
# ---------------------------------------------------------------------------
#
# Trois cartes de test d'époque, reconstruites élément par élément.
#
# CE QUI EST EXACT, ET CE QUI NE L'EST PAS. Il faut le dire d'emblée, parce que
# la tentation serait grande de faire passer une jolie image pour un fac-similé.
#
#   - Les éléments MESURABLES sont exacts, et calculés depuis la norme choisie :
#     les réseaux de fréquence tombent sur les mégahertz annoncés parce qu'ils
#     sont dérivés de `duree_ligne_active`, les barres de couleur sortent de
#     `ORDRE_BARRES` à 75 %, l'escalier de gris a des marches égales. Ce sont
#     eux qui font de ces mires des instruments plutôt que des décorations.
#
#   - La DISPOSITION est une reconstruction. Elle reprend la structure de chaque
#     carte — ce qu'elle contenait, et à quoi chaque élément servait — sans
#     prétendre au pixel près. Les proportions viennent de photographies
#     d'écrans, pas d'un document de normalisation.
#
#   - La PHOTOGRAPHIE de la Test Card F n'est pas reproduite. On ne synthétise
#     pas une petite fille et un clown ; le panneau central garde le tableau
#     noir et sa grille de morpion, qui étaient bien dessinés dessus.

_ALPHABET = {
    # Cinq colonnes sur sept lignes : la matrice des générateurs de caractères
    # de l'époque, et bien assez pour trois sigles.
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."),
    " ": (".....",) * 7,
}


def _texte(image, texte: str, y: int, x: int, echelle: int, couleur) -> None:
    """Écrit en majuscules dans une matrice 5 × 7, à l'échelle demandée.

    L'alphabet ne contient que les caractères dont les trois mires ont besoin.
    Un caractère absent lève, plutôt que de dessiner un blanc silencieux.
    """
    curseur = x
    for caractere in texte.upper():
        if caractere not in _ALPHABET:
            raise KeyError(f"caractère absent de l'alphabet des mires : {caractere!r}")
        glyphe = _ALPHABET[caractere]
        for ligne, motif in enumerate(glyphe):
            for colonne, point in enumerate(motif):
                if point != "#":
                    continue
                y0 = y + ligne * echelle
                x0 = curseur + colonne * echelle
                image[y0 : y0 + echelle, x0 : x0 + echelle] = couleur
        curseur += 6 * echelle


def _anneau(image, cy: float, cx: float, rayon: float, epaisseur: float, couleur) -> None:
    """Cercle en trait fin — le contrôle de géométrie de toutes les mires.

    Un tube mal réglé le rend ovale ; un balayage non linéaire l'aplatit d'un
    côté. C'est l'élément le plus universel des cartes de test, et le seul qu'on
    trouve sur toutes sans exception.
    """
    yy, xx = np.mgrid[0 : image.shape[0], 0 : image.shape[1]]
    # Le rayon est mesuré en unités de HAUTEUR dans les deux directions : sur
    # une trame 4:3 à pixels carrés, le cercle doit être rond à l'écran.
    r = np.hypot(yy - cy, xx - cx)
    image[np.abs(r - rayon) <= epaisseur] = couleur


def _quadrillage(image, pas: int, couleur, epaisseur: int = 1) -> None:
    """Quadrillage centré sur l'image — linéarité du balayage."""
    h, w = image.shape[:2]
    for y in range(h // 2 % pas, h, pas):
        image[y : y + epaisseur, :] = couleur
    for x in range(w // 2 % pas, w, pas):
        image[:, x : x + epaisseur] = couleur


def _creneaux(image, y0: int, y1: int, n: int, premier=1.0, second=0.0) -> None:
    """Créneaux noir et blanc sur toute la largeur — le contrôle de surbalayage.

    Un téléviseur affichait volontairement un peu moins que l'image transmise,
    pour cacher les défauts de bord. Compter les créneaux encore visibles
    mesurait ce surbalayage — et c'est pour cela qu'ils bordent toutes ces
    mires.
    """
    bornes = np.round(np.linspace(0, image.shape[1], n + 1)).astype(int)
    for k in range(n):
        image[y0:y1, bornes[k] : bornes[k + 1]] = premier if k % 2 == 0 else second


def _escalier(image, y0: int, y1: int, x0: int, x1: int, marches: int = 8) -> None:
    """Escalier de gris à marches égales — le contrôle du gamma."""
    bornes = np.round(np.linspace(x0, x1, marches + 1)).astype(int)
    for k in range(marches):
        image[y0:y1, bornes[k] : bornes[k + 1]] = k / (marches - 1)


def _reseau(image, y0: int, y1: int, x0: int, x1: int, f: float, n) -> None:
    """Réseau sinusoïdal à une fréquence donnée, en hertz de signal vidéo.

    La conversion n'a rien d'approximatif : la position horizontale dans
    l'image correspond à un instant dans la ligne active, et c'est cet instant
    qui décide de la fréquence. Un réseau à 4,8 MHz disparaît donc vraiment
    derrière la coupure de luminance de la norme, sans qu'on ait rien réglé.
    """
    largeur_totale = image.shape[1]
    t = (np.arange(x0, x1) / largeur_totale) * n.duree_ligne_active
    image[y0:y1, x0:x1] = (0.5 + 0.4 * np.sin(2 * np.pi * f * t))[None, :, None]


def _eventail(image, cy: float, cx: float, rayon: float, secteurs: int,
              angle0: float, ouverture: float) -> None:
    """Éventail de barres convergentes — la mire de définition proprement dite.

    Les barres se resserrent en approchant du sommet : on lit la définition à
    l'endroit où elles cessent d'être distinctes et se fondent en un gris
    uniforme. C'est la mesure la plus directe qui soit, et elle se fait à l'œil
    nu, sans instrument.
    """
    yy, xx = np.mgrid[0 : image.shape[0], 0 : image.shape[1]]
    dy, dx = yy - cy, xx - cx
    r = np.hypot(dy, dx)
    angle = np.arctan2(dy, dx)
    ecart = np.abs((angle - angle0 + np.pi) % (2 * np.pi) - np.pi)

    dedans = (r <= rayon) & (ecart <= ouverture / 2)
    barre = np.floor((angle - angle0) / (ouverture / secteurs)) % 2 == 0
    image[dedans & barre] = 1.0
    image[dedans & ~barre] = 0.0


def _bandes_couleur(image, y0: int, y1: int, x0: int, x1: int, niveau: float = 0.75):
    """Les huit barres normalisées, dans un rectangle."""
    bornes = np.round(np.linspace(x0, x1, len(ORDRE_BARRES) + 1)).astype(int)
    for k, rgb in enumerate(ORDRE_BARRES):
        image[y0:y1, bornes[k] : bornes[k + 1]] = tuple(niveau * c for c in rgb)


# ---------------------------------------------------------------------------

def mire_tdf(h: int = 576, w: int = 768, norme: str | Norme = "PAL-BG") -> np.ndarray:
    """France — la mire électronique de Télédiffusion de France.

    De la famille du générateur Philips PM5544, dont dérivaient la plupart des
    mires électroniques européennes : fond quadrillé gris, cercle de géométrie,
    créneaux de surbalayage en haut et en bas, barres de couleur, réseaux de
    fréquence, escalier de gris, et un rectangle blanc central portant
    l'identification de l'émetteur.

    Ce rectangle central est ce qui distinguait les mires nationales entre
    elles : on y lisait ici « TDF », ailleurs le nom de la chaîne ou le numéro
    du réémetteur. Le reste était à peu de choses près commun à toute l'Europe.
    """
    n = norme if isinstance(norme, Norme) else obtenir_norme(norme)
    image = np.full((h, w, 3), 0.5)

    _quadrillage(image, pas=max(8, h // 12), couleur=1.0)

    # Créneaux de surbalayage, en haut et en bas.
    _creneaux(image, 0, max(2, h // 24), 24)
    _creneaux(image, h - max(2, h // 24), h, 24)

    bande = max(2, h // 24)

    # Barres de couleur, dans le tiers supérieur.
    _bandes_couleur(image, int(0.22 * h), int(0.36 * h), 0, w)

    # Réseaux de fréquence, au tiers inférieur. Les quatre valeurs encadrent la
    # coupure de luminance de la norme : les deux premiers doivent passer, le
    # dernier disparaître.
    frequences = (1.5e6, 2.8e6, 3.8e6, 4.8e6)
    bornes = np.round(np.linspace(0, w, len(frequences) + 1)).astype(int)
    for k, f in enumerate(frequences):
        _reseau(image, int(0.58 * h), int(0.72 * h), bornes[k], bornes[k + 1], f, n)

    # Escalier de gris, tout en bas.
    _escalier(image, int(0.76 * h), int(0.90 * h), 0, w)

    # Le rectangle d'identification, au centre.
    y0, y1 = int(0.42 * h), int(0.54 * h)
    x0, x1 = int(0.33 * w), int(0.67 * w)
    image[y0:y1, x0:x1] = 1.0
    echelle = max(1, (y1 - y0) // 12)
    _texte(image, "TDF", y0 + (y1 - y0 - 7 * echelle) // 2,
           x0 + ((x1 - x0) - 17 * echelle) // 2, echelle, 0.0)

    _anneau(image, h / 2.0, w / 2.0, 0.45 * h, max(1.0, h / 400.0), 1.0)
    return image


def mire_test_card_f(h: int = 576, w: int = 768, norme: str | Norme = "PAL-BG") -> np.ndarray:
    """Royaume-Uni — la Test Card F de la BBC, 1967.

    La première mire de test britannique en couleur, et la plus longtemps
    diffusée : un cadre crénelé, un grand cercle de géométrie, des barres de
    couleur verticales de part et d'autre du panneau central, un escalier de
    gris, et des réseaux de fréquence dans les angles.

    **La photographie n'est pas reproduite** — ni la petite fille, ni le clown.
    Le panneau central garde le tableau noir et sa grille de morpion, qui
    étaient bien dessinés derrière eux, et rien de plus. Ce qui suit est donc
    une reconstruction de la structure de la carte, pas un fac-similé.
    """
    n = norme if isinstance(norme, Norme) else obtenir_norme(norme)
    image = np.full((h, w, 3), 0.5)

    bordure = max(2, h // 22)
    _creneaux(image, 0, bordure, 20)
    _creneaux(image, h - bordure, h, 20)
    # Créneaux verticaux, sur les côtés.
    bornes = np.round(np.linspace(0, h, 15)).astype(int)
    for k in range(14):
        valeur = 1.0 if k % 2 == 0 else 0.0
        image[bornes[k] : bornes[k + 1], :bordure] = valeur
        image[bornes[k] : bornes[k + 1], w - bordure :] = valeur

    # Barres de couleur verticales, de part et d'autre du panneau central.
    couleurs = ORDRE_BARRES[:7]
    hauteurs = np.round(np.linspace(int(0.18 * h), int(0.82 * h), len(couleurs) + 1))
    for cote in (int(0.16 * w), int(0.78 * w)):
        for k, rgb in enumerate(couleurs):
            y0, y1 = int(hauteurs[k]), int(hauteurs[k + 1])
            image[y0:y1, cote : cote + int(0.06 * w)] = tuple(0.75 * c for c in rgb)

    # Réseaux de fréquence dans les quatre angles. Les deux du bas passent
    # SOUS l'escalier de gris : dans l'autre ordre, l'escalier les recouvrait.
    for k, f in enumerate((1.5e6, 2.5e6, 3.5e6, 4.5e6)):
        haut = k < 2
        gauche = k % 2 == 0
        y0 = int(0.14 * h) if haut else int(0.83 * h)
        x0 = int(0.26 * w) if gauche else int(0.58 * w)
        _reseau(image, y0, y0 + int(0.11 * h), x0, x0 + int(0.16 * w), f, n)

    # Le panneau central : un tableau noir et sa grille de morpion.
    y0, y1 = int(0.28 * h), int(0.72 * h)
    x0, x1 = int(0.30 * w), int(0.70 * w)
    image[y0:y1, x0:x1] = 0.12
    trait = max(1, h // 200)
    for k in (1, 2):
        y = y0 + (y1 - y0) * k // 3
        x = x0 + (x1 - x0) * k // 3
        image[y : y + trait, x0:x1] = 0.85
        image[y0:y1, x : x + trait] = 0.85

    # Escalier de gris, sous le panneau.
    _escalier(image, int(0.74 * h), int(0.80 * h), int(0.26 * w), int(0.74 * w))

    # L'identification de la chaîne, dans un cartouche en haut — c'est elle qui
    # changeait d'une chaîne à l'autre, le reste de la carte étant commun.
    echelle = max(1, h // 80)
    y0 = int(0.055 * h)
    hauteur_texte = 7 * echelle
    x0 = (w - 17 * echelle) // 2
    image[y0 - echelle : y0 + hauteur_texte + echelle,
          x0 - 2 * echelle : x0 + 17 * echelle + 2 * echelle] = 0.0
    _texte(image, "BBC", y0, x0, echelle, 1.0)

    _anneau(image, h / 2.0, w / 2.0, 0.44 * h, max(1.0, h / 400.0), 1.0)
    return image


def mire_nhk(h: int = 576, w: int = 768, norme: str | Norme = "NTSC-J") -> np.ndarray:
    """Japon — la mire de définition de la NHK.

    De la famille des monoscopes à éventails, dont dérivent aussi les mires
    américaines RETMA : le cœur en est la **mesure de définition à l'œil nu**.
    Cinq éventails de barres convergentes — un au centre, un dans chaque angle —
    dont on lit la définition à l'endroit où les barres cessent d'être
    distinctes et se fondent en gris.

    C'est la mire qui rend le plus visible ce que ce simulateur fait : la
    limitation de bande passante ne se devine pas, elle se lit. En SECAM, dont
    la voie de luminance est la plus large des trois, les éventails se résolvent
    plus loin qu'en NTSC.

    L'éventail central est doublé d'un quadrillage et d'un cercle pour la
    géométrie, et d'une bande de barres de couleur qui n'existait pas sur les
    monoscopes d'avant la couleur — ils étaient photographiques, et gravés sur
    une plaque.
    """
    n = norme if isinstance(norme, Norme) else obtenir_norme(norme)
    image = np.full((h, w, 3), 0.5)

    _quadrillage(image, pas=max(8, h // 14), couleur=0.75)

    # Les cinq éventails : centre, puis les quatre angles, tournés vers lui.
    rayon = 0.17 * h
    _eventail(image, h * 0.30, w * 0.5, rayon, 14, np.pi / 2, np.pi * 0.9)
    for cy, cx, angle in (
        (0.16 * h, 0.13 * w, np.pi / 4),
        (0.16 * h, 0.87 * w, 3 * np.pi / 4),
        (0.84 * h, 0.13 * w, -np.pi / 4),
        (0.84 * h, 0.87 * w, -3 * np.pi / 4),
    ):
        _eventail(image, cy, cx, rayon * 0.75, 10, angle, np.pi * 0.5)

    # Barres de couleur et escalier de gris, en bas.
    _bandes_couleur(image, int(0.60 * h), int(0.72 * h), int(0.18 * w), int(0.82 * w))
    _escalier(image, int(0.72 * h), int(0.82 * h), int(0.18 * w), int(0.82 * w))

    # Un réseau unique à la coupure de la norme : il doit disparaître.
    _reseau(image, int(0.86 * h), int(0.94 * h), int(0.30 * w), int(0.70 * w),
            n.bande_y, n)

    echelle = max(1, h // 64)
    y0 = int(0.49 * h)
    x0 = (w - 17 * echelle) // 2
    image[y0 - echelle : y0 + 8 * echelle,
          x0 - 2 * echelle : x0 + 19 * echelle] = 0.0
    _texte(image, "NHK", y0, x0, echelle, 1.0)

    _anneau(image, h / 2.0, w / 2.0, 0.47 * h, max(1.0, h / 400.0), 1.0)
    return image


CATALOGUE = {
    "Barres de couleur 75 %": barres_couleur,
    "Mire SMPTE": barres_smpte,
    "Balayage de fréquence (cross-color)": balayage_frequentiel,
    "Multiburst": multiburst,
    "Piège à dot crawl": piege_dot_crawl,
    "Roue de teintes": roue_de_teintes,
    "Dégradé de saturation": degrade_saturation,
    "Rampe de luminance": rampe,
    "Quadrillage": grille,
    "Mire TDF (France)": mire_tdf,
    "Test Card F (Royaume-Uni)": mire_test_card_f,
    "Mire NHK (Japon)": mire_nhk,
}


def obtenir_mire(nom: str, h: int = 576, w: int = 768, **kwargs) -> np.ndarray:
    """Génère une mire du catalogue."""
    if nom not in CATALOGUE:
        raise KeyError(f"mire inconnue : {nom!r}")
    return np.clip(CATALOGUE[nom](h, w, **kwargs), 0.0, 1.0)
