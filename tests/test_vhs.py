"""
Vérifie le magnétoscope.

Deux catégories de tests, et la seconde est la plus utile : celle qui contrôle
que les défauts sont bien ceux d'une cassette, et non ceux du simulateur. Trois
contresens physiques ont été trouvés par la mesure pendant l'écriture de ce
module, et chacun a laissé ici le test qui l'aurait attrapé.
"""

from __future__ import annotations

import numpy as np
import pytest

from tvcolor import mesures, mires, vhs
from tvcolor.constantes import obtenir_norme
from tvcolor.pipeline import Parametres, encoder_decoder

MIRE = mires.barres_couleur(144, 192)


def rendre(**reglages):
    params = Parametres(norme="PAL-BG", taille_sortie=MIRE.shape[:2])
    if reglages:
        params.vhs = vhs.ParametresVHS(**reglages)
    return encoder_decoder(MIRE, params)


PROPRE = dict(
    actif=True, generation=1, usure=0.0, gigue=0.0, abandons=0.0,
    commutation_tetes=False, bruit_luma=0.0, bruit_chroma=0.0, depassement=0.0,
)
"""Un magnétoscope dont tous les défauts sont éteints. Il ne reste que le
color-under lui-même — c'est-à-dire l'essentiel."""


# ---------------------------------------------------------------------------
# Le format
# ---------------------------------------------------------------------------

def test_la_porteuse_transposee_est_calee_sur_la_frequence_ligne():
    """40,125 fois la fréquence ligne en 625 lignes, 40 fois en 525.

    Le quart de multiple n'est pas une coquetterie : comme pour la
    sous-porteuse couleur, un rapport non entier fait que le motif résiduel
    s'inverse d'une ligne à l'autre au lieu de s'y superposer.
    """
    pal = obtenir_norme("PAL-BG")
    ntsc = obtenir_norme("NTSC-M")
    assert vhs.sous_porteuse_transposee(pal) == pytest.approx(626_953.125)
    assert vhs.sous_porteuse_transposee(ntsc) == pytest.approx(629_370.6, abs=1.0)
    assert vhs.sous_porteuse_transposee(pal) / pal.f_ligne == pytest.approx(40.125)
    assert vhs.sous_porteuse_transposee(ntsc) / ntsc.f_ligne == pytest.approx(40.0)


def test_la_couleur_est_bien_plus_grossiere_que_la_luminance():
    """Le trait qui définit le VHS.

    240 lignes de définition en luminance, une trentaine en chrominance : un
    facteur huit. C'est la conséquence directe des 400 kHz que la porteuse
    transposée laisse à la couleur, contre 3 MHz pour la luminance.
    """
    norme = obtenir_norme("PAL-BG")
    params = vhs.ParametresVHS(actif=True, usure=0.0)
    luma, chroma = params.bandes()
    assert luma / chroma > 6.0
    assert 20.0 < vhs.resolution_chroma_lignes(norme, params) < 60.0


@pytest.mark.parametrize("vitesse,attendue", [("SP", 3.0e6), ("LP", 2.6e6), ("EP", 2.0e6)])
def test_ralentir_la_bande_coute_de_la_definition(vitesse, attendue):
    """Trois fois plus de durée sur la même cassette, un tiers de définition en
    moins : la vitesse relative tête/bande décide de la fréquence maximale."""
    params = vhs.ParametresVHS(actif=True, vitesse=vitesse, usure=0.0)
    assert params.bandes()[0] == pytest.approx(attendue)


def test_les_generations_se_cumulent():
    """Une copie de copie repasse par toute la chaîne."""
    une = vhs.ParametresVHS(actif=True, generation=1, usure=0.0).bandes()
    trois = vhs.ParametresVHS(actif=True, generation=3, usure=0.0).bandes()
    assert trois[0] < une[0]
    assert trois[1] < une[1]


# ---------------------------------------------------------------------------
# Le passage, et ce qu'il doit et ne doit PAS faire
# ---------------------------------------------------------------------------

def test_inactif_le_signal_traverse_intact():
    signal = np.random.default_rng(0).normal(0.0, 0.3, (32, 1135))
    norme = obtenir_norme("PAL-BG")
    sortie = vhs.enregistrer_et_relire(signal, norme, vhs.ParametresVHS(actif=False))
    assert sortie is signal or np.array_equal(sortie, signal)


