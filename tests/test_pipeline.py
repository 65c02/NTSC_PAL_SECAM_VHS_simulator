"""
Vérifie la chaîne complète, et surtout que chaque artefact célèbre apparaît
bien tout seul.

Ces tests sont la garantie principale de l'honnêteté du simulateur : si un
artefact devait être ajouté à la main, il ne pourrait pas se manifester ici
comme une conséquence des seuls réglages normatifs.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import find_peaks

from tvcolor import matrices as mx
from tvcolor import mesures, mires
from tvcolor.canal import ParametresCanal
from tvcolor.constantes import obtenir_norme
from tvcolor.decodeur import ParametresDecodage
from tvcolor.encodeur import ParametresEncodage
from tvcolor.pipeline import Parametres, encoder_decoder


def _geometrie_native(code: str):
    n = obtenir_norme(code)
    return n.lignes_actives, n.echantillons_par_ligne


# ---------------------------------------------------------------------------
# Transparence : sans limitation ni défaut, la chaîne ne doit rien changer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", ["NTSC-M", "PAL-BG"])
def test_chaine_transparente(code):
    """Bandes illimitées, décodeur parfait, canal idéal → l'image est intacte.

    C'est le test le plus important du lot. Il prouve que tout écart observé
    ailleurs vient d'un phénomène simulé, et non d'une approximation cachée
    dans le matriçage, le gamma ou le rééchantillonnage.

    L'image d'entrée est à la géométrie native de la norme, pour qu'aucun
    rééchantillonnage n'intervienne.
    """
    h, w = _geometrie_native(code)
    rng = np.random.default_rng(7)
    image = rng.random((h, w, 3))

    params = Parametres(
        norme=code,
        encodage=ParametresEncodage(bande_y=1e9, bande_c1=1e9, bande_c2=1e9),
        decodage=ParametresDecodage(separateur="parfait"),
        taille_sortie=(h, w),
    )
    resultat = encoder_decoder(image, params)
    assert np.max(np.abs(resultat.finale - resultat.source)) < 1e-6


@pytest.mark.parametrize("code", ["NTSC-M", "PAL-BG"])
def test_ntsc_et_pal_n_emettent_rien_sur_une_image_grise(code):
    """Compatibilité noir et blanc : pas de chrominance, donc pas de sous-porteuse.

    C'était la contrainte fondatrice de 1953. La modulation en quadrature est
    à **porteuse supprimée** : quand U = V = 0, le signal de chrominance est
    identiquement nul. Un récepteur monochrome ne voit donc rien de
    particulier sur une émission couleur, et une image monochrome ne colore
    pas un récepteur couleur.
    """
    h, w = _geometrie_native(code)
    gris = np.repeat(np.linspace(0.05, 0.95, w)[None, :, None], h, 0).repeat(3, 2)

    resultat = encoder_decoder(gris, Parametres(norme=code, taille_sortie=(h, w)))

    assert np.max(np.abs(resultat.signal.ref_chroma)) < 1e-9
    u, v = mesures.uv_de_image(resultat.finale)
    assert np.max(np.hypot(u, v)) < 0.02


def test_secam_emet_sa_sous_porteuse_meme_sur_du_gris():
    """La faiblesse structurelle du SECAM : la porteuse ne s'éteint jamais.

    En modulation de fréquence, l'information est portée par la fréquence, pas
    par l'amplitude — il faut donc émettre en permanence, y compris sur une
    image parfaitement grise, où la fréquence reste simplement à sa valeur de
    repos. Contrairement au NTSC et au PAL, le SECAM n'est donc **pas**
    parfaitement compatible avec le noir et blanc : un motif de sous-porteuse
    subsiste toujours dans l'image.

    C'est précisément le rôle du filtre cloche que d'atténuer ce résidu au
    repos, et le test vérifie qu'il fait son travail : la porteuse est bien
    présente, mais l'image décodée reste grise.
    """
    h, w = _geometrie_native("SECAM-L")

    def amplitude_sous_porteuse(image):
        """Amplitude crête de la sous-porteuse, loin des bords de ligne."""
        r = encoder_decoder(image, Parametres(norme="SECAM-L", taille_sortie=(h, w)))
        chroma = r.signal.partie_active(r.signal.ref_chroma)
        return float(np.abs(chroma[100:-100, 100:-100]).max()), r

    gris = np.repeat(np.linspace(0.05, 0.95, w)[None, :, None], h, 0).repeat(3, 2)
    au_repos, resultat = amplitude_sous_porteuse(gris)
    a_pleine_excursion, _ = amplitude_sous_porteuse(np.tile([0.75, 0.75, 0.0], (h, w, 1)))

    # La sous-porteuse est bien là, et pas qu'un peu.
    assert au_repos > 0.1

    # Le filtre cloche l'a néanmoins ramenée à moins de la moitié de son
    # amplitude à pleine excursion : à la fréquence de repos son gain vaut
    # environ 1,2 contre 3,4 à 4,2 aux extrémités de l'excursion.
    assert au_repos < 0.5 * a_pleine_excursion

    # Et malgré cette porteuse permanente, le décodage restitue bien du gris.
    u, v = mesures.uv_de_image(resultat.finale)
    assert np.mean(np.hypot(u, v)) < 0.01


# ---------------------------------------------------------------------------
# L'entrelacement spectral
# ---------------------------------------------------------------------------

def test_entrelacement_spectral_des_peignes_luma_et_chroma():
    """La démonstration centrale : luma sur les entiers, chroma sur les demi-entiers.

    Le spectre du signal composite est analysé en multiples de la fréquence
    ligne. Dans une zone où seule la luminance est présente, les raies tombent
    sur des entiers. Autour de la sous-porteuse, elles tombent au milieu, sur
    des demi-entiers — exactement dans les creux laissés par la luminance.

    C'est cette propriété, et elle seule, qui permet de faire tenir un signal
    couleur dans un canal déjà entièrement occupé par le noir et blanc.
    """
    resultat = encoder_decoder(
        mires.barres_couleur(288, 384), Parametres(norme="NTSC-M")
    )
    f, db = mesures.spectre_raster(resultat.composite_emis, resultat.norme, f_max=4.2e6)

    def raies(bas, haut, seuil):
        zone = (f > bas) & (f < haut)
        fz, dz = f[zone], db[zone]
        pics, _ = find_peaks(dz, height=dz.max() - seuil, distance=5)
        return fz[pics]

    # Zone de luminance pure (loin de la sous-porteuse) : partie
    # fractionnaire nulle.
    luma = raies(50.0, 56.0, 30.0)
    assert len(luma) >= 4
    assert np.allclose(np.mod(luma, 1.0), 0.0, atol=0.06)

    # Zone de la sous-porteuse (227,5 f_H) : partie fractionnaire 1/2.
    chroma = raies(224.0, 231.0, 35.0)
    assert len(chroma) >= 4
    assert np.allclose(np.mod(chroma, 1.0), 0.5, atol=0.06)


# ---------------------------------------------------------------------------
# Le comportement de chaque norme face à l'erreur de phase
# ---------------------------------------------------------------------------

def _teinte_et_saturation(resultat, fraction_x=0.71):
    """Teinte et saturation moyennes de la barre rouge, lues avant écrêtage."""
    u, v = resultat.decodee.chroma1, resultat.decodee.chroma2
    if resultat.norme.famille == "SECAM":
        u, v = mx.drdb_vers_uv(v, u)
    x = u.shape[1]
    zone = (slice(80, -80), slice(int(x * fraction_x), int(x * fraction_x) + 12))
    uu, vv = u[zone].mean(), v[zone].mean()
    return np.rad2deg(np.arctan2(vv, uu)), float(np.hypot(uu, vv))


def test_reponse_des_trois_normes_a_la_phase_differentielle():
    """Le cœur de la comparaison entre les trois systèmes.

    Un seul et même canal, dégradé de la même manière, est appliqué aux trois
    normes. La différence de comportement ne vient donc que de la façon dont
    chacune code la couleur.

    * NTSC  : la teinte tourne. C'est le défaut qui a valu au système son
      surnom de *Never Twice the Same Color*.
    * PAL-D : la teinte est intacte, la saturation baisse un peu. La ligne à
      retard a converti une erreur voyante en une erreur imperceptible.
    * SECAM : rien ne bouge. Un retard constant ne change pas une fréquence.
    """
    mire = mires.barres_couleur(288, 384)
    canal = ParametresCanal(phase_differentielle=40.0)

    reference = encoder_decoder(mire, Parametres(norme="PAL-BG"))
    teinte_ref, sat_ref = _teinte_et_saturation(reference)

    resultats = {
        code: _teinte_et_saturation(
            encoder_decoder(mire, Parametres(norme=code, canal=canal))
        )
        for code in ("NTSC-M", "PAL-BG", "SECAM-L")
    }

    # NTSC : erreur de teinte franche, plusieurs degrés.
    assert abs(resultats["NTSC-M"][0] - teinte_ref) > 5.0

    # PAL : erreur de teinte annulée par la ligne à retard…
    assert abs(resultats["PAL-BG"][0] - teinte_ref) < 1.0
    # … au prix d'une légère perte de saturation.
    assert resultats["PAL-BG"][1] < sat_ref

    # SECAM : insensible, teinte ET saturation.
    assert abs(resultats["SECAM-L"][0] - teinte_ref) < 1.0
    assert resultats["SECAM-L"][1] == pytest.approx(sat_ref, rel=0.03)


def test_les_barres_de_hanover_apparaissent_sans_ligne_a_retard():
    """PAL sans ligne à retard : l'erreur de teinte alterne d'une ligne à l'autre.

    C'est ce striage horizontal des couleurs qu'on appelle « barres de
    Hanover », du nom de la ville où Walter Bruch a mis le PAL au point.
    """
    mire = mires.barres_couleur(288, 384)
    canal = ParametresCanal(phase_differentielle=60.0)

    def striage(ligne_a_retard):
        r = encoder_decoder(
            mire,
            Parametres(
                norme="PAL-BG",
                canal=canal,
                decodage=ParametresDecodage(ligne_a_retard=ligne_a_retard),
            ),
        )
        u, v = r.decodee.chroma1, r.decodee.chroma2
        x = u.shape[1]
        colonnes = slice(int(x * 0.71), int(x * 0.71) + 12)
        teintes = np.rad2deg(
            np.arctan2(v[80:-80, colonnes].mean(1), u[80:-80, colonnes].mean(1))
        )
        return float(np.abs(np.diff(teintes)).mean())

    assert striage(ligne_a_retard=False) > 10.0
    assert striage(ligne_a_retard=True) < 1.0


def test_secam_ignore_le_gain_differentiel():
    """Le limiteur du discriminateur FM efface toute information d'amplitude."""
    mire = mires.barres_couleur(288, 384)
    canal = ParametresCanal(gain_differentiel=0.5)

    for code, tolerance in (("SECAM-L", 0.03), ("PAL-BG", None)):
        sans = _teinte_et_saturation(encoder_decoder(mire, Parametres(norme=code)))[1]
        avec = _teinte_et_saturation(
            encoder_decoder(mire, Parametres(norme=code, canal=canal))
        )[1]
        if tolerance is not None:
            assert avec == pytest.approx(sans, rel=tolerance), code
        else:
            assert abs(avec / sans - 1.0) > 0.05, code


