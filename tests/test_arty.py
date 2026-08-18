"""
Vérifie Arty : la synthèse, la base de temps, et la géométrie qui en découle.

Le critère de ce module est particulier et vaut d'être posé. Ce qu'on y fabrique
est de l'art, mais **le lien entre le son et l'image ne l'est pas** : une onde de
fréquence `f` ajoutée au composite donne `f / f_ligne` barres par ligne et une
avance de phase de `2π f / f_ligne` d'une ligne à la suivante. C'est calculable
avant d'être tracé, et c'est ce que ces tests contrôlent — la prédiction contre
la mesure, sur l'image rendue.
"""

from __future__ import annotations

import numpy as np
import pytest

from arty.dx7 import ALGORITHMES, Enveloppe, Operateur, Voix, obtenir_algorithme
from arty.injection import ParametresArty, base_de_temps, motif, perturbation, rendre
from tvcolor.constantes import obtenir_norme

NORME = obtenir_norme("PAL-BG")


def _voix(fondamentale: float, algorithme: str = "additif", **kw) -> Voix:
    """Une voix à un seul opérateur actif : une sinusoïde pure."""
    operateurs = [Operateur(rapport=1.0, niveau=1.0)] + [
        Operateur(rapport=1.0, niveau=0.0) for _ in range(5)
    ]
    return Voix(
        fondamentale=fondamentale, algorithme=algorithme,
        operateurs=tuple(operateurs), **kw
    )


# ---------------------------------------------------------------------------
# La base de temps
# ---------------------------------------------------------------------------

def test_la_base_de_temps_avance_d_une_periode_ligne_exactement():
    """Le composite est un signal à UNE dimension, plié en deux.

    Ce qui doit être exact, c'est l'écart d'une ligne à la suivante : une
    période ligne, sans quoi tous les motifs dériveraient.
    """
    temps = base_de_temps(NORME, 8)
    for ligne in range(7):
        ecart = temps[ligne + 1, 0] - temps[ligne, 0]
        assert abs(ecart - 1.0 / NORME.f_ligne) < 1e-18


def test_la_ligne_ne_contient_pas_un_nombre_entier_d_echantillons():
    """Et c'est heureux — c'est même toute la raison d'être du PAL.

    À quatre fois la sous-porteuse, une ligne de 625 lignes vaut **1135,0064**
    périodes d'échantillonnage, et non 1135 tout rond. La grille n'est PAS
    verrouillée sur la ligne, et c'est exactement ce qui donne à la
    sous-porteuse son avance de 270,576° par ligne — le décalage en +1/625 du
    chapitre 8, qui remonte jusqu'ici.

    Le tableau du composite, lui, a bien 1135 colonnes : c'est un arrondi de
    rangement. Le dernier échantillon d'une ligne et le premier de la suivante
    sont donc séparés de 1,0064 période et non d'une exactement. Quatre
    dixièmes de picoseconde, qu'on mesure plutôt que de les supposer nuls — et
    qui suffisent, sur 576 lignes, à faire tourner la sous-porteuse.
    """
    exact = NORME.f_echantillonnage / NORME.f_ligne
    assert abs(exact - 1135.0064) < 1e-3
    assert NORME.echantillons_ligne_totale == 1135

    temps = base_de_temps(NORME, 4)
    saut = temps[1, 0] - temps[0, -1]
    pas = 1.0 / NORME.f_echantillonnage
    assert abs(saut / pas - 1.0064) < 1e-3


def test_l_instant_decale_toute_la_trame():
    a = base_de_temps(NORME, 4, instant=0.0)
    b = base_de_temps(NORME, 4, instant=0.02)
    assert np.abs((b - a) - 0.02).max() < 1e-15


# ---------------------------------------------------------------------------
# Les enveloppes
# ---------------------------------------------------------------------------

def test_l_enveloppe_plate_ne_module_rien():
    temps = np.linspace(0.0, 0.02, 500)
    assert np.abs(Enveloppe.plate().evaluer(temps) - 1.0).max() < 1e-12


def test_l_enveloppe_suit_ses_paliers():
    """Quatre segments linéaires, et le dernier niveau se tient après la fin."""
    enveloppe = Enveloppe((1.0, 0.5, 0.5, 0.0), (0.002, 0.002, 0.002, 0.002))
    assert abs(float(enveloppe.evaluer(np.array([0.0]))[0])) < 1e-9
    assert abs(float(enveloppe.evaluer(np.array([0.002]))[0]) - 1.0) < 1e-9
    assert abs(float(enveloppe.evaluer(np.array([0.004]))[0]) - 0.5) < 1e-9
    assert abs(float(enveloppe.evaluer(np.array([0.008]))[0])) < 1e-9
    # Au-delà, on tient le dernier niveau plutôt que de redéclencher.
    assert abs(float(enveloppe.evaluer(np.array([0.05]))[0])) < 1e-9


