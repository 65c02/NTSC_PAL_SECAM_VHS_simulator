"""
Vérifie la voie son : les propriétés qui doivent tenir, et celles qui doivent
DIFFÉRER d'un système à l'autre.

Le test le plus important de ce fichier n'est pas qu'une chaîne rende ce qu'on
lui donne — c'est que le SECAM-L se dégrade quand le PAL tient bon. Cette
différence-là n'est codée nulle part : elle sort de la modulation d'amplitude.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import signal as sig

from tvcolor import son
from tvcolor.constantes import NORMES, obtenir_norme

TAUX = 48000


def sinus(frequence=1000.0, duree=0.4, amplitude=0.5, taux=TAUX):
    t = np.arange(int(taux * duree)) / taux
    return amplitude * np.sin(2.0 * np.pi * frequence * t)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

def test_chaque_norme_a_sa_porteuse_son():
    for code, norme in NORMES.items():
        voie = norme.son
        assert voie.modulation in ("FM", "AM"), code
        assert 4e6 < voie.decalage < 7e6, code
        assert voie.niveau_porteuse_db < 0.0, code
        assert voie.bande_audio == 15e3, code


def test_le_systeme_l_est_le_seul_en_amplitude():
    """La France a modulé son son en amplitude. C'est unique, et lourd de suites."""
    en_am = [c for c, n in NORMES.items() if n.son.modulation == "AM"]
    assert en_am == ["SECAM-L"]


def test_le_systeme_m_a_la_moitie_de_l_excursion_europeenne():
    """Le canal américain faisait 6 MHz, celui d'Europe 7 ou 8. L'excursion s'en
    ressent, et le rapport signal/bruit avec elle."""
    assert NORMES["NTSC-M"].son.deviation == 25e3
    assert NORMES["PAL-BG"].son.deviation == 50e3
    assert son.gain_de_demodulation_db(NORMES["PAL-BG"].son) - son.gain_de_demodulation_db(
        NORMES["NTSC-M"].son
    ) == pytest.approx(8.1, abs=0.5)


# ---------------------------------------------------------------------------
# Les réseaux d'accentuation
# ---------------------------------------------------------------------------

def test_preaccentuation_et_desaccentuation_sont_exactement_inverses():
    """Elles doivent l'être au bit près, et non « à peu près ».

    L'inverse numérique est obtenu en échangeant numérateur et dénominateur du
    filtre bilinéaire, pas en transposant l'inverse analogique. C'est ce qui
    garantit l'exactitude, et c'est ce qu'on vérifie ici — car si la chaîne
    colorait le signal en l'absence de tout bruit, aucune mesure faite ensuite
    ne voudrait plus rien dire.
    """
    f_ech = 528000.0
    pre, des = son.reseaux_accentuation(50e-6, 15e3, f_ech)
    x = np.random.default_rng(7).normal(0.0, 1.0, 20000)
    retour = sig.lfilter(*des, sig.lfilter(*pre, x))
    assert np.abs(retour - x).max() < 1e-10


def test_la_preaccentuation_suit_la_courbe_theorique():
    """+13,7 dB à 15 kHz pour 50 µs : c'est la valeur du manuel."""
    f_ech = 528000.0
    (b, a), _ = son.reseaux_accentuation(50e-6, 15e3, f_ech)
    frequences = np.array([1e3, 5e3, 10e3, 15e3])
    _, reponse = sig.freqz(b, a, worN=frequences, fs=f_ech)
    obtenu = 20.0 * np.log10(np.abs(reponse))
    ideal = 20.0 * np.log10(np.abs(1.0 + 2j * np.pi * frequences * 50e-6))
    assert np.abs(obtenu - ideal).max() < 0.3


def test_sans_preaccentuation_les_reseaux_sont_transparents():
    """Le système L n'en a pas. Les filtres doivent alors être l'identité."""
    pre, des = son.reseaux_accentuation(0.0, 15e3, 192000.0)
    x = np.random.default_rng(3).normal(0.0, 1.0, 500)
    assert np.allclose(sig.lfilter(*pre, x), x)
    assert np.allclose(sig.lfilter(*des, x), x)