# ---------------------------------------------------------------------------
# Les artefacts de séparation Y/C
# ---------------------------------------------------------------------------

def test_le_dot_crawl_apparait_et_le_peigne_le_deplace():
    """Le peigne ne supprime pas le dot crawl : il le déplace.

    * Réjecteur : la chrominance résiduelle fuit dans la luma sur les
      contours **verticaux** des aplats colorés.
    * Peigne : ces contours-là sont propres, mais l'hypothèse « la luma ne
      change pas d'une ligne à l'autre » s'effondre sur les contours
      **horizontaux**, où le motif réapparaît.
    """
    mire = mires.piege_dot_crawl(288, 384)
    hauteur, largeur = 480, 753

    def luminance(separateur):
        r = encoder_decoder(
            mire,
            Parametres(
                norme="NTSC-M",
                decodage=ParametresDecodage(separateur=separateur),
                taille_sortie=(hauteur, largeur),
            ),
        )
        return mx.luma(r.finale)

    # Le pavé rouge occupe les rangées 15–85 % de la demi-hauteur et les
    # colonnes 12–88 % du premier tiers. On mesure l'**alternance** — la
    # variation d'un échantillon au suivant — dans deux zones où l'image
    # source est parfaitement uniforme dans la direction considérée. Tout ce
    # qui bouge y est donc un artefact et rien d'autre.
    bord_vertical = (slice(60, 180), slice(212, 232))     # sur le flanc droit
    bord_horizontal = (slice(30, 44), slice(60, 190))     # sur l'arête du haut

    mesures_ = {}
    for separateur in ("notch", "peigne", "parfait"):
        y = luminance(separateur)
        mesures_[separateur] = (
            float(np.abs(np.diff(y[bord_vertical], axis=0)).mean()),   # ligne à ligne
            float(np.abs(np.diff(y[bord_horizontal], axis=1)).mean()), # point à point
        )

    # Un séparateur parfait n'a ni l'un ni l'autre.
    assert mesures_["parfait"][0] < 1e-3
    assert mesures_["parfait"][1] < 1e-3

    # Le réjecteur laisse fuir la chrominance sur les contours verticaux…
    assert mesures_["notch"][0] > 0.02
    assert mesures_["notch"][0] > 10.0 * mesures_["peigne"][0]

    # … et le peigne, lui, déplace l'artefact sur les contours horizontaux.
    assert mesures_["peigne"][1] > 0.01
    assert mesures_["peigne"][1] > 10.0 * mesures_["notch"][1]