def test_la_cassette_ne_change_pas_la_geometrie_du_signal():
    """Entrée et sortie ont la même forme : un magnétoscope rend un composite,
    c'est tout l'intérêt du procédé."""
    norme = obtenir_norme("PAL-BG")
    signal = np.zeros((48, norme.echantillons_ligne_totale))
    sortie = vhs.enregistrer_et_relire(signal, norme, vhs.ParametresVHS(**PROPRE))
    assert sortie.shape == signal.shape


def test_la_cassette_degrade_sans_detruire():
    """Elle doit coûter quelque chose, et pas tout.

    Un ΔE de 10 à 20 sur des barres de couleur : la couleur bave franchement,
    l'image reste parfaitement regardable. Au-delà de 40 c'est que quelque
    chose est cassé, en dessous de 4 c'est que rien ne se passe.
    """
    direct = mesures.evaluer(rendre()).delta_e_moyen
    cassette = mesures.evaluer(rendre(**PROPRE)).delta_e_moyen
    assert direct < 5.0
    assert 5.0 < cassette < 40.0


def test_la_teinte_ne_tourne_pas():
    """LE test de ce fichier, et celui qui a trouvé deux fautes.

    Un magnétoscope régénère sa sous-porteuse à partir du burst : il ne la
    transporte pas telle quelle. Ni le retard de la voie chrominance, ni
    l'erreur de base de temps ne doivent donc faire tourner la teinte.

    Les deux la faisaient. Le retard de 0,6 µs appliqué à la porteuse modulée
    valait 238° à 4,43 MHz, et le magenta ressortait VERT. La gigue, appliquée
    au composite reconstitué, valait 180° pour deux points d'échantillonnage —
    à f_sc = f_e/4, décaler de deux points, c'est tourner d'un demi-tour.
    """
    for reglage in (PROPRE, {**PROPRE, "gigue": 0.8, "usure": 0.5}):
        bilan = mesures.evaluer(rendre(**reglage))
        assert abs(bilan.erreur_teinte_moyenne) < 8.0, reglage


def test_la_couleur_bave_horizontalement_et_pas_verticalement():
    """Le color-under ne touche qu'à la bande passante horizontale. La
    résolution verticale de la couleur est fixée par la norme — une ligne est
    une ligne — et la cassette n'y peut rien."""
    direct = np.clip(rendre().finale, 0.0, 1.0)
    cassette = np.clip(rendre(**PROPRE).finale, 0.0, 1.0)

    def detail_chroma(image, axe):
        """Énergie de chrominance au-dessus du quart de la fréquence de Nyquist.

        On ne mesure PAS la variation totale : elle se conserve quand on floute
        une transition monotone — une marche étalée sur dix points a la même
        somme de différences qu'une marche franche. Elle donnait donc la
        cassette pour plus nette que le direct, ce qui est absurde. C'est bien
        le contenu HAUTE FRÉQUENCE qu'il faut regarder.
        """
        difference = image[..., 0] - image[..., 2]        # rouge moins bleu
        profil = difference.mean(axis=1 - axe)
        spectre = np.abs(np.fft.rfft(profil - profil.mean()))
        frequences = np.fft.rfftfreq(profil.size)
        return float(np.sqrt((spectre[frequences > 0.25] ** 2).sum()))

    # Les transitions de couleur horizontales s'adoucissent nettement...
    assert detail_chroma(cassette, axe=1) < 0.6 * detail_chroma(direct, axe=1)
    # ...et rien ne se passe verticalement : une ligne reste une ligne.
    assert detail_chroma(cassette, axe=0) == pytest.approx(
        detail_chroma(direct, axe=0), rel=0.35
    )


def test_la_luminance_perd_ses_hautes_frequences():
    """Sur un multiburst, les paquets les plus fins doivent s'effacer, et
    d'autant plus que la bande défile lentement."""
    multiburst = mires.CATALOGUE["Multiburst"](144, 192)

    def contraste(vitesse=None):
        params = Parametres(norme="PAL-BG", taille_sortie=multiburst.shape[:2])
        if vitesse is not None:
            params.vhs = vhs.ParametresVHS(**{**PROPRE, "vitesse": vitesse})
        image = np.clip(encoder_decoder(multiburst, params).finale, 0.0, 1.0)
        profil = image[..., 1].mean(axis=0)
        return float(np.abs(np.diff(profil)).mean())

    direct, sp, ep = contraste(), contraste("SP"), contraste("EP")
    assert sp < direct
    assert ep < sp


