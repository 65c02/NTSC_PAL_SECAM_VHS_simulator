"""
Vérifie que les shaders temps réel disent la même chose que le simulateur.

Le simulateur `tvcolor` est la référence : il reconstruit le signal composite
sans compromis, et ses propres tests le comparent aux valeurs normatives. Les
shaders, eux, doivent faire le même trajet à une cadence de plusieurs centaines
d'images par seconde, ce qui impose des approximations. Ces tests mesurent
l'écart et le bornent.

Ils exigent un contexte OpenGL 3.3 : sans écran ni pilote, ils sont ignorés
plutôt que déclarés en échec.
"""

from __future__ import annotations

import numpy as np
import pytest

from tvcolor import colorimetrie as col
from tvcolor import mires
from tvcolor.canal import ParametresCanal
from tvcolor.decodeur import ParametresDecodage
from tvcolor.pipeline import Parametres, encoder_decoder

pytest.importorskip("OpenGL", reason="PyOpenGL absent")

NORMES = ["NTSC-M", "PAL-BG", "SECAM-L"]
QUALITES = ["rapide", "normale", "haute"]


# ---------------------------------------------------------------------------
# Contexte partagé
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def vue():
    """Une vue OpenGL prête à rendre, partagée par tous les tests du module."""
    from PyQt5 import QtGui, QtWidgets

    format_gl = QtGui.QSurfaceFormat()
    format_gl.setVersion(3, 3)
    format_gl.setProfile(QtGui.QSurfaceFormat.CoreProfile)
    format_gl.setSwapInterval(0)
    QtGui.QSurfaceFormat.setDefaultFormat(format_gl)

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    from lecteur.vue_gl import VueTelevision

    widget = VueTelevision()
    widget.resize(640, 480)
    widget.show()
    application.processEvents()

    if widget.image_rendue() is None and not widget.isVisible():
        pytest.skip("aucun contexte OpenGL disponible")

    yield widget

    widget.close()


def rendre(vue, image, **reglages) -> np.ndarray:
    """Fait passer une image sRGB flottante par les shaders. Retourne du sRGB flottant."""
    from lecteur.vue_gl import ParametresRendu

    parametres = ParametresRendu(animer=False, **reglages)
    vue.appliquer(parametres)
    vue.definir_image((np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))
    rendu = vue.image_rendue()
    assert rendu is not None, "le rendu n'a rien produit"
    return rendu.astype(np.float64) / 255.0


def reference(image, norme, taille):
    """La même image dans le simulateur de référence."""
    params = Parametres(norme=norme, taille_sortie=taille)
    if norme.startswith("SECAM"):
        params.decodage = ParametresDecodage(separateur="notch")
    return encoder_decoder(image, params).finale


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("norme", NORMES)
@pytest.mark.parametrize("qualite", QUALITES)
def test_les_shaders_compilent_et_rendent(vue, norme, qualite):
    """Neuf combinaisons de norme et de qualité, neuf programmes à lier.

    Chaque changement de qualité recompile : les longueurs de noyau sont des
    constantes de compilation, pour que les boucles soient déroulées par le
    pilote plutôt que testées à chaque tour.
    """
    sortie = rendre(vue, mires.barres_couleur(288, 384), norme=norme, qualite=qualite)
    assert sortie.ndim == 3 and sortie.shape[2] == 3
    assert np.isfinite(sortie).all()
    assert sortie.max() > 0.5, "l'image rendue est noire"


# ---------------------------------------------------------------------------
# Accord avec le simulateur de référence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "norme,delta_median_max",
    [("NTSC-M", 1.5), ("PAL-BG", 1.5), ("SECAM-L", 8.0)],
)
def test_accord_avec_le_simulateur(vue, norme, delta_median_max):
    """Les shaders doivent retrouver ce que calcule `tvcolor`.

    Le seuil est plus large pour le SECAM, et pour des raisons identifiées :
    le shader n'applique pas les préaccentuations basse fréquence — sans effet
    à l'aller-retour, mais elles décalent légèrement les transitions — et son
    piège de sous-porteuse est un filtre à réponse finie là où la référence
    emploie un Butterworth récursif, hors de portée d'un shader.

    On écarte une bande aux bords : les deux chaînes ne traitent pas le
    hors-champ de la même façon, la référence codant la ligne entière avec sa
    suppression quand le shader s'arrête au bord de l'image.
    """
    mire = mires.barres_couleur(288, 384)
    obtenu = rendre(vue, mire, norme=norme)
    attendu = reference(mire, norme, obtenu.shape[:2])

    ecart = col.delta_e_76(col.srgb_vers_lab(obtenu), col.srgb_vers_lab(attendu))
    interieur = ecart[20:-20, 30:-30]

    assert np.median(interieur) < delta_median_max


