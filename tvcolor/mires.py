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
}


def obtenir_mire(nom: str, h: int = 576, w: int = 768, **kwargs) -> np.ndarray:
    """Génère une mire du catalogue."""
    if nom not in CATALOGUE:
        raise KeyError(f"mire inconnue : {nom!r}")
    return np.clip(CATALOGUE[nom](h, w, **kwargs), 0.0, 1.0)
