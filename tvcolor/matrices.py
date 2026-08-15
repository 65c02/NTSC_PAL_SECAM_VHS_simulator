"""
Matriçage : R'G'B' ↔ Y'UV ↔ Y'IQ ↔ Y'D'RD'B.

Toutes ces matrices agissent sur des composantes **déjà gamma-corrigées**
(notées avec une apostrophe). C'est un point de doctrine, pas un détail
d'implémentation : les normes de télévision matricent après le gamma, ce qui
rend Y' différent de la luminance physique (cf. `colorimetrie.oetf_camera`).

Conventions de forme : toutes les fonctions acceptent un tableau de forme
`(..., 3)` et retournent un tableau de même forme.
"""

from __future__ import annotations

import numpy as np

from .constantes import (
    ANGLE_IQ_DEG,
    FACTEUR_DB,
    FACTEUR_DR,
    FACTEUR_U,
    FACTEUR_V,
    KB,
    KG,
    KR,
)

# ---------------------------------------------------------------------------
# Y' — la luma
# ---------------------------------------------------------------------------

COEFFS_LUMA = np.array([KR, KG, KB])


def luma(rgb: np.ndarray) -> np.ndarray:
    """Y' = 0,299 R' + 0,587 G' + 0,114 B'."""
    return np.asarray(rgb, dtype=np.float64) @ COEFFS_LUMA


# ---------------------------------------------------------------------------
# Y'UV — la base de PAL, et la base de référence pour tout le reste
# ---------------------------------------------------------------------------
#
#   U = 0,492 (B' - Y')
#   V = 0,877 (R' - Y')
#
# Pourquoi ces deux facteurs ? Voir `deriver_facteurs_echelle` : ce sont les
# seules valeurs qui font tenir le signal composite exactement dans l'intervalle
# [-1/3, +4/3] sur les six couleurs primaires et complémentaires saturées.

MATRICE_RGB_YUV = np.array(
    [
        [KR, KG, KB],
        [-FACTEUR_U * KR, -FACTEUR_U * KG, FACTEUR_U * (1.0 - KB)],
        [FACTEUR_V * (1.0 - KR), -FACTEUR_V * KG, -FACTEUR_V * KB],
    ]
)

MATRICE_YUV_RGB = np.linalg.inv(MATRICE_RGB_YUV)


def rgb_vers_yuv(rgb: np.ndarray) -> np.ndarray:
    return np.asarray(rgb, dtype=np.float64) @ MATRICE_RGB_YUV.T


def yuv_vers_rgb(yuv: np.ndarray) -> np.ndarray:
    return np.asarray(yuv, dtype=np.float64) @ MATRICE_YUV_RGB.T


# ---------------------------------------------------------------------------
# Y'IQ — la base de NTSC
# ---------------------------------------------------------------------------
#
# I et Q sont U et V tournés de 33°. L'intérêt : l'acuité chromatique de l'œil
# n'est pas isotrope. Elle est meilleure le long de l'axe orange–cyan (≈ +123°
# dans le plan UV, c'est l'axe I) que le long de l'axe vert–magenta (l'axe Q).
# NTSC exploite cette asymétrie en accordant 1,3 MHz à I et seulement 0,4 MHz
# à Q — une économie de bande passante qui n'a coûté aucune qualité perçue.
#
#   I = V cos33° - U sin33°
#   Q = V sin33° + U cos33°

_theta = np.deg2rad(ANGLE_IQ_DEG)
_c, _s = np.cos(_theta), np.sin(_theta)

MATRICE_UV_IQ = np.array([[-_s, _c], [_c, _s]])   # (U,V) → (I,Q)
MATRICE_IQ_UV = np.linalg.inv(MATRICE_UV_IQ)

MATRICE_RGB_YIQ = np.vstack(
    [MATRICE_RGB_YUV[0], MATRICE_UV_IQ @ MATRICE_RGB_YUV[1:]]
)
MATRICE_YIQ_RGB = np.linalg.inv(MATRICE_RGB_YIQ)


def rgb_vers_yiq(rgb: np.ndarray) -> np.ndarray:
    return np.asarray(rgb, dtype=np.float64) @ MATRICE_RGB_YIQ.T


def yiq_vers_rgb(yiq: np.ndarray) -> np.ndarray:
    return np.asarray(yiq, dtype=np.float64) @ MATRICE_YIQ_RGB.T


