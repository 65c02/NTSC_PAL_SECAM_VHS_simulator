"""
Colorimétrie : primaires, blancs de référence, gamma.

Ce module fait le lien entre le fichier image (sRGB, primaires BT.709,
blanc D65) et le signal R'G'B' que voit réellement un codeur de télévision
analogique — lequel suppose d'autres primaires et un autre gamma.

Deux transformations distinctes, souvent confondues :

* le **changement de primaires**, qui est une rotation dans l'espace des
  couleurs : le « rouge » d'un tube NTSC 1953 n'est pas le « rouge » d'un
  écran sRGB, donc le même triplet numérique n'y désigne pas la même couleur ;
* le **gamma**, qui est une déformation non linéaire de chaque canal,
  appliquée à la prise de vue pour compenser la loi de puissance du tube
  cathodique.

L'ordre importe : les primaires se combinent linéairement (dans l'espace
XYZ), le gamma s'applique après, canal par canal.
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Blancs de référence (coordonnées chromatiques CIE 1931 xy)
# ---------------------------------------------------------------------------

BLANCS: dict[str, tuple[float, float]] = {
    # Illuminant C : le blanc de la télévision de 1953, une lumière du jour
    # approximative, légèrement bleutée (≈ 6774 K).
    "C": (0.31006, 0.31616),
    # D65 : le blanc adopté par l'EBU puis par tout le monde (≈ 6504 K).
    "D65": (0.31270, 0.32900),
    # D93 : le blanc « froid » des téléviseurs japonais, d'où NTSC-J.
    "D93": (0.28315, 0.29711),
}


# ---------------------------------------------------------------------------
# Jeux de primaires
# ---------------------------------------------------------------------------

class Primaires:
    """Trois primaires xy plus un blanc de référence."""

    __slots__ = ("nom", "rouge", "vert", "bleu", "blanc", "description")

    def __init__(self, nom, rouge, vert, bleu, blanc, description=""):
        self.nom = nom
        self.rouge = rouge
        self.vert = vert
        self.bleu = bleu
        self.blanc = BLANCS[blanc]
        self.description = description

    def matrice_vers_xyz(self) -> np.ndarray:
        """Matrice 3×3 convertissant RGB linéaire → XYZ.

        Méthode classique : on écrit la matrice des primaires normalisées par
        leur y, puis on cherche les trois facteurs d'échelle qui font
        correspondre RGB = (1,1,1) au blanc de référence.
        """
        def colonne(xy):
            x, y = xy
            return np.array([x / y, 1.0, (1.0 - x - y) / y])

        m = np.column_stack([colonne(self.rouge), colonne(self.vert), colonne(self.bleu)])
        blanc_xyz = colonne(self.blanc)
        echelles = np.linalg.solve(m, blanc_xyz)
        return m * echelles

    def coefficients_luma(self) -> np.ndarray:
        """Coefficients (kR, kG, kB) de la luminance Y pour ces primaires.

        C'est simplement la deuxième ligne de la matrice RGB→XYZ : Y est,
        par construction, la composante de luminance photométrique du
        système CIE.

        Pour les primaires NTSC 1953 sous illuminant C, on retrouve
        (0,299 ; 0,587 ; 0,114) — les coefficients de luma inscrits dans
        toutes les normes de télévision depuis. Le test
        `tests/test_matrices.py::test_origine_des_coefficients_luma` le vérifie.
        """
        return self.matrice_vers_xyz()[1]


PRIMAIRES: dict[str, Primaires] = {
    "ntsc1953": Primaires(
        "NTSC 1953",
        rouge=(0.67, 0.33),
        vert=(0.21, 0.71),
        bleu=(0.14, 0.08),
        blanc="C",
        description=(
            "Primaires d'origine du NTSC, très saturées. Les luminophores "
            "capables de les produire étaient si peu lumineux qu'aucun "
            "constructeur ne les a suivies : dès les années 1960, les tubes "
            "réels avaient un gamut bien plus étroit, normalisé plus tard "
            "sous le nom SMPTE-C."
        ),
    ),
    "smpte-c": Primaires(
        "SMPTE-C",
        rouge=(0.630, 0.340),
        vert=(0.310, 0.595),
        bleu=(0.155, 0.070),
        blanc="D65",
        description="Primaires réelles des tubes NTSC à partir des années 1970.",
    ),
    "ebu": Primaires(
        "EBU Tech. 3213",
        rouge=(0.64, 0.33),
        vert=(0.29, 0.60),
        bleu=(0.15, 0.06),
        blanc="D65",
        description="Primaires PAL/SECAM 625 lignes, quasi identiques à BT.709.",
    ),
    "bt709": Primaires(
        "BT.709 / sRGB",
        rouge=(0.640, 0.330),
        vert=(0.300, 0.600),
        bleu=(0.150, 0.060),
        blanc="D65",
        description="Primaires de la vidéo numérique et des écrans actuels.",
    ),
}


# ---------------------------------------------------------------------------
# Adaptation chromatique (Bradford)
# ---------------------------------------------------------------------------

_BRADFORD = np.array(
    [
        [0.8951, 0.2664, -0.1614],
        [-0.7502, 1.7135, 0.0367],
        [0.0389, -0.0685, 1.0296],
    ]
)


def _xyz_du_blanc(xy: tuple[float, float]) -> np.ndarray:
    x, y = xy
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


def adaptation_chromatique(blanc_source, blanc_cible) -> np.ndarray:
    """Matrice d'adaptation de von Kries–Bradford entre deux blancs.

    Sans elle, convertir des primaires sous illuminant C vers des primaires
    sous D65 donnerait une dominante colorée : on comparerait des couleurs
    définies sous deux éclairages différents.
    """
    src = _BRADFORD @ _xyz_du_blanc(blanc_source)
    dst = _BRADFORD @ _xyz_du_blanc(blanc_cible)
    return np.linalg.inv(_BRADFORD) @ np.diag(dst / src) @ _BRADFORD


def matrice_conversion_primaires(source: str, cible: str) -> np.ndarray:
    """Matrice 3×3 RGB linéaire (source) → RGB linéaire (cible).

    Exemple : `matrice_conversion_primaires("bt709", "ntsc1953")` réinterprète
    une image sRGB comme si elle avait été produite pour un tube NTSC 1953.
    Les couleurs saturées deviennent alors nettement plus ternes, puisque le
    même triplet numérique désigne désormais une couleur plus éloignée du blanc.
    """
    p_src, p_dst = PRIMAIRES[source], PRIMAIRES[cible]
    m_src = p_src.matrice_vers_xyz()
    m_dst = p_dst.matrice_vers_xyz()
    adapt = adaptation_chromatique(p_src.blanc, p_dst.blanc)
    return np.linalg.inv(m_dst) @ adapt @ m_src


def convertir_primaires(rgb_lineaire: np.ndarray, source: str, cible: str) -> np.ndarray:
    """Applique un changement de primaires à une image RGB linéaire (H, W, 3)."""
    if source == cible:
        return rgb_lineaire
    m = matrice_conversion_primaires(source, cible)
    return rgb_lineaire @ m.T


# ---------------------------------------------------------------------------
# Fonctions de transfert
# ---------------------------------------------------------------------------

def srgb_vers_lineaire(v: np.ndarray) -> np.ndarray:
    """EOTF sRGB : valeur d'un fichier image → luminance relative linéaire."""
    v = np.asarray(v, dtype=np.float64)
    return np.where(v <= 0.04045, v / 12.92, ((np.clip(v, 0.0, None) + 0.055) / 1.055) ** 2.4)


