"""
Vérifie l'horloge de sous-porteuse — la propriété dont tout le reste découle.

Si ces tests passent, alors le dot crawl, le filtre en peigne et la séquence
à quatre trames du NTSC sont des conséquences arithmétiques et non des effets
ajoutés à la main.
"""

from __future__ import annotations

import numpy as np
import pytest

from tvcolor import porteuse
from tvcolor.constantes import (
    F_LIGNE_625,
    F_LIGNE_M,
    F_SC_NTSC,
    F_SC_PAL,
    F_SC_SECAM_B,
    F_SC_SECAM_R,
    obtenir_norme,
)


# ---------------------------------------------------------------------------
# Les relations entre sous-porteuse et fréquence ligne
# ---------------------------------------------------------------------------

def test_sous_porteuse_ntsc_est_un_multiple_demi_entier():
    """f_sc = 455/2 · f_H : le fondement de l'entrelacement spectral NTSC."""
    assert F_SC_NTSC / F_LIGNE_M == pytest.approx(227.5, abs=1e-12)
    assert F_SC_NTSC == pytest.approx(3_579_545.4545, abs=1e-3)


def test_sous_porteuse_pal_et_son_decalage_de_25_hz():
    """f_sc = (1135/4 + 1/625)·f_H, soit 283,7516 cycles par ligne.

    Le quart-entier place la chroma dans les creux du peigne de luminance ;
    le terme résiduel de 25 Hz décale le motif d'une image à la suivante pour
    le rendre moins visible.
    """
    cycles = F_SC_PAL / F_LIGNE_625
    assert cycles == pytest.approx(283.7516, abs=1e-4)
    assert F_SC_PAL == pytest.approx(4_433_618.75, abs=1e-3)
    # Le décalage vaut exactement une fréquence de trame divisée par deux.
    assert F_SC_PAL - (1135.0 / 4.0) * F_LIGNE_625 == pytest.approx(25.0, abs=1e-9)


def test_sous_porteuses_secam_sont_des_multiples_entiers():
    """272·f_H et 282·f_H : entières, donc jamais d'inversion d'une ligne à l'autre.

    C'est la raison mathématique pour laquelle aucun filtre en peigne ne peut
    séparer la chrominance SECAM, et pourquoi le motif de sous-porteuse y est
    fixe verticalement au lieu de ramper.
    """
    assert F_SC_SECAM_B / F_LIGNE_625 == pytest.approx(272.0, abs=1e-12)
    assert F_SC_SECAM_R / F_LIGNE_625 == pytest.approx(282.0, abs=1e-12)


# ---------------------------------------------------------------------------
# L'avance de phase par ligne
# ---------------------------------------------------------------------------

def test_ntsc_tourne_de_180_degres_par_ligne():
    """La propriété qui rend possible le filtre en peigne à une ligne."""
    norme = obtenir_norme("NTSC-M")
    assert porteuse.avance_de_phase_par_ligne(norme) == pytest.approx(180.0, abs=1e-9)


def test_pal_tourne_de_270_degres_par_ligne():
    """270,58° : trois quarts de tour. Un peigne à une ligne ne peut pas marcher.

    En revanche, sur deux lignes cela fait 541,15°, soit 181,15° modulo un
    tour — assez proche de l'inversion. D'où les peignes PAL à retard de 2H.
    """
    norme = obtenir_norme("PAL-BG")
    avance = porteuse.avance_de_phase_par_ligne(norme)
    assert avance == pytest.approx(270.576, abs=1e-3)
    assert (2 * avance) % 360.0 == pytest.approx(181.15, abs=0.05)


def test_secam_ne_tourne_pas():
    norme = obtenir_norme("SECAM-L")
    for f in (F_SC_SECAM_B, F_SC_SECAM_R):
        assert porteuse.avance_de_phase_par_ligne(norme, f) == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# La matrice de phase elle-même
# ---------------------------------------------------------------------------

def test_la_phase_calculee_alterne_bien_de_180_degres():
    """Vérification directe sur la matrice de phase, et non sur la formule.

    On compare la phase au même instant de deux lignes consécutives : l'écart
    doit valoir π à 1e-9 près, malgré les 227,5 cycles accumulés par ligne.
    """
    norme = obtenir_norme("NTSC-M")
    indices = porteuse.indices_lignes(norme, 32)
    phi = porteuse.phase(norme, indices, 16)

    ecart = np.mod(phi[1:] - phi[:-1], 2 * np.pi)
    assert np.allclose(ecart, np.pi, atol=1e-9)


