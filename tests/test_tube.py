"""
Vérifie la caméra à tubes : sa transparence, sa rémanence, et sa comète.

Le contrôle le plus important est le premier. Un tube analyseur ne dégrade pas
une image immobile — il ne fait que retarder les changements — et le modèle
doit le rendre exactement, sans quoi tout ce qu'on mesurerait ensuite serait
mêlé d'une erreur constante.
"""

from __future__ import annotations

import numpy as np
import pytest

from tvcolor.tube import (
    CAMERAS,
    ChaineTube,
    ParametresTube,
    eclairement_scene,
    filmer,
    fraction_residuelle,
    obtenir_camera,
)


# ---------------------------------------------------------------------------
# Transparence
# ---------------------------------------------------------------------------

def test_tube_transparent_sur_image_fixe():
    """Régime établi sur une scène fixe : le signal lu EST la scène.

    C'est un résultat exact, pas une approximation. À l'équilibre la charge
    résiduelle ne bouge plus, donc ce que le faisceau évacue est exactement ce
    que la trame a déposé, c'est-à-dire `L + b` ; l'étage de niveau du noir
    retire `b`, et il reste `L`. La rémanence n'y change rien : elle décide de
    la VITESSE d'établissement, pas du point d'équilibre.
    """
    rng = np.random.default_rng(4)
    scene = rng.random((24, 32, 3)) * 0.9

    for remanence in (0.0, 0.35, 0.8):
        chaine = ChaineTube(ParametresTube(remanence=remanence, eclat_reflets=0.0))
        chaine.amorcer(scene, 40)
        lu = chaine.traiter(scene)
        assert np.abs(lu - scene).max() < 1e-12


def test_camera_eteinte_ne_touche_a_rien():
    from tvcolor.tube import appliquer

    scene = np.linspace(0.0, 1.0, 3 * 8 * 8).reshape(8, 8, 3)
    assert appliquer(scene, ParametresTube(actif=False)) is scene


# ---------------------------------------------------------------------------
# Rémanence
# ---------------------------------------------------------------------------

def test_remanence_pire_dans_les_bas_niveaux():
    """La propriété contre-intuitive du tube, et celle qu'il faut reproduire.

    Un petit écart de potentiel se résorbe lentement, parce que le faisceau ne
    peut plus y déposer que la queue de sa distribution d'énergie. Une image
    sombre traîne donc bien plus qu'une image bien éclairée — et c'est pour
    cela que les caméras avaient une lumière de biais.
    """
    def residus(niveau: float) -> list[float]:
        params = ParametresTube(eclat_reflets=0.0, lumiere_de_biais=0.0)
        chaine = ChaineTube(params)
        scene = np.full((1, 1, 3), niveau)
        chaine.amorcer(scene, 40)
        noir = np.zeros((1, 1, 3))
        return [float(chaine.traiter(noir)[0, 0, 0]) / niveau for _ in range(3)]

    clair, sombre = residus(1.0), residus(0.05)

    # Deuxième trame après extinction : 2,3 % à pleine lumière, 19 % à 5 %.
    assert clair[0] < 0.03
    assert sombre[0] > 6.0 * clair[0]
    # Et la décroissance reste monotone dans les deux cas.
    assert clair == sorted(clair, reverse=True)
    assert sombre == sorted(sombre, reverse=True)


def test_lumiere_de_biais_reduit_la_remanence():
    """Ce à quoi elle servait, et à rien d'autre."""
    def residu(biais: float) -> float:
        params = ParametresTube(eclat_reflets=0.0, lumiere_de_biais=biais)
        chaine = ChaineTube(params)
        scene = np.full((1, 1, 3), 0.05)
        chaine.amorcer(scene, 40)
        return float(chaine.traiter(np.zeros((1, 1, 3)))[0, 0, 0])

    assert residu(0.06) < 0.5 * residu(0.0)