# ---------------------------------------------------------------------------
# Canal parfait
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", ["NTSC-M", "PAL-BG", "SECAM-L", "SECAM-DK"])
def test_canal_parfait_le_son_traverse_proprement(code):
    """Sans bruit, la chaîne doit rendre le signal : plus de 50 dB et moins de
    1 % de distorsion. Ce qui reste vient du filtre à fréquence intermédiaire,
    qui convertit un peu d'amplitude en phase — comme le fait celui d'un vrai
    récepteur."""
    bilan = son.evaluer(obtenir_norme(code), TAUX)
    assert bilan.rapport_signal_bruit > 50.0
    assert bilan.distorsion < 1.0


@pytest.mark.parametrize("code", ["NTSC-M", "PAL-BG", "SECAM-L"])
def test_la_bande_passante_est_plate_puis_coupee(code):
    """Plate à 0,5 dB près jusqu'à 10 kHz, et effondrée à 20."""
    frequences, gains = son.reponse_en_frequence(obtenir_norme(code), TAUX, points=12)
    dans_la_bande = gains[(frequences > 50.0) & (frequences < 10e3)]
    assert np.abs(dans_la_bande).max() < 0.5
    assert gains[-1] < -20.0


def test_desactive_la_chaine_ne_touche_a_rien():
    entree = sinus()
    p = son.ParametresSon(actif=False)
    sortie = son.transmettre(entree, TAUX, obtenir_norme("PAL-BG"), p)
    assert np.allclose(sortie, entree, atol=1e-6)


def test_une_entree_stereo_ressort_en_mono():
    """La télévision analogique était monophonique. Ce n'est pas un raccourci
    d'implémentation, c'est ce que la porteuse transportait."""
    n = int(TAUX * 0.2)
    stereo = np.stack([sinus(1000.0, 0.2), sinus(3000.0, 0.2)], axis=1)
    assert stereo.shape == (n, 2)
    sortie = son.transmettre(stereo, TAUX, obtenir_norme("PAL-BG"))
    assert sortie.ndim == 1


# ---------------------------------------------------------------------------
# Le bruit, et ce qui distingue les systèmes
# ---------------------------------------------------------------------------

def test_le_rapport_porteuse_bruit_est_deduit_du_reglage_image():
    """Étroitesse de bande d'un côté, puissance d'émission de l'autre.

    En PAL : 5 MHz d'image contre 130 kHz de son valent 15,8 dB de gain, dont
    on retire les 13 dB de puissance en moins. Le solde est de +2,8 dB.
    """
    norme = obtenir_norme("PAL-BG")
    obtenu = son.rapport_porteuse_bruit(norme, 40.0)
    gain = 10.0 * np.log10(norme.bande_y / son.largeur_carson(norme.son))
    assert gain == pytest.approx(15.8, abs=0.2)
    assert obtenu == pytest.approx(40.0 + gain - 13.0, abs=1e-6)


def test_le_son_se_degrade_avec_le_bruit_de_l_image():
    """Un seul canal, un seul bruit : le son doit suivre l'image."""
    norme = obtenir_norme("PAL-BG")
    propre = son.evaluer(norme, TAUX, son.ParametresSon(rapport_signal_bruit=50.0))
    sale = son.evaluer(norme, TAUX, son.ParametresSon(rapport_signal_bruit=20.0))
    assert sale.rapport_signal_bruit < propre.rapport_signal_bruit - 10.0


def test_la_fm_tient_bien_apres_que_l_image_a_neige():
    """Le fait le plus souvent constaté et le plus rarement expliqué.

    À 20 dB de rapport signal/bruit d'image — une réception franchement
    médiocre, où la neige est parfaitement visible — le son FM doit encore
    dépasser 40 dB, c'est-à-dire rester parfaitement écoutable.
    """
    for code in ("NTSC-M", "PAL-BG", "SECAM-DK"):
        bilan = son.evaluer(
            obtenir_norme(code), TAUX, son.ParametresSon(rapport_signal_bruit=20.0)
        )
        assert bilan.rapport_signal_bruit > 40.0, code


