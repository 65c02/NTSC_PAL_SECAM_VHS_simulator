"""
Vérifie les mires, et surtout les trois cartes de test nationales.

Une mire n'est utile que si ce qu'elle prétend mesurer est exact. La
disposition de ces cartes est une reconstruction — c'est dit dans le module —
mais leurs éléments mesurables, eux, ne se reconstruisent pas : un réseau
annoncé à 3,8 MHz doit tomber sur 3,8 MHz, sans quoi la mire ment.
"""

from __future__ import annotations

import numpy as np
import pytest

from tvcolor import mires
from tvcolor.constantes import obtenir_norme

CARTES = ["Mire TDF (France)", "Test Card F (Royaume-Uni)", "Mire NHK (Japon)"]


@pytest.mark.parametrize("nom", sorted(mires.CATALOGUE))
@pytest.mark.parametrize("taille", [(576, 768), (288, 384), (480, 640)])
def test_toutes_les_mires_se_generent(nom, taille):
    """Toute entrée du catalogue doit sortir une image valide, à toute taille.

    Les trois cartes nationales sont dessinées en fractions de la hauteur, et
    ce test les passe en 288 lignes comme en 576 : c'est ce qui garantit
    qu'aucune coordonnée n'a été écrite en pixels au hasard.
    """
    image = mires.obtenir_mire(nom, *taille)
    assert image.shape == (*taille, 3)
    assert np.isfinite(image).all()
    assert 0.0 <= image.min() and image.max() <= 1.0


@pytest.mark.parametrize("nom", CARTES)
def test_les_cartes_ont_du_noir_et_du_blanc_francs(nom):
    """Créneaux de surbalayage et escalier de gris : les deux extrêmes y sont.

    Sans blanc franc, pas de repère de niveau ; sans noir franc, pas de mesure
    du piédestal. Une carte de test qui n'aurait ni l'un ni l'autre ne servirait
    à rien.
    """
    image = mires.obtenir_mire(nom, 576, 768)
    gris = image.mean(axis=-1)
    assert (gris > 0.99).mean() > 0.01
    assert (gris < 0.01).mean() > 0.01


@pytest.mark.parametrize("nom", CARTES)
def test_les_cartes_portent_de_la_couleur(nom):
    """Chacune a ses barres : la saturation doit être bien présente."""
    image = mires.obtenir_mire(nom, 576, 768)
    ecart = image.max(axis=-1) - image.min(axis=-1)
    assert (ecart > 0.3).mean() > 0.02


def _frequence_dominante(bande: np.ndarray, norme) -> float:
    """Fréquence de la raie la plus forte d'un profil horizontal, en hertz.

    L'axe des fréquences se déduit de la durée de ligne active : une image de
    `w` points couvre `duree_ligne_active`, donc le pas fréquentiel vaut
    `1 / duree_ligne_active`.
    """
    profil = bande - bande.mean()
    spectre = np.abs(np.fft.rfft(profil * np.hanning(profil.size)))
    k = int(np.argmax(spectre))
    return k / norme.duree_ligne_active


def test_les_reseaux_de_la_mire_tdf_sont_aux_frequences_annoncees():
    """Le contrôle qui fait la différence entre un instrument et un décor.

    Les quatre réseaux sont annoncés à 1,5 · 2,8 · 3,8 et 4,8 MHz. On les
    remesure par transformée de Fourier sur la bande où ils sont tracés, en
    prenant pour axe des fréquences la seule chose qui compte : la durée de la
    ligne active de la norme.
    """
    norme = obtenir_norme("PAL-BG")
    h, w = 576, 768
    image = mires.obtenir_mire("Mire TDF (France)", h, w)

    ligne = image[int(0.65 * h), :, 0]
    attendues = (1.5e6, 2.8e6, 3.8e6, 4.8e6)
    bornes = np.round(np.linspace(0, w, len(attendues) + 1)).astype(int)

    for k, attendue in enumerate(attendues):
        # On rogne les bords du bloc : la transition d'un réseau au suivant
        # apporte une discontinuité qui n'appartient à aucun des deux.
        a, b = bornes[k] + 8, bornes[k + 1] - 8
        mesuree = _frequence_dominante(ligne[a:b], norme) * w / (b - a)
        assert abs(mesuree - attendue) < 0.15e6, (
            f"réseau {attendue / 1e6:.1f} MHz mesuré à {mesuree / 1e6:.2f}"
        )


def test_le_reseau_de_la_mire_nhk_suit_la_norme():
    """Le réseau unique est calé sur la coupure de luminance de la norme.

    Il doit donc se déplacer d'une norme à l'autre — 4,2 MHz en NTSC, 6,0 en
    SECAM — et c'est bien ce qu'on mesure. Une mire dessinée une fois pour
    toutes n'aurait pas cette propriété.
    """
    h, w = 576, 768
    for code in ("NTSC-M", "SECAM-L"):
        norme = obtenir_norme(code)
        image = mires.mire_nhk(h, w, norme=code)
        ligne = image[int(0.90 * h), int(0.32 * w) : int(0.68 * w), 0]
        largeur = ligne.size
        mesuree = _frequence_dominante(ligne, norme) * w / largeur
        assert abs(mesuree - norme.bande_y) < 0.25e6


def test_le_cercle_est_rond():
    """Sur une trame 4:3 à pixels carrés, un cercle doit être un cercle.

    Le tracer en fraction de LARGEUR l'aurait rendu ovale d'un tiers, et c'est
    exactement le défaut que ce cercle est censé révéler sur un téléviseur mal
    réglé. Une mire qui porte elle-même le défaut ne mesure plus rien.
    """
    h, w = 576, 768
    # Sur la primitive seule : dans une mire complète, le quadrillage et les
    # créneaux sont blancs eux aussi et l'on ne mesurerait plus le cercle.
    image = np.zeros((h, w, 3))
    mires._anneau(image, h / 2.0, w / 2.0, 0.45 * h, 1.0, 1.0)
    blanc = image.mean(axis=-1) > 0.5

    colonnes = np.flatnonzero(blanc[h // 2])
    lignes = np.flatnonzero(blanc[:, w // 2])
    demi_largeur = (colonnes.max() - colonnes.min()) / 2.0
    demi_hauteur = (lignes.max() - lignes.min()) / 2.0
    assert abs(demi_largeur - demi_hauteur) < 0.02 * demi_hauteur
    assert abs(demi_hauteur - 0.45 * h) < 2.0


def test_alphabet_incomplet_le_dit():
    image = np.zeros((40, 60, 3))
    with pytest.raises(KeyError, match="alphabet"):
        mires._texte(image, "ZUT", 4, 4, 2, 1.0)