def test_fraction_residuelle_decroit_avec_la_charge():
    charges = np.array([0.01, 0.05, 0.2, 1.0, 5.0])
    r = fraction_residuelle(charges, 0.35)
    assert np.all(np.diff(r) < 0.0)
    assert r[0] < 0.35 and r[-1] < 0.01


# ---------------------------------------------------------------------------
# La reconstruction des hautes lumières
# ---------------------------------------------------------------------------

def _scene(taille=192):
    return np.zeros((taille, taille, 3))


# Les essais de comète ci-dessous demandent un reflet FRANC et pas d'optique.
#
# Le réglage par défaut est délibérément léger — calé sur une capture de 1972,
# où l'on ne voit aucune plage blanche — et la tache de diffusion de l'objectif
# étale le sommet, ce qui est juste mais brouille une mesure de géométrie. Pour
# vérifier la mécanique du faisceau, on suppose donc un projecteur dans l'axe et
# une optique parfaite.
COMETE = dict(eclat_reflets=25.0, diffusion=0.0)


def test_un_reflet_part_en_surcharge_pas_un_drap_blanc():
    """Les deux sont à 100 % dans le fichier : seule la FORME les sépare.

    C'est la seule hypothèse du module — un fichier huit bits ne contient plus
    l'éclairement des reflets, il faut le lui rendre — et ce test vérifie que
    le critère employé ne se trompe pas de cible.
    """
    params = ParametresTube(**COMETE)

    reflet = _scene()
    reflet[95:99, 95:99] = 1.0
    assert eclairement_scene(reflet, params).max() > 20.0

    aplat = _scene()
    aplat[30:160, 30:160] = 1.0
    assert eclairement_scene(aplat, params).max() < 1.01

    plein = np.ones((192, 192, 3))
    assert eclairement_scene(plein, params).max() < 1.01


def test_un_reflet_filiforme_est_reconnu():
    """Une corde de guitare, un jonc de chrome : fin mais long."""
    params = ParametresTube(**COMETE)
    corde = _scene()
    corde[40:150, 95:97] = 1.0
    assert eclairement_scene(corde, params).max() > 20.0


# ---------------------------------------------------------------------------
# La queue de comète
# ---------------------------------------------------------------------------

def _trainee(image: np.ndarray, ligne: int) -> int:
    """Nombre de pixels consécutifs au blanc écrêté sur une ligne."""
    return int(np.sum(image[ligne, :, 0] > 0.9))


def test_queue_de_comete_a_la_longueur_prevue():
    """La longueur se calcule avant de se mesurer, et les deux doivent coller.

    Le faisceau évacue une tranche fixe par trame : un reflet à `E` fois le
    blanc met `E/c` trames à s'effacer, et laisse donc `E/c × v` pixels de
    traînée. Rien n'est réglé à l'œil ici — la prédiction est
    `ParametresTube.trainee_en_pixels`.
    """
    vitesse = 5.0
    params = ParametresTube(
        **COMETE, actif=True, faisceau=1.3, mouvement=(vitesse, 0.0), champs=30,
    )
    scene = _scene(160)
    scene[78:82, 100:104] = 1.0

    lu = filmer(scene, params)
    mesure = _trainee(lu, 79)
    prevu = params.trainee_en_pixels() + 4.0   # + la largeur du reflet lui-même

    assert abs(mesure - prevu) < 0.25 * prevu