# ---------------------------------------------------------------------------
# Les défauts, un par un
# ---------------------------------------------------------------------------

def test_la_gigue_fait_onduler_sans_ajouter_de_bruit():
    """Une mécanique a de l'inertie : le décalage est lissé verticalement.

    Tiré indépendamment ligne à ligne, il donnerait un grésillement de haute
    fréquence — du bruit — et non l'ondulation lente qu'on voit sur une
    cassette. On vérifie donc que le profil de décalage est bien corrélé d'une
    ligne à l'autre.
    """
    params = vhs.ParametresVHS(**{**PROPRE, "gigue": 1.0, "usure": 1.0})
    decalages = vhs._decalages_gigue(200, params, 17.73e6, np.random.default_rng(2))

    assert np.abs(decalages).max() > 1.0, "la gigue doit décaler d'au moins un point"
    correlation = np.corrcoef(decalages[:-1], decalages[1:])[0, 1]
    assert correlation > 0.7, "le décalage doit être lissé, pas tiré au hasard"


def test_la_gigue_deforme_l_image():
    """Elle doit se voir : les verticales ondulent."""
    droit = np.clip(rendre(**PROPRE).finale, 0.0, 1.0)
    ondule = np.clip(rendre(**{**PROPRE, "gigue": 1.0, "usure": 0.8}).finale, 0.0, 1.0)
    assert np.abs(np.diff(ondule, axis=0)).mean() > 2.0 * np.abs(
        np.diff(droit, axis=0)
    ).mean()


def test_les_bruits_ajoutent_du_grain():
    calme = np.clip(rendre(**PROPRE).finale, 0.0, 1.0)
    for defaut in ("bruit_luma", "bruit_chroma"):
        bruite = np.clip(
            rendre(**{**PROPRE, defaut: 2.0, "usure": 0.8}).finale, 0.0, 1.0
        )
        assert bruite.std() != pytest.approx(calme.std(), abs=1e-4), defaut


def test_la_commutation_des_tetes_ne_touche_que_le_bas():
    """Les deux têtes se relaient quelques lignes avant la fin de l'image. Le
    haut ne doit rien en savoir."""
    norme = obtenir_norme("PAL-BG")
    signal = np.zeros((60, norme.echantillons_ligne_totale))
    signal[:] = np.linspace(0.0, 1.0, norme.echantillons_ligne_totale)

    sortie = vhs.enregistrer_et_relire(
        signal, norme, vhs.ParametresVHS(**{**PROPRE, "commutation_tetes": True})
    )
    ecart = np.abs(sortie - signal).mean(axis=1)
    assert ecart[:-8].max() < 0.05, "le haut de l'image doit rester intact"
    assert ecart[-6:].max() > 0.05, "le bas doit être perturbé"


def test_le_depassement_borde_les_contours():
    """Le liseré clair au bord des zones sombres : la signature de tout
    enregistreur à modulation de fréquence."""
    sans = np.clip(rendre(**PROPRE).finale, 0.0, 1.0)
    avec = np.clip(rendre(**{**PROPRE, "depassement": 2.0}).finale, 0.0, 1.0)
    # Le dépassement accentue les transitions : le contraste local monte.
    assert np.abs(np.diff(avec, axis=1)).mean() > np.abs(np.diff(sans, axis=1)).mean()


def test_une_cassette_usee_est_pire_qu_une_neuve():
    neuve = mesures.evaluer(rendre(actif=True, usure=0.0, gigue=0.2)).delta_e_moyen
    usee = mesures.evaluer(rendre(actif=True, usure=1.0, gigue=0.2)).delta_e_moyen
    assert usee > neuve


@pytest.mark.parametrize("code", ["NTSC-M", "PAL-BG", "SECAM-L"])
def test_les_trois_normes_passent_la_cassette(code):
    """Le magnétoscope est indifférent à la norme : il transpose ce qu'on lui
    donne. Le SECAM y a droit comme les autres — c'est ce que faisait le
    MESECAM, qui déplaçait toute la bande de chrominance sans la décoder."""
    mire = mires.barres_couleur(144, 192)
    params = Parametres(norme=code, taille_sortie=mire.shape[:2])
    params.vhs = vhs.ParametresVHS(**PROPRE)
    if code.startswith("SECAM"):
        params.decodage.separateur = "notch"
    resultat = encoder_decoder(mire, params)
    assert np.isfinite(resultat.finale).all()
    assert resultat.finale.max() > 0.5, "l'image est noire"