def test_le_cross_color_colore_une_mire_en_noir_et_blanc():
    """Une mire strictement monochrome ressort colorée : c'est le cross-color.

    Le balayage de fréquence contient des détails de luminance dont la
    fréquence spatiale coïncide avec la sous-porteuse. Le décodeur n'a aucun
    moyen de savoir qu'il s'agit de luminance : il les interprète en couleur.
    """
    mire = mires.balayage_frequentiel(288, 384, "NTSC-M")
    assert np.allclose(mire[..., 0], mire[..., 1])   # bien monochrome au départ

    resultat = encoder_decoder(
        mire,
        Parametres(
            norme="NTSC-M",
            decodage=ParametresDecodage(separateur="notch"),
            taille_sortie=(300, 753),
        ),
    )
    u, v = mesures.uv_de_image(resultat.finale)
    saturation = np.hypot(u, v)
    assert saturation.max() > 0.15
    assert np.mean(saturation > 0.03) > 0.10


# ---------------------------------------------------------------------------
# Le coût permanent : bande passante et résolution
# ---------------------------------------------------------------------------

def test_la_chrominance_bave_horizontalement():
    """Une transition franche de couleur s'étale sur plusieurs dizaines de points.

    Conséquence directe de la bande de chrominance : 1,3 MHz sur une ligne
    active de 52 µs, cela ne fait que 68 alternances. La couleur ne peut pas
    changer plus vite que cela, même quand la luminance, elle, le peut.
    """
    # Mire produite d'emblée à la géométrie native de la norme : aucun
    # rééchantillonnage ne vient brouiller la mesure.
    hauteur, largeur = _geometrie_native("PAL-BG")
    mire = mires.barres_couleur(hauteur, largeur)
    resultat = encoder_decoder(
        mire, Parametres(norme="PAL-BG", taille_sortie=(hauteur, largeur))
    )

    u, _ = mesures.uv_de_image(resultat.finale)
    luma = mx.luma(resultat.finale)

    def largeur_de_transition(profil):
        """Nombre d'échantillons entre 10 % et 90 % de la transition."""
        profil = np.asarray(profil, dtype=float)
        depart, arrivee = profil[0], profil[-1]
        normalise = (profil - depart) / (arrivee - depart)
        return int(np.sum((normalise > 0.1) & (normalise < 0.9)))

    # Transition blanc → jaune : la luminance chute de 1,00 à 0,70 et la
    # chrominance passe de zéro à sa pleine valeur. Les deux signaux
    # franchissent donc une marche nette au même endroit, ce qui permet de
    # comparer directement leurs temps de montée.
    milieu = hauteur // 2
    frontiere = largeur // 8
    fenetre = slice(frontiere - 45, frontiere + 45)

    transition_chroma = largeur_de_transition(u[milieu, fenetre])
    transition_luma = largeur_de_transition(luma[milieu, fenetre])

    # 0,35/B donne un temps de montée de 269 ns pour 1,3 MHz de chrominance
    # contre 70 ns pour 5 MHz de luminance : un rapport proche de 4.
    assert transition_chroma >= 4
    assert transition_chroma > 2 * transition_luma