def test_la_trainee_est_plate_et_ecretee():
    """Elle se lit au maximum du faisceau, donc au blanc, sur toute sa longueur.

    C'est ce qui distingue une queue de comète d'un flou de bougé : un flou
    s'éteint progressivement, une comète est un aplat qui s'arrête net.
    """
    params = ParametresTube(
        **COMETE, actif=True, mouvement=(5.0, 0.0), champs=20
    )
    scene = _scene(160)
    scene[78:82, 110:114] = 1.0

    lu = filmer(scene, params)
    trainee = lu[79, :, 0]
    allumes = np.flatnonzero(trainee > 0.5)

    assert allumes.size > 20
    # Plate, et au blanc : mesuré, 28 pixels dont 82 % exactement à 1,000, le
    # reste étant le dernier pas du faisceau qui rattrape la charge restante.
    assert trainee[allumes].min() > 0.80
    assert (trainee[allumes] > 0.999).mean() > 0.75
    # Et elle s'arrête net. Un flou de bougé s'éteindrait en fondu ; ici le
    # pixel qui suit la tête du reflet est à zéro, sans transition.
    assert trainee[allumes.max() + 1] < 0.05


def test_l_image_disparait_derriere_la_trainee():
    """Le faisceau donne déjà tout : ce qui s'ajoute à la cible ne se lit pas."""
    params = ParametresTube(
        **COMETE, actif=True, mouvement=(5.0, 0.0), champs=20
    )
    fond = _scene(160)
    fond[:, :] = 0.35
    fond[78:82, 110:114] = 1.0

    lu = filmer(fond, params)
    # Vingt pixels derrière le reflet, on doit lire du blanc et non le fond.
    assert lu[79, 90, 0] > 0.99


def test_la_trainee_ne_depend_pas_du_temps_passe_dans_le_champ():
    """La cible sature, et c'est ce qui borne tout.

    Sans cette borne, la charge s'accumule sans fin : mesuré sur la version qui
    en manquait, un reflet resté quarante trames dans le champ avait amassé 989
    unités, de quoi traîner plus de quinze secondes. C'est exactement ce qu'on
    voyait à l'écran, et c'est ce que ce test interdit désormais — un reflet qui
    stationne une seconde ne traîne pas plus longtemps qu'un reflet qui passe.
    """
    def charge_apres(trames: int) -> float:
        chaine = ChaineTube(ParametresTube(**COMETE, actif=True))
        eclairement = np.full((1, 1, 3), 26.0)
        for _ in range(trames):
            chaine.integrer(eclairement)
        return float(chaine.charge[0, 0, 0])

    assert charge_apres(200) == pytest.approx(charge_apres(5), rel=1e-9)
    assert charge_apres(200) < ParametresTube().charge_maximale


def test_un_reflet_plus_brillant_ne_traine_pas_plus_longtemps():
    """Conséquence directe de la saturation, et contre-intuitive.

    Au-delà de la capacité de la cible, doubler l'éclairement d'un reflet ne
    dépose pas deux fois plus de charge : il n'y a plus de place. La durée de la
    traînée ne dépend alors plus que du rapport entre cette capacité et le
    courant du faisceau.
    """
    scene = _scene(160)
    scene[78:82, 110:114] = 1.0
    commun = dict(**COMETE, actif=True, mouvement=(5.0, 0.0), champs=20)

    modeste = _trainee(filmer(scene, ParametresTube(**commun)), 79)
    commun_feroce = dict(commun, eclat_reflets=100.0)
    feroce = _trainee(filmer(scene, ParametresTube(**commun_feroce)), 79)
    assert modeste == feroce

    # En revanche, une cible plus capacitive traîne bien plus longtemps :
    # mesuré, 75 pixels contre 43 en triplant la capacité.
    commun_large = dict(commun, charge_maximale=30.0)
    large = _trainee(filmer(scene, ParametresTube(**commun_large)), 79)
    assert large > 1.5 * modeste


def test_l_anti_comete_supprime_la_trainee():
    """Le circuit de 1976, et la raison pour laquelle l'effet a disparu."""
    scene = _scene(160)
    scene[78:82, 110:114] = 1.0

    commun = dict(**COMETE, actif=True, mouvement=(5.0, 0.0), champs=20)
    sans = filmer(scene, ParametresTube(**commun, anti_comete=0.0))
    avec = filmer(scene, ParametresTube(**commun, anti_comete=1.0))

    # Sans anti-comète, 75 pixels de traînée ; avec, il ne reste que le reflet
    # lui-même, étalé du déplacement d'une trame.
    # Mesuré : 23 pixels de traînée sans anti-comète, 8 avec — soit le reflet
    # lui-même, étalé du déplacement d'une trame.
    assert _trainee(sans, 79) > 18
    assert _trainee(avec, 79) < 0.5 * _trainee(sans, 79)