def test_la_chroma_s_inverse_bien_d_une_ligne_a_l_autre_en_ntsc():
    """Conséquence pratique : moduler puis moyenner deux lignes annule la chroma.

    C'est le filtre en peigne, démontré sur un cas où la luminance est
    rigoureusement constante d'une ligne à l'autre.
    """
    norme = obtenir_norme("NTSC-M")
    indices = porteuse.indices_lignes(norme, 8)
    phi = porteuse.phase(norme, indices, 64)

    u = np.full((8, 64), 0.3)
    v = np.full((8, 64), -0.2)
    chroma = porteuse.moduler_quadrature(u, v, phi)

    moyenne = 0.5 * (chroma[1:] + chroma[:-1])
    assert np.max(np.abs(moyenne)) < 1e-12


def test_precision_conservee_sur_une_image_entiere():
    """Le calcul reste exact jusqu'à la dernière ligne de la 100ᵉ image.

    Sans la réduction modulo 1 opérée dans `phase`, on aurait accumulé plus de
    onze millions de cycles et perdu le demi-cycle dans l'arrondi flottant.
    """
    norme = obtenir_norme("NTSC-M")
    indices = porteuse.indices_lignes(norme, 480, numero_image=100)
    phi = porteuse.phase(norme, indices, 8)
    ecart = np.mod(phi[1:] - phi[:-1], 2 * np.pi)
    assert np.allclose(ecart, np.pi, atol=1e-9)


# ---------------------------------------------------------------------------
# Entrelacement et séquences de trames
# ---------------------------------------------------------------------------

def test_entrelacement_produit_le_demi_ecart_de_ligne():
    """312,5 lignes par trame en 625 : le demi-écart est ce qui entrelace."""
    norme = obtenir_norme("PAL-BG")
    indices = porteuse.indices_lignes(norme, 6, entrelace=True)
    assert indices.tolist() == [0.0, 312.5, 1.0, 313.5, 2.0, 314.5]


def test_le_motif_ntsc_se_deplace_d_une_image_a_l_autre():
    """En NTSC, la phase s'inverse d'une image à la suivante : les points rampent.

    525 lignes × 227,5 cycles = 119 437,5 cycles par image. La demi-période
    résiduelle fait que l'image n+1 porte le motif de sous-porteuse inversé,
    et qu'il faut quatre trames pour revenir au point de départ.
    """
    norme = obtenir_norme("NTSC-M")
    phi0 = porteuse.phase(norme, porteuse.indices_lignes(norme, 4, numero_image=0), 4)
    phi1 = porteuse.phase(norme, porteuse.indices_lignes(norme, 4, numero_image=1), 4)
    phi2 = porteuse.phase(norme, porteuse.indices_lignes(norme, 4, numero_image=2), 4)

    assert np.allclose(np.mod(phi1 - phi0, 2 * np.pi), np.pi, atol=1e-9)
    assert np.allclose(np.mod(phi2 - phi0, 2 * np.pi), 0.0, atol=1e-9)


# ---------------------------------------------------------------------------
# Commutateurs de ligne
# ---------------------------------------------------------------------------

def test_le_signe_pal_alterne_et_le_burst_le_signale():
    norme = obtenir_norme("PAL-BG")
    indices = porteuse.indices_lignes(norme, 6)
    signes = porteuse.signe_pal(indices)[:, 0]
    assert signes.tolist() == [1.0, -1.0, 1.0, -1.0, 1.0, -1.0]

    bursts = porteuse.phase_burst_pal(indices)
    assert bursts.tolist() == [135.0, 225.0, 135.0, 225.0, 135.0, 225.0]
    # Le burst oscille de ±45° autour de la référence 180°.
    assert np.allclose(np.abs(bursts - 180.0), 45.0)


def test_secam_alterne_les_composantes():
    norme = obtenir_norme("SECAM-L")
    indices = porteuse.indices_lignes(norme, 6)
    rouge = porteuse.secam_ligne_rouge(indices)
    assert rouge.tolist() == [False, True, False, True, False, True]


# ---------------------------------------------------------------------------
# Modulation / démodulation
# ---------------------------------------------------------------------------