@pytest.mark.parametrize(
    "code,ligne_a_retard,attendu",
    [
        ("NTSC-M", True, 480.0),
        ("PAL-BG", True, 288.0),
        ("PAL-BG", False, 576.0),
        ("SECAM-L", True, 288.0),
    ],
)
def test_resolution_chromatique_verticale(code, ligne_a_retard, attendu):
    """PAL-D et SECAM paient tous deux leur robustesse en résolution verticale."""
    norme = obtenir_norme(code)
    assert mesures.resolution_verticale_chroma(norme, ligne_a_retard) == attendu


def test_bilan_de_non_constant_luminance():
    """Sur un bleu saturé, la voie luma ne transporte presque rien.

    Y' = 0,114 pour du bleu pur ; élevé à la puissance γ = 2,2, cela ne fait
    plus que 0,0075 de luminance, alors que la couleur en vaut 0,114. Plus de
    90 % de la luminance du bleu voyage donc dans la chrominance — que l'on
    filtre à 1,3 MHz. D'où des bleus saturés systématiquement mous.
    """
    bleu = np.zeros((4, 4, 3))
    bleu[..., 2] = 1.0
    bilan = mesures.bilan_luminance(bleu, gamma=2.2)
    assert bilan["fraction_portee"].mean() < 0.10

    gris = np.full((4, 4, 3), 0.5)
    bilan_gris = mesures.bilan_luminance(gris, gamma=2.2)
    assert bilan_gris["fraction_portee"] == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Piédestal
# ---------------------------------------------------------------------------

def test_le_piedestal_remonte_le_niveau_de_noir():
    """Le setup de 7,5 IRE du NTSC-M place le noir au-dessus de la suppression."""
    noir = np.zeros((100, 100, 3))
    avec = encoder_decoder(noir, Parametres(norme="NTSC-M"))
    sans = encoder_decoder(noir, Parametres(norme="NTSC-J"))

    assert avec.composite_emis.mean() == pytest.approx(0.075, abs=1e-3)
    assert sans.composite_emis.mean() == pytest.approx(0.0, abs=1e-3)


# ---------------------------------------------------------------------------
# Métriques
# ---------------------------------------------------------------------------

def test_le_bilan_se_calcule_sur_les_trois_normes():
    mire = mires.barres_couleur(144, 192)
    for code in ("NTSC-M", "PAL-BG", "SECAM-L"):
        bilan = mesures.evaluer(encoder_decoder(mire, Parametres(norme=code)))
        assert bilan.delta_e_moyen >= 0.0
        assert bilan.carte_delta_e.shape == mire.shape[:2]
        assert isinstance(bilan.resume(), str)