def uv_vers_iq(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return (-_s * u + _c * v, _c * u + _s * v)


def iq_vers_uv(i: np.ndarray, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # Rotation inverse : l'inverse d'une matrice orthogonale est sa transposée.
    return (-_s * i + _c * q, _c * i + _s * q)


# ---------------------------------------------------------------------------
# Y'D'RD'B — la base de SECAM
# ---------------------------------------------------------------------------
#
#   D'B = +1,505 (B' - Y')
#   D'R = -1,902 (R' - Y')
#
# Les facteurs sont plus grands qu'en PAL parce que la modulation est en
# fréquence : l'amplitude du signal en bande de base n'a plus à cohabiter avec
# la luma dans la même excursion. Le signe négatif de D'R est un choix de norme
# qui équilibre les excursions positives et négatives après préaccentuation.

MATRICE_RGB_YDRDB = np.array(
    [
        [KR, KG, KB],
        [FACTEUR_DR * (1.0 - KR), -FACTEUR_DR * KG, -FACTEUR_DR * KB],  # D'R
        [-FACTEUR_DB * KR, -FACTEUR_DB * KG, FACTEUR_DB * (1.0 - KB)],  # D'B
    ]
)
MATRICE_YDRDB_RGB = np.linalg.inv(MATRICE_RGB_YDRDB)


def rgb_vers_ydrdb(rgb: np.ndarray) -> np.ndarray:
    """Retourne (Y', D'R, D'B)."""
    return np.asarray(rgb, dtype=np.float64) @ MATRICE_RGB_YDRDB.T


def ydrdb_vers_rgb(ydrdb: np.ndarray) -> np.ndarray:
    return np.asarray(ydrdb, dtype=np.float64) @ MATRICE_YDRDB_RGB.T


def uv_vers_drdb(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(U, V) → (D'R, D'B). Simple changement d'échelle, sans rotation."""
    return (FACTEUR_DR / FACTEUR_V * v, FACTEUR_DB / FACTEUR_U * u)


def drdb_vers_uv(dr: np.ndarray, db: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return (FACTEUR_U / FACTEUR_DB * db, FACTEUR_V / FACTEUR_DR * dr)


# ---------------------------------------------------------------------------
# D'où viennent 0,492 et 0,877 ?
# ---------------------------------------------------------------------------

def deriver_facteurs_echelle(
    excursion_max: float = 4.0 / 3.0,
    excursion_min: float = -1.0 / 3.0,
) -> tuple[float, float]:
    """Recalcule les facteurs d'échelle de U et V à partir de leur cahier des charges.

    Le signal composite d'une couleur uniforme vaut

        S(t) = Y' + sqrt(U² + V²) · sin(ωt + φ)

    et oscille donc entre `Y' - A` et `Y' + A`, avec `A = sqrt(U² + V²)`.

    Le cahier des charges de 1953 impose que ce signal reste dans une
    excursion totale de 5/3 de l'amplitude vidéo : au plus +4/3 (pour ne pas
    saturer l'émetteur, dont le niveau de synchro occupe déjà le bas) et au
    moins -1/3 (pour ne pas empiéter sur la zone des synchros).

    Deux couples de couleurs saturent ces bornes :

    * **bleu et jaune** : Y'_bleu = 0,114, et le jaune en est le complément.
      Le bleu atteint la borne basse : ``0,114 - A_bleu = -1/3``.
    * **rouge et cyan** : Y'_rouge = 0,299 ; le cyan atteint la borne haute :
      ``0,701 + A_rouge = +4/3``, ce qui revient à ``0,299 - A_rouge = -1/3``.

    Cela fait deux équations pour deux inconnues (les facteurs de U et V).
    Le système est linéaire en leurs carrés ; on le résout exactement.

    Retourne le couple (facteur_U, facteur_V) ≈ (0,4921 ; 0,8772).
    """
    # Le bleu pur : R'=G'=0, B'=1, donc Y' = kB.
    y_bleu = KB
    db_bleu, dr_bleu = 1.0 - KB, -KB   # (B'-Y'), (R'-Y')
    a_bleu = y_bleu - excursion_min    # amplitude de chroma requise

    # Le rouge pur : R'=1, G'=B'=0, donc Y' = kR.
    y_rouge = KR
    db_rouge, dr_rouge = -KR, 1.0 - KR
    a_rouge = y_rouge - excursion_min

    # A² = (u·(B'-Y'))² + (v·(R'-Y'))², linéaire en (u², v²).
    systeme = np.array(
        [
            [db_bleu**2, dr_bleu**2],
            [db_rouge**2, dr_rouge**2],
        ]
    )
    second_membre = np.array([a_bleu**2, a_rouge**2])
    carres = np.linalg.solve(systeme, second_membre)

    # Élégance de la construction : les complémentaires (jaune et cyan) ont la
    # même amplitude de chroma que leur primaire, mais une luma complémentaire
    # 1 - Y'. Elles atteignent donc la borne haute exactement quand les
    # primaires atteignent la borne basse, à condition que
    # excursion_max = 1 - excursion_min. Les deux contraintes n'en font qu'une.
    if abs(excursion_max - (1.0 - excursion_min)) > 1e-12:
        raise ValueError(
            "excursions incompatibles : il faut excursion_max = 1 - excursion_min "
            "pour que primaires et complémentaires saturent les mêmes bornes"
        )

    return float(np.sqrt(carres[0])), float(np.sqrt(carres[1]))


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def matrice_de(base: str) -> tuple[np.ndarray, np.ndarray]:
    """Retourne (matrice directe RGB→base, matrice inverse) pour « UV », « IQ », « DRDB »."""
    tables = {
        "UV": (MATRICE_RGB_YUV, MATRICE_YUV_RGB),
        "IQ": (MATRICE_RGB_YIQ, MATRICE_YIQ_RGB),
        "DRDB": (MATRICE_RGB_YDRDB, MATRICE_YDRDB_RGB),
    }
    if base not in tables:
        raise KeyError(f"base de chrominance inconnue : {base!r}")
    return tables[base]


def saturation_et_teinte(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Coordonnées polaires du vecteur de chrominance : (module, argument).

    Le **module** porte la saturation, la **phase** porte la teinte. Toute
    l'histoire du NTSC tient dans cette phrase : une erreur de phase du canal
    devient une erreur de teinte, et l'œil est bien plus sensible à une
    dérive de teinte qu'à une dérive de saturation.
    """
    return np.hypot(u, v), np.arctan2(v, u)