def lineaire_vers_srgb(v: np.ndarray) -> np.ndarray:
    """OETF sRGB : luminance relative linéaire → valeur d'un fichier image."""
    v = np.clip(np.asarray(v, dtype=np.float64), 0.0, None)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * v ** (1.0 / 2.4) - 0.055)


def oetf_camera(lineaire: np.ndarray, gamma_affichage: float) -> np.ndarray:
    """Correction de gamma appliquée à la prise de vue : L → L^(1/γ).

    C'est ici que se joue le péché originel de la télévision couleur.
    Le codeur ne matrice pas la luminance L, mais sa racine γ-ième L^(1/γ).
    Autrement dit, il calcule

        Y' = 0,299 R'^ + 0,587 G'^ + 0,114 B'^      (^ = déjà gamma-corrigé)

    et non pas la vraie luminance

        Y  = 0,299 R  + 0,587 G  + 0,114 B .

    Ces deux quantités ne coïncident que sur les gris. Sur les couleurs
    saturées, Y' sous-estime la luminance réelle : la part manquante voyage
    dans les signaux de chrominance, que l'on va justement filtrer sévèrement.
    C'est la **non-constant-luminance**, cf. `mesures.perte_de_luminance`.
    """
    return np.clip(np.asarray(lineaire, dtype=np.float64), 0.0, None) ** (1.0 / gamma_affichage)


def eotf_ecran(gamma_corrige: np.ndarray, gamma_affichage: float) -> np.ndarray:
    """Loi du tube cathodique : R' → R'^γ. Inverse de `oetf_camera`."""
    return np.clip(np.asarray(gamma_corrige, dtype=np.float64), 0.0, None) ** gamma_affichage


# ---------------------------------------------------------------------------
# CIELAB, pour mesurer les écarts perceptuels
# ---------------------------------------------------------------------------

def xyz_vers_lab(xyz: np.ndarray, blanc: str = "D65") -> np.ndarray:
    """Conversion XYZ → CIE L*a*b*."""
    blanc_xyz = _xyz_du_blanc(BLANCS[blanc])
    r = np.asarray(xyz, dtype=np.float64) / blanc_xyz
    delta = 6.0 / 29.0
    f = np.where(r > delta**3, np.cbrt(np.clip(r, 0, None)), r / (3 * delta**2) + 4.0 / 29.0)
    return np.stack(
        [
            116.0 * f[..., 1] - 16.0,
            500.0 * (f[..., 0] - f[..., 1]),
            200.0 * (f[..., 1] - f[..., 2]),
        ],
        axis=-1,
    )


def srgb_vers_lab(srgb: np.ndarray) -> np.ndarray:
    """Image sRGB (0..1) → CIE L*a*b*, via les primaires BT.709 et D65."""
    lineaire = srgb_vers_lineaire(srgb)
    xyz = lineaire @ PRIMAIRES["bt709"].matrice_vers_xyz().T
    return xyz_vers_lab(xyz, "D65")


def delta_e_76(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """Écart colorimétrique ΔE*ab (CIE 1976), en unités JND approximatives.

    ΔE ≈ 1 correspond au seuil de perception d'un observateur entraîné,
    ΔE ≈ 3 à une différence évidente pour tout le monde.
    """
    return np.sqrt(np.sum((np.asarray(lab1) - np.asarray(lab2)) ** 2, axis=-1))