@pytest.mark.parametrize("norme", ["NTSC-M", "PAL-BG"])
def test_une_image_grise_reste_grise(vue, norme):
    """Compatibilité noir et blanc : sans chrominance, pas de sous-porteuse.

    Le SECAM est exclu à dessein — sa porteuse est émise en permanence, et le
    test correspondant du simulateur vérifie justement qu'il en produit une.
    """
    hauteur, largeur = 288, 384
    gris = np.repeat(
        np.linspace(0.05, 0.95, largeur)[None, :, None], hauteur, 0
    ).repeat(3, 2)

    sortie = rendre(vue, gris, norme=norme)
    ecart = sortie.max(axis=2) - sortie.min(axis=2)
    assert np.median(ecart) < 0.02


# ---------------------------------------------------------------------------
# Le bruit du canal
# ---------------------------------------------------------------------------

def _correlation(residu, dl, dc):
    """Corrélation d'un résidu avec lui-même, décalé de (dl, dc) échantillons."""
    a = residu[: residu.shape[0] - dl, : residu.shape[1] - dc]
    b = residu[dl:, dc:]
    return float((a * b).mean() / max(residu.var(), 1e-12))


@pytest.mark.parametrize(
    "norme,correlation_min",
    [("NTSC-M", 0.45), ("PAL-BG", 0.45), ("SECAM-L", 0.60)],
)
def test_le_bruit_est_limite_a_la_bande_de_luminance(vue, norme, correlation_min):
    """Le bruit doit arriver limité en bande, comme dans `canal._bruit`.

    La référence tire un bruit blanc, le passe à `bande_y`, puis renormalise
    pour retrouver le sigma demandé. Le shader ajoutait pour sa part du bruit
    blanc — un écart à la référence, et un écart visible : le grain était fin
    et isotrope là où la neige d'un téléviseur s'allonge et s'agglomère.

    Ce qui rend ce test nécessaire, c'est que l'écart NE SE VOIT PAS sur un
    écart-type. Les deux versions renormalisent, et donnent le même : 0,121
    en NTSC dans les deux cas. Il faut regarder la corrélation d'un
    échantillon avec son voisin de la même ligne, qui passe de +0,09 à +0,61.

    On ne vérifie que l'axe horizontal. La corrélation verticale existe aussi,
    mais elle ne dit rien du bruit : elle vient du décodeur, et vaut ce que
    vaut sa mémoire de ligne — 0,50 pour le peigne 1H du NTSC, 0,03 pour celui
    du PAL qui remonte deux lignes, 0,22 pour le retard du SECAM.
    """
    hauteur, largeur = 288, 384
    gris = np.full((hauteur, largeur, 3), 0.5)

    propre = rendre(vue, gris, norme=norme)
    bruite = rendre(vue, gris, norme=norme, rapport_signal_bruit=20.0)

    residu = (bruite - propre).mean(axis=2)[20:-20, 30:-30]
    residu = residu - residu.mean()

    assert residu.std() > 0.02, "le bruit demandé n'est pas arrivé"
    assert _correlation(residu, 0, 1) > correlation_min


# ---------------------------------------------------------------------------
# La physique des trois normes
# ---------------------------------------------------------------------------

FRACTION_JAUNE = 0.19
"""Position de la barre jaune dans la mire, en fraction de largeur.

Le choix de la barre n'est pas indifférent, et s'y tromper fait passer les
tests à côté du phénomène. La phase différentielle est, par définition,
proportionnelle au NIVEAU DE LUMINANCE : elle ne produit presque rien sur le
rouge (Y' = 0,22) ou le bleu (Y' = 0,09), et son plein effet sur le jaune
(Y' = 0,70) ou le cyan (Y' = 0,52). C'est d'ailleurs ce qu'on observe à
l'écran — les barres de Hanover strient le jaune et le cyan en laissant le
rouge et le bleu impassibles."""