# ---------------------------------------------------------------------------
# La synthèse
# ---------------------------------------------------------------------------

def test_un_operateur_seul_est_une_sinusoide_pure():
    voix = _voix(2_000.0)
    temps = np.arange(48_000) / 48_000.0
    onde = voix.rendre(temps)

    spectre = np.abs(np.fft.rfft(onde * np.hanning(onde.size)))
    frequences = np.fft.rfftfreq(onde.size, 1.0 / 48_000.0)
    pic = frequences[int(np.argmax(spectre))]
    assert abs(pic - 2_000.0) < 3.0

    # Et rien d'autre : la seconde raie est trente décibels plus bas.
    autour = np.abs(frequences - 2_000.0) > 60.0
    assert spectre[autour].max() < 0.05 * spectre.max()


def test_l_index_de_modulation_ouvre_l_eventail_des_harmoniques():
    """La loi de Bessel, mesurée : au-delà de β + 1, les raies s'effondrent.

    C'est tout l'intérêt de la modulation de fréquence, et c'est ce qui rend
    l'outil intéressant : un seul bouton fait passer d'une barre franche à une
    texture fine, parce qu'il fait passer de deux raies à vingt.
    """
    temps = np.arange(48_000) / 48_000.0
    largeurs = []
    for index in (0.5, 2.0, 6.0):
        voix = Voix(
            fondamentale=1_000.0, algorithme="chaine", index=index,
            operateurs=tuple([Operateur(rapport=1.0), Operateur(rapport=1.0)]
                             + [Operateur(niveau=0.0) for _ in range(4)]),
        )
        onde = voix.rendre(temps)
        spectre = np.abs(np.fft.rfft(onde * np.hanning(onde.size)))
        frequences = np.fft.rfftfreq(onde.size, 1.0 / 48_000.0)
        significatif = spectre > 0.02 * spectre.max()
        largeurs.append(float(frequences[significatif].max()))

    assert largeurs[0] < largeurs[1] < largeurs[2]
    # β = 6 : la dernière raie notable est vers (β + 1) fois la modulante.
    assert 5_000.0 < largeurs[2] < 12_000.0


def test_la_retroaction_enrichit_le_spectre():
    temps = np.arange(48_000) / 48_000.0

    def harmoniques(retroaction):
        voix = _voix(1_000.0)
        voix = voix.avec_operateur(0, retroaction=retroaction)
        onde = voix.rendre(temps)
        spectre = np.abs(np.fft.rfft(onde * np.hanning(onde.size)))
        return int((spectre > 0.02 * spectre.max()).sum())

    assert harmoniques(4.0) > 3 * harmoniques(0.0)


@pytest.mark.parametrize("code", sorted(ALGORITHMES))
def test_chaque_algorithme_produit_une_onde_bornee(code):
    """Aucun agencement ne doit diverger, rétroaction comprise."""
    voix = Voix(
        fondamentale=800.0, algorithme=code, index=4.0,
        operateurs=tuple(Operateur(rapport=1.0 + rang, retroaction=2.0 if rang == 5 else 0.0)
                         for rang in range(6)),
    )
    onde = voix.rendre(np.arange(4_000) / 48_000.0)
    assert np.isfinite(onde).all()
    assert np.abs(onde).max() <= 1.01


def test_l_ordre_d_evaluation_respecte_les_dependances():
    """Un opérateur doit être évalué après ceux qui le modulent."""
    algo = obtenir_algorithme("chaine")
    rangs = algo.rangs()
    place = {op: rang for rang, op in enumerate(rangs)}
    for cible in range(6):
        for source in range(6):
            if algo.matrice[cible, source] and source != cible:
                assert place[source] < place[cible]


def test_algorithme_inconnu_le_dit():
    with pytest.raises(KeyError, match="algorithme inconnu"):
        obtenir_algorithme("dx7-numero-7")


# ---------------------------------------------------------------------------
# La prédiction du motif
# ---------------------------------------------------------------------------

def test_la_prediction_annonce_les_trois_cas():
    entier = motif(8.0 * NORME.f_ligne, NORME)
    assert abs(entier["cycles_par_ligne"] - 8.0) < 1e-9
    assert entier["avance_par_ligne"] < 1.0
    assert "immobiles" in entier["allure"]

    demi = motif(8.5 * NORME.f_ligne, NORME)
    assert abs(demi["avance_par_ligne"] - 180.0) < 1.0
    assert "damier" in demi["allure"]

    couleur = motif(NORME.f_sc, NORME)
    assert "COULEUR" in couleur["allure"]


# ---------------------------------------------------------------------------
# La géométrie, prédite puis mesurée sur l'image
# ---------------------------------------------------------------------------

def _rendu(frequence: float, niveau: float = 0.25, **kw):
    params = ParametresArty(
        taille=(288, 384), niveau=niveau,
        voix=_voix(frequence), mire="Rampe de luminance", **kw
    )
    return rendre(params)