def test_la_trainee_change_de_couleur_sur_sa_longueur():
    """La traînée d'un reflet chaud finit rouge, et personne ne l'a peinte.

    Les trois tubes surchargent inégalement, chacun met un temps différent à
    s'évacuer, et la traînée passe du blanc au jaune puis au rouge à mesure
    qu'on s'éloigne du reflet.

    **Mais il y faut un reflet dont les canaux ne soient pas tous écrêtés
    ensemble**, et c'est une limite qu'il vaut mieux énoncer. Un fichier huit
    bits où les trois canaux sont à 255 ne dit RIEN de leurs proportions
    réelles : le simulateur les amplifie alors à l'identique, et la traînée sort
    blanche. La couleur n'apparaît que si le fichier a gardé l'inégalité — ici
    un reflet à (1,000 ; 0,981 ; 0,950), dont seul le rouge est écrêté pour de
    bon.
    """
    scene = np.full((288, 384, 3), 0.06)
    scene[140:146, 300:306] = (1.0, 0.981, 0.95)

    lu = filmer(scene, ParametresTube(
        **COMETE, actif=True, mouvement=(6.0, 0.0), champs=30
    ))[143]

    # Longueurs mesurées : rouge 35 pixels, vert 24, bleu 5. Le bleu ne
    # surcharge pas du tout ; le vert lâche bien avant le rouge.
    def borne(canal):
        allumes = np.flatnonzero(lu[:, canal] > 0.5)
        return allumes.min(), allumes.max()

    debut_r, _ = borne(0)
    debut_v, _ = borne(1)
    debut_b, fin_b = borne(2)

    assert debut_r < debut_v < debut_b        # le rouge tient le plus longtemps
    assert fin_b - debut_b < 10               # le bleu ne surcharge pratiquement pas
    assert lu[278, 0] > 0.9 and lu[278, 1] < 0.5   # la pointe est rouge


def test_un_reflet_entierement_ecrete_traine_en_blanc():
    """La limite de la reconstruction, énoncée plutôt que masquée.

    Quand les trois canaux sont à 255 dans le fichier, plus rien ne dit lequel
    était le plus fort dans la scène. Le simulateur les amplifie donc à
    l'identique, et la traînée sort blanche. C'est honnête : l'information a été
    perdue par celui qui a fabriqué le fichier, pas par la simulation.
    """
    scene = np.full((288, 384, 3), 0.06)
    scene[140:146, 300:306] = 1.0

    lu = filmer(scene, ParametresTube(
        **COMETE, actif=True, mouvement=(6.0, 0.0), champs=30
    ))[143]
    longueurs = [int((lu[:, k] > 0.5).sum()) for k in range(3)]
    assert longueurs[0] == longueurs[1] == longueurs[2]


def test_la_trainee_suit_le_sens_du_mouvement():
    """Elle est derrière, jamais devant : c'est une trace du passé."""
    scene = _scene(160)
    scene[78:82, 80:84] = 1.0
    commun = dict(**COMETE, actif=True, champs=20)

    droite = filmer(scene, ParametresTube(**commun, mouvement=(5.0, 0.0)))
    gauche = filmer(scene, ParametresTube(**commun, mouvement=(-5.0, 0.0)))

    # Mesuré : 37,1 d'un côté contre 2,0 de l'autre, dans les deux sens.
    assert droite[79, :80, 0].sum() > 10.0 * droite[79, 84:, 0].sum()
    assert gauche[79, 84:, 0].sum() > 10.0 * gauche[79, :80, 0].sum()