def test_le_son_du_systeme_l_est_bien_plus_fragile_que_celui_du_pal():
    """LE test de ce fichier.

    Le SECAM-L module son son en amplitude. Son détecteur d'enveloppe n'apporte
    aucun gain de traitement, là où un discriminateur de fréquence en apporte
    une vingtaine de décibels. À bruit de canal égal, le son du système L doit
    donc être nettement plus mauvais que celui du PAL — alors même que sa
    porteuse est émise 3 dB PLUS FORT et que sa bande est quatre fois plus
    étroite, deux avantages qui jouent en sa faveur.

    Rien de tout cela n'est écrit dans le code : la différence naît de
    `_demoduler`, où l'un prend un argument et l'autre un module.
    """
    reglage = son.ParametresSon(rapport_signal_bruit=25.0)
    pal = son.evaluer(obtenir_norme("PAL-BG"), TAUX, reglage)
    secam_l = son.evaluer(obtenir_norme("SECAM-L"), TAUX, reglage)

    assert secam_l.porteuse_bruit > pal.porteuse_bruit          # il part gagnant…
    assert secam_l.rapport_signal_bruit < pal.rapport_signal_bruit - 20.0  # …et perd


def test_le_seuil_fm_existe_et_s_effondre():
    """Sous une dizaine de décibels de porteuse/bruit, la FM décroche.

    Le bruit fait alors franchir ±π au vecteur reçu, et le discriminateur
    produit un saut de phase entier — un claquement. La chute est bien plus
    raide qu'un décibel pour un décibel, et c'est la signature du seuil.
    """
    norme = obtenir_norme("PAL-BG")
    haut = son.evaluer(norme, TAUX, son.ParametresSon(rapport_signal_bruit=10.0))
    bas = son.evaluer(norme, TAUX, son.ParametresSon(rapport_signal_bruit=4.0))
    chute = haut.rapport_signal_bruit - bas.rapport_signal_bruit
    assert chute > 10.0, "six décibels de canal doivent en coûter bien plus de six"


# ---------------------------------------------------------------------------
# Traitement par blocs
# ---------------------------------------------------------------------------

def test_le_traitement_par_blocs_egale_le_traitement_d_un_seul_tenant():
    """Le lecteur vidéo traite le son par paquets. Si l'état des filtres et la
    phase du modulateur ne traversaient pas les jonctions, on entendrait un
    claquement à chaque paquet — le défaut le plus audible qui soit."""
    entree = sinus(440.0, 0.3)
    norme = obtenir_norme("PAL-BG")

    entier = son.ChaineSon(norme, TAUX).traiter(entree)

    par_blocs = son.ChaineSon(norme, TAUX)
    morceaux = [par_blocs.traiter(entree[i : i + 1024])
                for i in range(0, entree.size, 1024)]
    assemble = np.concatenate(morceaux)

    assert assemble.shape == entier.shape
    assert np.abs(assemble - entier).max() < 1e-6