def test_la_demodulation_synchrone_retrouve_u_et_v():
    """2·C·sin φ moyenné sur un nombre entier de périodes redonne U ; idem pour V.

    C'est la démonstration élémentaire de la modulation en quadrature : deux
    signaux indépendants tiennent sur une seule porteuse parce que sinus et
    cosinus sont orthogonaux.
    """
    phi = np.linspace(0, 2 * np.pi * 50, 20000, endpoint=False)[None, :]
    u, v = 0.31, -0.17
    chroma = porteuse.moduler_quadrature(u, v, phi)
    u_dem, v_dem = porteuse.demoduler_quadrature(chroma, phi)

    assert np.mean(u_dem) == pytest.approx(u, abs=1e-9)
    assert np.mean(v_dem) == pytest.approx(v, abs=1e-9)


def test_une_erreur_de_phase_fait_tourner_la_teinte():
    """Le péché du NTSC, réduit à sa plus simple expression.

    Si le canal a fait tourner la porteuse de θ, le vecteur (U, V) démodulé
    subit exactement la même rotation : le module (la saturation) est intact,
    l'argument (la teinte) a bougé de θ. Rien ne permet au récepteur de
    distinguer cette rotation d'une vraie couleur — d'où le bouton « Tint ».
    """
    theta = np.deg2rad(20.0)
    phi = np.linspace(0, 2 * np.pi * 50, 20000, endpoint=False)[None, :]
    u, v = 0.31, -0.17

    chroma = porteuse.moduler_quadrature(u, v, phi + theta)
    u_dem, v_dem = porteuse.demoduler_quadrature(chroma, phi)
    u_dem, v_dem = np.mean(u_dem), np.mean(v_dem)

    assert np.hypot(u_dem, v_dem) == pytest.approx(np.hypot(u, v), abs=1e-9)
    ecart = np.arctan2(v_dem, u_dem) - np.arctan2(v, u)
    assert np.rad2deg(np.mod(ecart + np.pi, 2 * np.pi) - np.pi) == pytest.approx(
        20.0, abs=1e-6
    )


def test_le_pal_annule_l_erreur_de_phase_en_moyennant_deux_lignes():
    """La démonstration centrale du PAL, faite sur les nombres.

    Sur une ligne, l'erreur de phase θ donne, après rétablissement du signe :

        U' = U cosθ - s·V sinθ
        V' = V cosθ + s·U sinθ

    où s = ±1 est le signe PAL de la ligne. Comme s change à chaque ligne, les
    termes en sinθ sont opposés d'une ligne à l'autre : leur moyenne est nulle.
    Il ne reste que le facteur cosθ — une simple perte de saturation, à peine
    perceptible là où une dérive de teinte aurait sauté aux yeux.
    """
    theta_deg = 25.0
    theta = np.deg2rad(theta_deg)
    norme = obtenir_norme("PAL-BG")
    indices = porteuse.indices_lignes(norme, 2)
    phi = porteuse.phase(norme, indices, 40000)
    signe = porteuse.signe_pal(indices)

    u, v = 0.28, 0.19
    chroma = porteuse.moduler_quadrature(u, signe * v, phi + theta)
    u_dem, v_dem = porteuse.demoduler_quadrature(chroma, phi)

    # Le récepteur rétablit le signe de V, puis moyenne les deux lignes.
    u_lignes = np.mean(u_dem, axis=1)
    v_lignes = np.mean(v_dem * signe, axis=1)

    u_pal, v_pal = np.mean(u_lignes), np.mean(v_lignes)

    assert u_pal == pytest.approx(u * np.cos(theta), abs=1e-6)
    assert v_pal == pytest.approx(v * np.cos(theta), abs=1e-6)

    # Aucune erreur de teinte : l'argument est rigoureusement conservé.
    assert np.arctan2(v_pal, u_pal) == pytest.approx(np.arctan2(v, u), abs=1e-9)

    # Sans la ligne à retard, chaque ligne porte une erreur de teinte de ±25°,
    # de signes opposés : c'est exactement ce qui produit les barres de Hanover.
    teintes = np.rad2deg(np.arctan2(v_lignes, u_lignes) - np.arctan2(v, u))
    assert teintes[0] == pytest.approx(+theta_deg, abs=1e-4)
    assert teintes[1] == pytest.approx(-theta_deg, abs=1e-4)