# ---------------------------------------------------------------------------
# Le pont temporel
# ---------------------------------------------------------------------------

def _film(positions, pose: float, images: int = 14, taille: int = 4):
    """Fait défiler un reflet devant la caméra, image par image, sans filé.

    C'est le régime du moteur temps réel : la source saute d'une position à
    l'autre, et rien ne dit où le reflet est passé entre les deux.
    """
    hauteur, largeur = 288, 700
    chaine = ChaineTube(ParametresTube(**COMETE, actif=True, pont_temporel=pose))
    lu = None
    for k in range(images):
        image = np.full((hauteur, largeur, 3), 0.06)
        for x in positions(k):
            image[140 : 140 + taille, x : x + taille] = 1.0
        eclairement = chaine.ponter(chaine.eclairement(image))
        for _ in range(2):          # deux trames par image, comme le moteur
            lu = chaine.integrer(eclairement)
    return lu


def _continuite(image: np.ndarray) -> tuple[int, int]:
    """(pixels allumés, étendue) sur la ligne du reflet."""
    ligne = image[141, :, 0]
    allumes = np.flatnonzero(ligne > 0.5)
    return allumes.size, allumes.max() - allumes.min() + 1


def test_sans_pont_la_trainee_sort_en_chapelet():
    """Le défaut que le pont corrige, mesuré avant de l'être.

    Un reflet de quatre pixels qui avance de vingt-quatre par image dépose sa
    charge par paquets espacés : la traînée n'est allumée que sur un cinquième
    de son étendue, et l'on voit une file de reflets distincts au lieu d'une
    traînée.
    """
    allumes, etendue = _continuite(_film(lambda k: [60 + 24 * k], pose=0.0))
    assert allumes / etendue < 0.35


def test_le_pont_rend_la_trainee_continue():
    """Et il la rend continue **sans l'épaissir** — c'est tout l'intérêt d'une
    interpolation dirigée plutôt que d'un simple étalement."""
    image = _film(lambda k: [60 + 24 * k], pose=28.0)
    allumes, etendue = _continuite(image)
    assert allumes == etendue

    colonne = image[:, (np.flatnonzero(image[141, :, 0] > 0.5)).mean().astype(int), 0]
    assert int((colonne > 0.5).sum()) <= 6      # le reflet fait 4 pixels de haut


def test_le_pont_ne_relie_pas_deux_reflets_immobiles():
    """Le garde-fou, et la raison d'être des deux qualificatifs.

    Sans eux, deux reflets immobiles distants de vingt-quatre pixels se
    retrouvaient reliés par un trait blanc, purement inventé. On exige donc un
    éclairement là où il n'y avait pas de charge, et de la charge là où il n'y
    a plus d'éclairement : deux reflets immobiles ont les deux au même endroit,
    et ne remplissent rien.
    """
    allumes, _ = _continuite(_film(lambda k: [300, 324], pose=28.0))
    assert allumes <= 10          # les deux reflets de 4 pixels, et rien entre