def test_le_ronflement_intercarrier_apparait_et_suit_le_niveau_video():
    """Sur une entrée muette, tout ce qu'on entend est le ronflement. Son
    niveau doit suivre le niveau vidéo : c'est la modulation de la porteuse
    image qui le fabrique, une image noire ne ronfle pas."""
    norme = obtenir_norme("PAL-BG")
    silence = np.zeros(TAUX // 2)

    def energie(niveau_video, intercarrier):
        p = son.ParametresSon(intercarrier=intercarrier, niveau_video=niveau_video)
        return float(np.std(son.transmettre(silence, TAUX, norme, p)))

    sans = energie(0.8, 0.0)
    faible = energie(0.2, 1.0)
    fort = energie(0.9, 1.0)

    assert fort > faible > sans
    # Le rapport doit suivre celui des niveaux vidéo, la dépendance étant linéaire.
    assert fort / faible == pytest.approx(0.9 / 0.2, rel=0.25)


def test_le_ronflement_porte_les_frequences_de_la_norme():
    """Il n'est pas « fabriqué pour sonner juste » : c'est le train
    d'impulsions de suppression de la norme, avec ses vraies durées. On doit
    donc retrouver la fréquence trame et ses harmoniques."""
    norme = obtenir_norme("PAL-BG")
    p = son.ParametresSon(intercarrier=1.0, niveau_video=1.0)
    sortie = son.transmettre(np.zeros(TAUX), TAUX, norme, p)

    utile = np.asarray(sortie[TAUX // 4:], dtype=float)
    spectre = np.abs(np.fft.rfft(utile))
    freqs = np.fft.rfftfreq(utile.size, 1.0 / TAUX)

    # Toutes les raies fortes doivent tomber sur le peigne de la fréquence
    # IMAGE, et non sur celui de la fréquence trame. La nuance n'est pas un
    # détail : une trame compte 312,5 lignes, donc la raie de ligne tombe sur
    # un demi-multiple de la fréquence trame. C'est le pas commun aux deux
    # trains d'impulsions — 25 Hz en 625 lignes — qui structure le ronflement.
    pas = norme.f_trame / 2.0
    fortes = freqs[np.argsort(spectre)[-12:]]
    ecarts = np.abs(fortes / pas - np.round(fortes / pas))
    assert ecarts.max() < 0.05, f"raies hors peigne image : {fortes}"

    def energie_autour(f):
        return float(spectre[np.abs(freqs - f) < 3.0].max())

    plancher = float(np.median(spectre))
    assert energie_autour(norme.f_trame) > 20.0 * plancher      # ronflement de trame
    assert energie_autour(norme.f_ligne) > 20.0 * plancher      # sifflement de ligne


# ---------------------------------------------------------------------------
# Le gain de sortie
# ---------------------------------------------------------------------------

def test_le_gain_de_sortie_est_exact_tant_qu_il_reste_de_la_marge():
    """Sous le seuil de saturation, le gain demandé doit être le gain obtenu.

    Un compresseur qui « arrondirait » dès les premiers décibels rendrait le
    réglage imprévisible : on tourne de six décibels et l'on en veut six.
    """
    norme = obtenir_norme("PAL-BG")
    entree = sinus(amplitude=0.1)
    reference = np.asarray(son.transmettre(entree, TAUX, norme), dtype=np.float64)

    for db in (-6.0, 0.0, 6.0, 12.0, 18.0):
        p = son.ParametresSon(gain_sortie=10.0 ** (db / 20.0))
        sortie = np.asarray(son.transmettre(entree, TAUX, norme, p), dtype=np.float64)
        rapport = np.sqrt(np.mean(sortie[4800:] ** 2) / np.mean(reference[4800:] ** 2))
        assert 20.0 * np.log10(rapport) == pytest.approx(db, abs=0.1), f"{db} dB"


def test_la_saturation_est_douce_et_borne_la_sortie():
    """Poussé à fond, l'étage doit saturer sans jamais dépasser la butée — et
    sans fabriquer les angles droits d'un écrêtage franc."""
    x = np.linspace(-3.0, 3.0, 2001)
    y = son.saturer(x)

    assert np.abs(y).max() < 1.0
    # Strictement linéaire sous le seuil : le réglage reste fidèle.
    sous_le_seuil = np.abs(x) < son.SEUIL_SATURATION
    assert np.allclose(y[sous_le_seuil], x[sous_le_seuil])
    # Monotone et lisse : la dérivée ne saute pas au passage du genou.
    pente = np.diff(y) / np.diff(x)
    assert (pente > 0).all()
    assert np.abs(np.diff(pente)).max() < 0.02


def test_le_gain_de_sortie_agit_meme_quand_la_porteuse_est_court_circuitee():
    """C'est le bouton de volume du poste : il ne dépend pas de ce qui arrive
    avant lui, et doit donc agir aussi quand on écoute le fichier tel quel."""
    entree = sinus(amplitude=0.1)
    p = son.ParametresSon(actif=False, gain_sortie=4.0)
    sortie = np.asarray(
        son.transmettre(entree, TAUX, obtenir_norme("PAL-BG"), p), dtype=np.float64
    )
    assert np.abs(sortie).max() == pytest.approx(0.4, abs=0.01)


def test_le_gain_de_sortie_n_ameliore_pas_le_rapport_signal_bruit():
    """Amplifier après la démodulation amplifie le bruit autant que le signal.

    Le contraire signalerait une faute : un gain placé du mauvais côté du
    démodulateur, qui rattraperait une mauvaise réception. Aucun bouton de
    volume n'a jamais fait ça.
    """
    norme = obtenir_norme("PAL-BG")
    # À bas niveau : les 12 dB doivent tenir dans la marge, faute de quoi c'est
    # la saturation qu'on mesurerait et non le canal.
    faible = son.evaluer(
        norme, TAUX, son.ParametresSon(rapport_signal_bruit=15.0), amplitude=0.05
    )
    fort = son.evaluer(
        norme, TAUX,
        son.ParametresSon(rapport_signal_bruit=15.0, gain_sortie=10.0 ** (12.0 / 20.0)),
        amplitude=0.05,
    )
    assert fort.rapport_signal_bruit == pytest.approx(
        faible.rapport_signal_bruit, abs=1.5
    )


def test_pousser_le_gain_sur_un_signal_deja_fort_fait_saturer():
    """Le pendant du test précédent, et il est tout aussi important.

    Un gain de sortie n'est pas magique : appliqué à un signal déjà proche de
    la butée, il sature. La distorsion doit donc monter franchement, sans quoi
    l'étage de sortie serait un amplificateur idéal — ce qu'aucun n'est.
    """
    norme = obtenir_norme("PAL-BG")
    au_repos = son.evaluer(norme, TAUX, amplitude=0.5)
    pousse = son.evaluer(
        norme, TAUX, son.ParametresSon(gain_sortie=10.0 ** (12.0 / 20.0)),
        amplitude=0.5,
    )
    assert au_repos.distorsion < 1.0
    assert pousse.distorsion > 10.0


def test_le_gain_avant_modulation_ameliore_vraiment_le_rapport_signal_bruit():
    """La différence entre remonter le niveau à l'émission et à la réception.

    Placé AVANT la modulation, le gain décide de l'excursion réellement
    employée — donc de la profondeur de modulation, donc du rapport
    signal/bruit. Un décibel de gain en rend un. C'est pour cela qu'un
    diffuseur surveille sa modulation, et c'est ce qu'il faut pousser quand la
    source est gravée bas.
    """
    norme = obtenir_norme("PAL-BG")

    def mesurer(db_entree=0.0, db_sortie=0.0):
        p = son.ParametresSon(
            rapport_signal_bruit=25.0,
            gain_entree=10.0 ** (db_entree / 20.0),
            gain_sortie=10.0 ** (db_sortie / 20.0),
        )
        return son.evaluer(norme, TAUX, p, amplitude=0.05).rapport_signal_bruit

    reference = mesurer()
    for db in (6.0, 12.0, 18.0):
        assert mesurer(db_entree=db) == pytest.approx(reference + db, abs=1.5), db


def test_le_gain_apres_demodulation_n_ameliore_rien():
    """Le pendant, et c'est lui qui donne son sens au précédent.

    Le bouton de volume d'un poste agit après le démodulateur : il amplifie le
    bruit autant que le signal. Si ce test échouait, c'est qu'un gain se serait
    glissé du mauvais côté du démodulateur.
    """
    norme = obtenir_norme("PAL-BG")

    def mesurer(db):
        p = son.ParametresSon(
            rapport_signal_bruit=25.0, gain_sortie=10.0 ** (db / 20.0)
        )
        return son.evaluer(norme, TAUX, p, amplitude=0.05).rapport_signal_bruit

    reference = mesurer(0.0)
    for db in (6.0, 12.0, 18.0):
        assert mesurer(db) == pytest.approx(reference, abs=1.5), db


def test_surmoduler_finit_par_distordre():
    """Le limiteur de l'émetteur existe, et il s'entend. Poussé bien au-delà du
    point où l'excursion est pleine, le gain d'entrée doit fabriquer de la
    distorsion — c'est ce que fait un émetteur réellement surmodulé."""
    norme = obtenir_norme("PAL-BG")
    raisonnable = son.evaluer(
        norme, TAUX, son.ParametresSon(gain_entree=10.0 ** (12.0 / 20.0)),
        amplitude=0.05,
    )
    excessif = son.evaluer(
        norme, TAUX, son.ParametresSon(gain_entree=10.0 ** (30.0 / 20.0)),
        amplitude=0.05,
    )
    assert raisonnable.distorsion < 1.0
    assert excessif.distorsion > 5.0