def test_une_frequence_multiple_de_la_ligne_donne_des_barres_immobiles():
    """La prédiction dit 0° d'avance par ligne : l'image doit être invariante.

    On mesure la différence entre deux lignes voisines de la PERTURBATION, sur
    une mire uniforme verticalement. Elle doit être nulle à la précision du
    calcul, et non « petite ».
    """
    params = ParametresArty(taille=(96, 128), voix=_voix(8.0 * NORME.f_ligne))
    onde = perturbation(params, 96)
    assert np.abs(onde[10] - onde[11]).max() < 1e-9


def test_une_frequence_demi_entiere_donne_un_damier():
    """180° d'avance : la ligne suivante est l'exacte opposée."""
    params = ParametresArty(taille=(96, 128), voix=_voix(8.5 * NORME.f_ligne))
    onde = perturbation(params, 96)
    assert np.abs(onde[10] + onde[11]).max() < 1e-9
    assert np.abs(onde[10]).max() > 0.01


def test_le_nombre_de_barres_est_celui_qu_on_annonce():
    """On compte les alternances sur une ligne, et on les compare à f / f_ligne."""
    for cycles in (4.0, 12.0, 30.0):
        params = ParametresArty(taille=(96, 128), voix=_voix(cycles * NORME.f_ligne))
        ligne = perturbation(params, 8)[0]
        changements = int(np.sum(np.diff(np.signbit(ligne))))
        assert abs(changements / 2.0 - cycles) <= 1.0


def test_une_onde_pres_de_la_sous_porteuse_fabrique_de_la_couleur():
    """Le décodeur ne peut pas distinguer l'intrus de la chrominance.

    C'est le cross-color du chapitre 10, provoqué exprès : on injecte une onde
    à la fréquence de la sous-porteuse sur une mire en niveaux de gris, et il en
    sort de la couleur. Rien ne l'a peinte — le démodulateur a simplement fait
    son travail sur ce qu'on lui a donné.
    """
    def saturation(frequence):
        resultat = _rendu(frequence, niveau=0.20)
        image = resultat.finale
        return float(np.mean(image.max(axis=-1) - image.min(axis=-1)))

    loin = saturation(0.6e6)
    bord = saturation(NORME.f_sc - 0.3e6)
    dessus = saturation(NORME.f_sc)

    # Sous la bande de chrominance il n'en sort RIEN : le peigne fait son
    # travail, et ce qui reste est le bruit de la virgule flottante. Comparer
    # « quatre fois plus » à un tel plancher ne prouverait rien — on exige donc
    # les deux bouts séparément.
    assert loin < 1e-9
    assert bord > 0.01
    assert dessus > 0.05


def test_le_niveau_zero_rend_l_image_intacte():
    """Le contrôle de transparence, comme partout ailleurs dans ce projet."""
    from tvcolor import mires
    from tvcolor.pipeline import Parametres, encoder_decoder

    source = mires.obtenir_mire("Rampe de luminance", 96, 128)
    nu = encoder_decoder(source, Parametres(norme="PAL-BG", taille_sortie=(96, 128)))
    avec = rendre(ParametresArty(
        taille=(96, 128), niveau=0.0, mire="Rampe de luminance"
    ))
    assert np.abs(avec.finale - nu.finale).max() < 1e-12


def test_une_perturbation_mal_dimensionnee_est_refusee():
    from tvcolor import mires
    from tvcolor.pipeline import Parametres, encoder_decoder

    params = Parametres(norme="PAL-BG", taille_sortie=(96, 128))
    params.perturbation = np.zeros((10, 10))
    with pytest.raises(ValueError, match="perturbation de forme"):
        encoder_decoder(mires.obtenir_mire("Rampe de luminance", 96, 128), params)


# ---------------------------------------------------------------------------
# Ce que l'outil ne touche pas
# ---------------------------------------------------------------------------

def test_le_son_n_est_pas_altere():
    """Arty n'approche pas la voie audio, et cela se vérifie.

    La voie son d'un téléviseur a sa propre porteuse, plusieurs mégahertz plus
    haut ; ce qu'on injecte ici va dans le composite vidéo. On fait donc passer
    le même signal par la chaîne son avant et après un rendu Arty à niveau
    maximal, et l'on exige le bit près — ce qui garantit du même coup qu'aucun
    état global ne fuit d'un module à l'autre.
    """
    from tvcolor.son import ParametresSon, transmettre

    entree = 0.4 * np.sin(2.0 * np.pi * 1_000.0 * np.arange(24_000) / 48_000.0)
    reglages = ParametresSon(rapport_signal_bruit=40.0)

    avant = transmettre(entree, 48_000, NORME, reglages)
    rendre(ParametresArty(taille=(96, 128), niveau=0.5))
    apres = transmettre(entree, 48_000, NORME, reglages)

    assert np.array_equal(avant, apres)