def test_le_pont_ne_se_nourrit_pas_de_lui_meme():
    """Le garde-fou structurel, et il a coûté cher à trouver.

    La première version consultait la CHARGE pour savoir où le reflet était
    passé. Or un point comblé dépose lui aussi de la charge : à l'image
    suivante il devenait une « trace abandonnée » pour ses voisins, qui se
    comblaient à leur tour. Mesuré sur une scène chaude en mouvement — un ciel
    écrêté et quelques éclats — **23 % de l'écran en blanc saturé à la première
    image, 85 % à la dixième**. La tache mangeait l'image.

    Amortir n'y suffisait pas : à gain 0,55 elle atteignait encore 61 %. Il
    fallait couper la boucle, pas la freiner — le pont ne consulte donc QUE
    l'éclairement, celui-ci et celui d'avant, et jamais la charge. Un point
    comblé n'entre dans aucune des deux, et ne peut plus rien déclencher.
    """
    hauteur, largeur = 288, 384
    chaine = ChaineTube(ParametresTube(**COMETE, actif=True, pont_temporel=24.0))

    rng = np.random.default_rng(5)
    fond = np.clip(rng.random((hauteur, largeur, 3)) * 0.4 + 0.5, 0.0, 1.0)
    fond[:60] = 1.0                       # un ciel écrêté
    for _ in range(12):                   # quelques éclats
        y, x = int(rng.integers(80, hauteur - 6)), int(rng.integers(6, largeur - 6))
        fond[y : y + 3, x : x + 3] = 1.0

    parts = []
    for k in range(12):
        image = np.roll(fond, 6 * k, axis=1)
        lu = chaine.integrer(chaine.ponter(chaine.eclairement(image)))
        parts.append(float((lu.min(axis=-1) > 0.95).mean()))

    # La part de blanc se stabilise au lieu de croître sans fin.
    assert parts[-1] < 1.6 * parts[0], parts
    assert parts[-1] - parts[-2] < 0.02


def test_le_pont_ne_touche_pas_a_une_scene_fixe():
    """Même exigence de transparence que le reste du module."""
    rng = np.random.default_rng(11)
    scene = rng.random((32, 48, 3)) * 0.9
    chaine = ChaineTube(ParametresTube(eclat_reflets=0.0, pont_temporel=24.0))
    chaine.amorcer(scene, 40)
    assert np.abs(chaine.traiter(scene) - scene).max() < 1e-12


# ---------------------------------------------------------------------------
# Le désalignement des trois tubes
# ---------------------------------------------------------------------------