def _teinte_moyenne(image, colonne):
    """Teinte moyenne d'une bande verticale, dans le plan (U, V)."""
    from tvcolor import matrices as mx

    zone = image[60:-60, colonne : colonne + 10]
    yuv = mx.rgb_vers_yuv(zone.reshape(-1, 3)).mean(axis=0)
    return np.rad2deg(np.arctan2(yuv[2], yuv[1])), float(np.hypot(yuv[1], yuv[2]))


def test_reponse_des_trois_normes_a_la_phase_differentielle(vue):
    """Le résultat central, retrouvé sur le GPU.

    Un seul et même défaut de canal, trois comportements : le NTSC voit sa
    teinte tourner, le PAL l'annule par sa ligne à retard, le SECAM l'ignore
    parce qu'un retard ne change pas une fréquence.
    """
    mire = mires.barres_couleur(288, 384)
    mesures = {}

    for norme in NORMES:
        sain = rendre(vue, mire, norme=norme)
        degrade = rendre(vue, mire, norme=norme, phase_differentielle=50.0)
        colonne = int(sain.shape[1] * FRACTION_JAUNE)
        teinte_saine, sat_saine = _teinte_moyenne(sain, colonne)
        teinte_degradee, sat_degradee = _teinte_moyenne(degrade, colonne)
        mesures[norme] = (
            abs(teinte_degradee - teinte_saine),
            sat_degradee / max(sat_saine, 1e-6),
        )

    assert mesures["NTSC-M"][0] > 4.0, "le NTSC devrait dériver en teinte"
    assert mesures["PAL-BG"][0] < 1.5, "la ligne à retard devrait annuler la dérive"
    assert mesures["SECAM-L"][0] < 1.5, "le SECAM devrait être insensible"

    # Le PAL paie l'annulation en saturation ; le SECAM ne paie rien.
    assert mesures["PAL-BG"][1] < 0.995
    assert mesures["SECAM-L"][1] == pytest.approx(1.0, abs=0.03)


def test_les_barres_de_hanover_apparaissent_sans_ligne_a_retard(vue):
    """PAL-S : l'erreur de teinte alterne d'une ligne à l'autre."""
    mire = mires.barres_couleur(288, 384)

    def striage(ligne_a_retard):
        from tvcolor import matrices as mx

        sortie = rendre(
            vue, mire, norme="PAL-BG",
            phase_differentielle=60.0, ligne_retard=ligne_a_retard,
        )
        colonne = int(sortie.shape[1] * FRACTION_JAUNE)
        bande = sortie[60:-60, colonne : colonne + 10].mean(axis=1)
        yuv = mx.rgb_vers_yuv(bande)
        teintes = np.rad2deg(np.arctan2(yuv[:, 2], yuv[:, 1]))
        return float(np.abs(np.diff(teintes)).mean())

    assert striage(ligne_a_retard=False) > 8.0
    assert striage(ligne_a_retard=True) < 2.0


def test_secam_garde_sa_sous_porteuse_sous_controle(vue):
    """La porteuse SECAM est permanente, mais le filtre cloche la contient.

    Sur une image blanche, le résidu que le piège laisse passer doit rester
    sous quelques niveaux sur 255 — au-delà, il dessinerait un motif visible
    en clair, ce qui n'a jamais été le cas d'un vrai récepteur.
    """
    blanc = np.ones((288, 384, 3))
    for qualite in QUALITES:
        sortie = rendre(vue, blanc, norme="SECAM-L", qualite=qualite)
        interieur = sortie[60:-60, 80:-80, 0]
        assert interieur.std() < 0.06, qualite
        assert interieur.mean() > 0.95, qualite


def test_le_peigne_et_le_rejecteur_ne_donnent_pas_la_meme_image(vue):
    """Deux séparateurs, deux compromis — donc deux images différentes."""
    mire = mires.piege_dot_crawl(288, 384)
    peigne = rendre(vue, mire, norme="NTSC-M", separateur=0)
    notch = rendre(vue, mire, norme="NTSC-M", separateur=1)
    assert np.abs(peigne - notch).mean() > 1e-3


# ---------------------------------------------------------------------------
# Le magnétoscope
# ---------------------------------------------------------------------------

def test_la_cassette_degrade_la_couleur_sans_toucher_a_la_teinte(vue):
    """Le color-under, en une mesure.

    La cassette doit adoucir franchement les transitions de COULEUR — c'est sa
    signature — et ne pas déplacer la teinte des aplats. Le second point est le
    plus délicat : la porteuse de relecture d'un magnétoscope est régénérée à
    partir du signal lu, si bien que ni le retard de la voie chrominance ni
    l'erreur de base de temps ne doivent faire tourner les couleurs.
    """
    mire = mires.barres_couleur(288, 384)
    propre = rendre(vue, mire, norme="PAL-BG", separateur=1)
    cassette = rendre(
        vue, mire, norme="PAL-BG", separateur=1,
        vhs_actif=True, vhs_gigue=0.0, vhs_usure=0.0, vhs_abandons=0.0,
        vhs_commutation=False, vhs_depassement=0.0,
    )

    def detail_couleur(image):
        """Énergie de chrominance dans le haut du spectre horizontal."""
        difference = image[..., 0] - image[..., 2]
        profil = difference.mean(axis=0)
        spectre = np.abs(np.fft.rfft(profil - profil.mean()))
        frequences = np.fft.rfftfreq(profil.size)
        return float(np.sqrt((spectre[frequences > 0.2] ** 2).sum()))

    assert detail_couleur(cassette) < 0.7 * detail_couleur(propre)

    # La teinte des aplats ne bouge pas. On la mesure sur une barre SATURÉE et
    # au milieu de celle-ci : sur du blanc, l'angle de chrominance n'a aucun
    # sens — deux millièmes d'écart le font sauter d'un quadrant — et sur un
    # bord, c'est la transition qu'on mesurerait. La sortie a la géométrie de
    # la norme, 921 points de large, et non celle de la mire.
    def teinte(image):
        largeur = image.shape[1]
        barre = slice(int(largeur * 4.2 / 8), int(largeur * 4.8 / 8))   # magenta
        bloc = image[image.shape[0] // 3 : 2 * image.shape[0] // 3, barre]
        rouge, vert, bleu = bloc[..., 0].mean(), bloc[..., 1].mean(), bloc[..., 2].mean()
        assert max(rouge, vert, bleu) - min(rouge, vert, bleu) > 0.2, "barre trop pâle"
        return np.degrees(np.arctan2(0.877 * (rouge - vert), 0.492 * (bleu - vert)))

    assert abs(teinte(cassette) - teinte(propre)) < 20.0


def test_la_gigue_ne_raye_pas_l_image(vue):
    """Elle doit faire onduler, pas déchirer.

    Deux fautes se cachaient ici, et aucune ne se voyait sans la gigue.
    D'abord un bruit d'ondulation trop rapide — période de quatre lignes — qui
    décalait différemment les lignes n et n-2 et mettait le filtre en peigne en
    échec. Ensuite, et surtout, un décalage FRACTIONNAIRE : la texture du
    composite étant filtrée au plus proche, la lecture retombait sur un texel
    tandis que la phase de démodulation était calculée sur la position exacte.
    À quatre points par cycle de sous-porteuse, un demi-échantillon d'écart
    vaut 45° de teinte — et l'image se rayait de bandes horizontales colorées.

    On mesure donc l'énergie verticale à HAUTE fréquence : une ondulation lente
    n'en produit presque pas, un rayage en produit énormément.
    """
    mire = mires.barres_couleur(288, 384)
    base = dict(norme="PAL-BG", vhs_actif=True, vhs_usure=0.1, vhs_abandons=0.0,
                vhs_commutation=False, vhs_depassement=0.0)
    droit = rendre(vue, mire, vhs_gigue=0.0, **base)
    ondule = rendre(vue, mire, vhs_gigue=0.6, **base)

    def rayure(image):
        """Énergie verticale au-dessus du quart de Nyquist, sur une colonne
        prise au milieu d'un aplat — là où rien ne devrait varier."""
        colonne = image[:, 120:160].mean(axis=1).mean(axis=1)
        spectre = np.abs(np.fft.rfft(colonne - colonne.mean()))
        frequences = np.fft.rfftfreq(colonne.size)
        return float(np.sqrt((spectre[frequences > 0.25] ** 2).sum()))

    assert rayure(ondule) < 3.0 * rayure(droit) + 0.05


def test_le_magnetoscope_coute_peu(vue):
    """Il double le temps de rendu au plus, et l'on reste très loin du temps réel."""
    from lecteur.normes_gl import longueur_vhs

    # Les noyaux du magnétoscope sont les plus longs du projet, et il le faut :
    # 400 kHz sur une grille à 17,7 MHz ne se forment pas en vingt taps.
    assert longueur_vhs("normale", 921, 921) >= 81
    assert longueur_vhs("rapide", 921, 921) < longueur_vhs("haute", 921, 921)


@pytest.mark.parametrize("norme", NORMES)
def test_la_cassette_marche_dans_les_trois_normes(vue, norme):
    sortie = rendre(vue, mires.barres_couleur(288, 384), norme=norme, vhs_actif=True)
    assert np.isfinite(sortie).all()
    assert sortie.max() > 0.5, "l'image est noire"


def test_les_defauts_de_la_cassette_changent_a_chaque_image(vue):
    """Une bande défile : le morceau de ruban sous la tête n'est jamais le même.

    Ni la gigue ni les pertes de signal ne doivent donc se répéter d'une image
    à la suivante. Le défaut trouvé ici était sournois : la passe s'appuyait sur
    `u_phase_image`, l'avance de phase de sous-porteuse d'une image à l'autre.
    Or cette grandeur ne prend que deux valeurs en NTSC, quatre en PAL, et **une
    seule en SECAM** — la sous-porteuse y étant un multiple entier de la
    fréquence ligne. Les défauts de la cassette restaient donc figés d'un bout à
    l'autre du film, et en SECAM ils ne bougeaient jamais.

    On teste les trois normes, et le SECAM est celle qui compte.
    """
    from lecteur.vue_gl import ParametresRendu

    mire = mires.barres_couleur(288, 384)
    for norme in ("SECAM-L", "PAL-BG", "NTSC-M"):
        # Le bruit du canal est éteint : on veut mesurer ce que la cassette
        # fait varier, pas ce que le canal ajoute.
        vue.appliquer(ParametresRendu(
            norme=norme, animer=True, rapport_signal_bruit=None,
            vhs_actif=True, vhs_gigue=0.6, vhs_abandons=0.5, vhs_usure=0.0,
        ))
        images = []
        for _ in range(3):
            vue.definir_image((np.clip(mire, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))
            rendu = vue.image_rendue()
            assert rendu is not None
            images.append(rendu.astype(np.float64))

        for precedente, suivante in zip(images, images[1:]):
            ecart = float(np.abs(suivante - precedente).mean())
            assert ecart > 1.0, f"{norme} : les défauts sont figés ({ecart:.3f})"


def test_en_arret_sur_image_les_defauts_se_figent(vue):
    """Le pendant du test précédent, et il est aussi physique que lui.

    Un magnétoscope à l'arrêt relit la même piste en boucle : la gigue et les
    pertes de signal se figent, et c'est exactement ce qu'on voyait sur un
    arrêt sur image. Le motif suit donc le compteur d'images, et rien d'autre.
    """
    from lecteur.vue_gl import ParametresRendu

    mire = (np.clip(mires.barres_couleur(288, 384), 0.0, 1.0) * 255.0 + 0.5).astype(
        np.uint8
    )
    vue.appliquer(ParametresRendu(
        norme="SECAM-L", animer=False, rapport_signal_bruit=None,
        vhs_actif=True, vhs_gigue=0.6, vhs_abandons=0.5, vhs_usure=0.0,
    ))
    vue.definir_image(mire)
    premiere = vue.image_rendue().astype(np.float64)
    seconde = vue.image_rendue().astype(np.float64)
    assert np.abs(seconde - premiere).mean() < 0.01


# ---------------------------------------------------------------------------
# La caméra à tubes
# ---------------------------------------------------------------------------

def _pousser(vue, images, **reglages):
    """Fait défiler une suite d'images devant la caméra, et rend la dernière.

    Le tube est le seul étage de ce moteur qui garde un état d'une image à
    l'autre : le mesurer suppose donc de lui en donner plusieurs, et non de
    rendre une image isolée comme partout ailleurs.
    """
    from lecteur.vue_gl import ParametresRendu

    vue.appliquer(ParametresRendu(animer=False, **reglages))
    rendu = None
    for image in images:
        vue.definir_image((np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))
        rendu = vue.image_rendue()
    assert rendu is not None
    return rendu.astype(np.float64) / 255.0


def test_tube_transparent_sur_scene_fixe(vue):
    """Une caméra à tubes ne dégrade pas une image immobile.

    Même invariant que dans le simulateur de référence, et même raison : à
    l'équilibre, ce que le faisceau évacue est exactement ce que la trame a
    déposé. Ici l'égalité n'est pas exacte — huit bits en sortie, seize en
    virgule flottante dans les tampons de charge — mais elle doit tenir au
    niveau de quantification près.
    """
    image = mires.barres_couleur(288, 384)
    sans = _pousser(vue, [image] * 3, norme="PAL-BG")
    # Sans reflet à reconstruire ni désalignement des trois tubes : on mesure
    # ici la transparence du MÉCANISME DE CHARGE, et les deux autres défauts
    # ont leurs propres tests.
    avec = _pousser(
        vue, [image] * 3, norme="PAL-BG", tube_actif=True,
        tube_eclat=0.0, tube_desalignement=0.0,
    )

    ecart = np.abs(avec - sans)
    # On mesure l'INTÉRIEUR des barres, et pas leurs transitions. Le passage
    # d'une barre à l'autre est un échelon franc que le composite fait sonner ;
    # un demi-échelon de quantification à l'entrée y déplace le crénelage de
    # deux niveaux, ce qui ne dit rien de la transparence du tube et tout de la
    # raideur de la transition. À l'intérieur des barres, l'écart tombe à un
    # niveau sur 255.
    largeur = ecart.shape[1]
    interieurs = np.concatenate([
        ecart[:, int(k * largeur / 8) + 20 : int((k + 1) * largeur / 8) - 20]
        for k in range(8)
    ], axis=1)
    assert interieurs.max() < 2.0 / 255.0
    assert np.percentile(ecart, 99.0) < 2.0 / 255.0


# Comme dans `tests/test_tube.py` : ces essais mesurent le MÉCANISME de la
# comète, et demandent donc un reflet franc et une optique parfaite. Le réglage
# par défaut est délibérément léger, calé sur une capture d'émission de 1972.
COMETE = dict(tube_eclat=25.0, tube_diffusion=0.0)


def _reflet_qui_traverse(n_images=16):
    """Une scène de concert : sombre, avec un éclat qui traverse le cadre."""
    images = []
    for n in range(n_images):
        image = np.full((288, 384, 3), 0.10)
        colonne = 120 + 8 * n
        image[140:148, colonne:colonne + 8] = 1.0
        images.append(image)
    return images


def _derriere_le_reflet(rendu):
    """La bande d'image que le reflet vient de quitter, en coordonnées relatives.

    Le rendu sort à la géométrie de la NORME — 921 points pour 576 lignes en
    PAL — et non à celle de la source : toute mesure doit donc se faire en
    fractions d'image.

    La fenêtre retenue tient entre le bout de la traînée et la tête du reflet.
    Mesuré : sans caméra le reflet occupe les fractions 0,625 à 0,644 et rien
    d'autre ; avec, la traînée s'étend en arrière d'une fraction qui dépend de
    la capacité de la cible — six blancs, soit 3,6 trames. La fenêtre se tient
    donc juste derrière la tête.
    """
    hauteur, largeur = rendu.shape[:2]
    bande = rendu[int(0.47 * hauteur):int(0.53 * hauteur), :, 0].max(axis=0)
    return bande[int(0.55 * largeur):int(0.62 * largeur)]


def test_tube_laisse_une_queue_de_comete(vue):
    """Un reflet qui se déplace laisse derrière lui une traînée blanche.

    Mesuré sur la portion d'image que le reflet a quittée : 0,10 sans caméra —
    c'est le fond de la scène — et une traînée franche avec.
    """
    images = _reflet_qui_traverse()
    sans = _derriere_le_reflet(_pousser(vue, images, norme="PAL-BG"))
    avec = _derriere_le_reflet(
        _pousser(vue, images, norme="PAL-BG", tube_actif=True, **COMETE)
    )

    assert sans.max() < 0.3
    assert avec.mean() > 0.6
    assert avec.max() > 0.95


def test_anti_comete_supprime_la_trainee_sur_carte_graphique(vue):
    """Le circuit de 1976, sur la carte graphique comme dans la référence."""
    images = _reflet_qui_traverse()
    avec = _derriere_le_reflet(
        _pousser(vue, images, norme="PAL-BG", tube_actif=True, **COMETE))
    acte = _derriere_le_reflet(
        _pousser(vue, images, norme="PAL-BG", tube_actif=True, **COMETE,
                 tube_anti_comete=1.0)
    )

    assert acte.max() < 0.3
    assert avec.mean() > 5.0 * acte.mean()


def test_la_carte_graphique_distingue_les_cameras(vue):
    """Deux modèles opposés doivent donner deux images opposées.

    Le vidicon de 1966 traîne et n'a aucun anti-comète ; le Saticon à canon
    diode de 1984 encaisse deux cent soixante-douze fois le blanc. Si le shader
    ne les séparait pas, c'est que le genou de rémanence ou la capacité du
    faisceau ne lui parviendraient pas.
    """
    from tvcolor.tube import obtenir_camera

    images = _reflet_qui_traverse()

    def rendre_avec(code):
        camera = obtenir_camera(code)
        return _derriere_le_reflet(_pousser(
            vue, images, norme="PAL-BG", tube_actif=True, **COMETE,
            tube_faisceau=camera.faisceau,
            tube_anti_comete=camera.anti_comete,
            tube_remanence=camera.remanence,
            tube_genou=camera.genou_remanence,
            tube_biais=camera.lumiere_de_biais,
            tube_desalignement=camera.desalignement,
        ))

    vieille = rendre_avec("vidicon")
    moderne = rendre_avec("saticon-diode")

    assert vieille.mean() > 0.6      # une traînée franche
    assert moderne.max() < 0.3       # plus rien derrière le reflet


def _reflet_rapide(saut=12, taille=3, n_images=14):
    """Un reflet petit et rapide : le cas où la traînée sort en chapelet."""
    images = []
    for k in range(n_images):
        image = np.full((288, 384, 3), 0.06)
        x = 40 + saut * k
        image[140 : 140 + taille, x : x + taille] = 1.0
        images.append(image)
    return images


def _continuite(rendu):
    """(pixels allumés, étendue) de la traînée sur la bande centrale."""
    hauteur, largeur = rendu.shape[:2]
    bande = rendu[int(0.47 * hauteur):int(0.53 * hauteur), :, 0].max(axis=0)
    allumes = np.flatnonzero(bande > 0.6)
    if allumes.size == 0:
        return 0, 1
    return allumes.size, allumes.max() - allumes.min() + 1


def test_le_pont_temporel_rend_la_trainee_continue(vue):
    """Le défaut, puis sa correction, mesurés sur la carte graphique.

    Une vidéo n'a que vingt-cinq images par seconde alors que la cible intègre
    en continu : sans pont, la charge se dépose par paquets espacés et la
    traînée n'est allumée que sur un cinquième de son étendue — une file de
    reflets distincts au lieu d'une traînée.
    """
    images = _reflet_rapide()
    sans = _continuite(_pousser(
        vue, images, norme="PAL-BG", tube_actif=True, **COMETE,
        tube_desalignement=0.0, tube_pont=0.0,
    ))
    avec = _continuite(_pousser(
        vue, images, norme="PAL-BG", tube_actif=True, **COMETE,
        tube_desalignement=0.0, tube_pont=24.0,
    ))

    assert sans[0] / sans[1] < 0.35
    assert avec[0] / avec[1] > 0.85
    # L'étendue, elle, change peu — les paquets couvraient déjà tout le
    # trajet. C'est ce qu'il y a ENTRE eux que le pont change : quatre fois
    # plus de pixels allumés pour la même longueur de traînée.
    assert avec[0] > 4.0 * sans[0]