def test_desalignement_nul_au_centre_croissant_aux_bords():
    """Une erreur d'échelle, la forme qu'elle prenait presque toujours."""
    from tvcolor.tube import _desaligner

    # Une rampe horizontale, identique dans les trois canaux : tout écart entre
    # le rouge et le vert en sortie est alors exactement le déplacement, lu en
    # unités de rampe. Une mire de bruit ne dirait rien — un décalage d'un
    # dixième de pixel y change déjà toutes les valeurs.
    hauteur, largeur = 120, 160
    rampe = np.arange(largeur, dtype=np.float64) / largeur
    scene = np.repeat(np.repeat(rampe[None, :, None], hauteur, 0), 3, 2)

    decale = _desaligner(scene, 4.0)
    ecart = np.abs(decale[..., 0] - decale[..., 1])

    centre = ecart[:, largeur // 2 - 4:largeur // 2 + 4].mean()
    bords = np.concatenate([ecart[:, :8].ravel(), ecart[:, -8:].ravel()]).mean()

    assert centre < 0.05 * bords
    assert bords > 0.01


# ---------------------------------------------------------------------------
# Intégration dans la chaîne complète
# ---------------------------------------------------------------------------

def test_la_camera_precede_tout_le_reste():
    """La caméra agit avant le codeur : elle change ce qui est transmis."""
    from tvcolor.pipeline import Parametres, encoder_decoder

    # Une scène de concert : sombre, avec un éclat de chrome. Le reflet est
    # petit EN PROPORTION de l'image — c'est ce qui le fait reconnaître comme
    # tel, et sur une mire de 96 lignes cela veut dire deux pixels.
    image = np.full((96, 128, 3), 0.12)
    image[41:43, 70:72] = 1.0

    sans = encoder_decoder(image, Parametres(norme="PAL-BG"))
    params = Parametres(norme="PAL-BG")
    params.tube = ParametresTube(**COMETE, actif=True, mouvement=(5.0, 0.0), champs=16)
    avec = encoder_decoder(image, params)

    # La traînée est derrière le reflet, et elle est franche.
    trainee = avec.finale[42, 50:70, 0]
    assert trainee.min() > 0.9
    assert sans.finale[42, 50:70, 0].max() < 0.5


def test_camera_immobile_ne_change_presque_rien():
    """Sans mouvement, il n'y a pas de traînée — seulement les reflets rendus.

    Le reste de l'image doit passer intact : c'est la transparence du premier
    test, vérifiée cette fois à travers toute la chaîne.

    La tolérance est ici de 10⁻⁵ et non de 10⁻¹⁵, et pour une raison qui vaut
    d'être notée. L'aller-retour de la matrice de masquage — contamination des
    filtres, puis son inverse — laisse un résidu de 10⁻¹⁶ sur les canaux qui
    devraient être exactement nuls. La correction de gamma qui suit a une pente
    INFINIE en zéro : elle transforme ce 10⁻¹⁶ en 2·10⁻⁶ sur l'image finale.
    C'est la limite de ce qu'on peut demander à une transparence quand une
    matrice traverse un exposant fractionnaire, et cela reste quatre mille fois
    plus petit qu'un échelon de huit bits.
    """
    from tvcolor import mires
    from tvcolor.pipeline import Parametres, encoder_decoder

    image = mires.barres_couleur(h=96, w=128)

    sans = encoder_decoder(image, Parametres(norme="PAL-BG"))
    params = Parametres(norme="PAL-BG")
    params.tube = ParametresTube(
        actif=True, eclat_reflets=0.0, mouvement=(0.0, 0.0), champs=16
    )
    avec = encoder_decoder(image, params)

    assert np.abs(avec.finale - sans.finale).max() < 1e-5


# ---------------------------------------------------------------------------
# La table des caméras
# ---------------------------------------------------------------------------

def _residu_troisieme_trame(camera, niveau: float = 0.05) -> float:
    """Résidu de troisième trame après extinction, en pour-cent du niveau.

    Sans lumière de biais : on mesure une propriété du TUBE, pas du réglage
    d'exploitation. C'est la convention des courbes de lag publiées, et celle
    que déclare `ModeleCamera.lag_troisieme_trame`.
    """
    params = camera.appliquer()
    params.eclat_reflets = 0.0
    params.lumiere_de_biais = 0.0

    chaine = ChaineTube(params)
    scene = np.full((1, 1, 3), niveau)
    chaine.amorcer(scene, 60)

    noir = np.zeros((1, 1, 3))
    residus = [float(chaine.traiter(noir)[0, 0, 0]) / niveau for _ in range(3)]
    return 100.0 * residus[2]


@pytest.mark.parametrize("code", sorted(CAMERAS))
def test_chaque_camera_a_la_remanence_annoncee(code):
    """La table est auto-vérifiante, et c'est tout son intérêt.

    Les paramètres de chaque modèle ne sont pas recopiés d'une fiche technique :
    ils sont choisis pour que le simulateur reproduise le comportement documenté
    de la génération. Une telle affirmation ne vaut que si elle est contrôlée —
    ce test recalcule la rémanence annoncée, de sorte qu'une valeur retouchée à
    l'œil fait rougir la suite.
    """
    camera = CAMERAS[code]
    mesure = _residu_troisieme_trame(camera)
    assert abs(mesure - camera.lag_troisieme_trame) < max(
        0.05 * camera.lag_troisieme_trame, 0.01
    )


def test_le_vidicon_est_de_loin_le_pire():
    """Ce qui l'a cantonné à la surveillance : le mouvement y était illisible."""
    vidicon = _residu_troisieme_trame(CAMERAS["vidicon"])
    autres = [
        _residu_troisieme_trame(c) for code, c in CAMERAS.items() if code != "vidicon"
    ]
    assert vidicon > 20.0
    assert vidicon > 5.0 * max(autres)


def test_les_cameras_encaissent_de_mieux_en_mieux():
    """La traînée raccourcit d'une génération à l'autre, sans jamais rallonger.

    Sur la rémanence, en revanche, la série n'est PAS monotone, et il ne faut
    pas la forcer à l'être : le Saticon de 1981 traînait davantage que le
    Plumbicon de 1973. Il gagnait ailleurs — en définition — et c'est le genre
    d'arbitrage que le simulateur doit rendre plutôt que lisser.
    """
    par_annee = sorted(CAMERAS.values(), key=lambda c: c.annee)
    trainees = [c.parametres().trainee_en_trames() for c in par_annee]

    assert trainees == sorted(trainees, reverse=True)
    assert trainees[0] > 1.9         # le vidicon de 1966, 2,0 trames
    assert trainees[-1] == 0.0       # le CCD de 1987

    # Et la caméra à anti-comète est bien celle qui fait basculer la série.
    bascule = [c.annee for c, t in zip(par_annee, trainees) if t == 0.0][0]
    assert bascule == 1977


def test_le_modele_ne_touche_pas_a_la_scene():
    """Choisir une caméra ne doit rien dire du plateau qu'elle filme."""
    base = ParametresTube(
        actif=True, eclat_reflets=40.0, seuil_reflets=0.6,
        mouvement=(9.0, 2.0), champs=33,
    )
    for camera in CAMERAS.values():
        sortie = camera.appliquer(base)
        assert sortie.eclat_reflets == 40.0
        assert sortie.seuil_reflets == 0.6
        assert sortie.mouvement == (9.0, 2.0)
        assert sortie.champs == 33
        assert sortie.actif is True
        assert sortie.faisceau == camera.faisceau
    # Et l'objet d'origine n'a pas bougé.
    assert base.faisceau == ParametresTube().faisceau


def test_l_anti_comete_suit_la_loi_quadratique():
    """Linéaire, tout le bas de course était inutilisable.

    Les circuits ACT encaissaient plusieurs centaines de fois le blanc. Étalée
    linéairement jusque-là, l'échelle aurait fait passer le curseur de 1 à 391
    en ligne droite, et le premier cran aurait déjà supprimé toute traînée
    visible. Au carré, la course entière sert.
    """
    def encaisse(position: float) -> float:
        return ParametresTube(faisceau=1.3, anti_comete=position).capacite()

    for position, attendu in ((0.0, 1.3), (0.25, 25.7), (0.55, 119.3), (1.0, 391.3)):
        assert abs(encaisse(position) - attendu) < 0.1


def test_camera_inconnue_le_dit_clairement():
    with pytest.raises(KeyError, match="caméra inconnue"):
        obtenir_camera("plumbicon-2050")


def test_le_genou_ouvre_la_gamme_des_remanences():
    """Le correctif qui rend les tubes distinguables, et sa raison d'être.

    Avec le genou figé à 0,10 — ce qu'il était — le résidu de troisième trame
    plafonne aux alentours de 0,7 % à niveau nominal, quelle que soit la
    rémanence : tous les tubes se ressemblent dans les hautes lumières. Le
    sortir en paramètre ouvre un facteur vingt-cinq.
    """
    def residu(remanence: float, genou: float) -> float:
        params = ParametresTube(
            eclat_reflets=0.0, remanence=remanence,
            genou_remanence=genou, lumiere_de_biais=0.0,
        )
        chaine = ChaineTube(params)
        chaine.amorcer(np.ones((1, 1, 3)), 60)
        noir = np.zeros((1, 1, 3))
        return 100.0 * [float(chaine.traiter(noir)[0, 0, 0]) for _ in range(3)][2]

    # Genou figé : la rémanence a beau tripler, le résidu reste dérisoire.
    fige = [residu(r, 0.10) for r in (0.30, 0.60, 0.90)]
    assert max(fige) < 0.8

    # Genou libre : la gamme complète des tubes réels devient accessible.
    assert residu(0.85, 0.80) > 20.0 * residu(0.30, 0.09)
