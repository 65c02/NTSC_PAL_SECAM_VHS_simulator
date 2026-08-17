"""
Vérifie l'export MP4 : la géométrie, puis un aller-retour complet.

Le test de bout en bout demande un contexte OpenGL et un encodeur H.264. Sans
eux il est ignoré plutôt que déclaré en échec — c'est la même règle que pour
les shaders.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

av = pytest.importorskip("av", reason="PyAV absent")

from lecteur.export_video import dimensions   # noqa: E402


# ---------------------------------------------------------------------------
# Géométrie
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hauteur", [240, 480, 576, 720, 1080, 1152, 1440, 2160])
def test_les_dimensions_sont_paires_et_au_format_du_tube(hauteur):
    """Deux exigences, et la seconde n'est pas cosmétique.

    Le format 4:3 est celui du tube : une vidéo 16:9 s'y inscrit avec ses
    bandes, exactement comme sur un poste d'époque.

    Les dimensions PAIRES, elles, sont une contrainte du codage : le 4:2:0
    sous-échantillonne la chrominance d'un facteur deux dans les deux
    directions, et une dimension impaire n'a rien à quoi s'accrocher. Les
    encodeurs la refusent — ou pire, l'arrondissent en silence.
    """
    largeur, obtenue = dimensions(hauteur)
    assert largeur % 2 == 0 and obtenue % 2 == 0
    assert abs(largeur / obtenue - 4.0 / 3.0) < 0.01


def test_une_hauteur_impaire_est_ramenee_au_pair_inferieur():
    assert dimensions(1081)[1] == 1080
    assert dimensions(577)[1] == 576


def test_une_hauteur_absurde_est_bornee():
    assert dimensions(1)[1] >= 64
    assert dimensions(0)[1] >= 64


# ---------------------------------------------------------------------------
# Aller-retour complet
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def source(tmp_path_factory):
    """Fabrique une courte vidéo d'essai, image et son."""
    chemin = tmp_path_factory.mktemp("export") / "source.mp4"
    conteneur = av.open(str(chemin), mode="w")
    piste = conteneur.add_stream("libx264", rate=25)
    piste.width, piste.height = 320, 240
    piste.pix_fmt = "yuv420p"

    piste_son = conteneur.add_stream("aac", rate=48000)
    t = np.arange(48000) / 48000.0
    onde = (0.4 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)

    for n in range(25):
        image = np.zeros((240, 320, 3), np.uint8)
        image[:, : 40 + 8 * n] = (200, 60, 60)
        trame = av.VideoFrame.from_ndarray(image, format="rgb24")
        for paquet in piste.encode(trame):
            conteneur.mux(paquet)

    for debut in range(0, onde.size, 1024):
        morceau = np.ascontiguousarray(
            np.repeat(onde[None, debut : debut + 1024], 2, axis=0)
        )
        trame = av.AudioFrame.from_ndarray(morceau, format="fltp", layout="stereo")
        trame.rate = 48000
        for paquet in piste_son.encode(trame):
            conteneur.mux(paquet)

    for paquet in piste.encode():
        conteneur.mux(paquet)
    for paquet in piste_son.encode():
        conteneur.mux(paquet)
    conteneur.close()
    return str(chemin)


@pytest.fixture(scope="module")
def vue():
    pytest.importorskip("OpenGL", reason="PyOpenGL absent")
    from PyQt5 import QtGui, QtWidgets

    format_gl = QtGui.QSurfaceFormat()
    format_gl.setVersion(3, 3)
    format_gl.setProfile(QtGui.QSurfaceFormat.CoreProfile)
    format_gl.setSwapInterval(0)
    QtGui.QSurfaceFormat.setDefaultFormat(format_gl)
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    from lecteur.vue_gl import VueTelevision

    widget = VueTelevision()
    widget.resize(320, 240)
    widget.show()
    application.processEvents()
    if not widget.isVisible():
        pytest.skip("aucun contexte OpenGL disponible")
    yield widget
    widget.close()


def test_le_rendu_hors_ecran_donne_la_taille_demandee(vue):
    """Il ne suffit pas qu'il produise une image : la géométrie du tube se
    calcule sur la surface VISÉE, pas sur la fenêtre. Un export plus grand que
    la fenêtre doit donc être plus grand, et non un agrandissement."""
    from lecteur.vue_gl import ParametresRendu

    vue.appliquer(ParametresRendu(norme="PAL-BG", animer=False))
    vue.definir_image(np.full((288, 384, 3), 160, np.uint8))

    for largeur, hauteur in ((256, 192), (768, 576)):
        rendue = vue.rendre_pour_export(largeur, hauteur)
        assert rendue is not None
        assert rendue.shape == (hauteur, largeur, 3)
        assert rendue.max() > 20, "l'image exportée est noire"


def test_export_complet(vue, source, tmp_path):
    """Le fichier produit doit contenir le bon nombre d'images, à la bonne
    taille, et une piste son."""
    from lecteur.export_video import ExportateurMP4, ReglagesExport
    from lecteur.vue_gl import ParametresRendu
    from tvcolor.son import ParametresSon

    vue.appliquer(ParametresRendu(norme="PAL-BG", courbure=0.2, lignes_balayage=0.4,
                                  animer=False))
    destination = tmp_path / "sortie.mp4"

    messages: list[str] = []
    exportateur = ExportateurMP4(vue)
    exportateur.terminee.connect(messages.append)
    exportateur.echouee.connect(lambda m: pytest.fail(f"export échoué : {m}"))
    exportateur.exporter(
        source,
        ReglagesExport(destination=str(destination), hauteur=240, debit=2_000_000),
        "PAL-BG",
        ParametresSon(rapport_signal_bruit=30.0),
    )

    assert messages, "l'export n'a pas signalé sa fin"
    assert destination.exists() and destination.stat().st_size > 1000

    conteneur = av.open(str(destination))
    try:
        video = next(f for f in conteneur.streams if f.type == "video")
        audio = next((f for f in conteneur.streams if f.type == "audio"), None)
        largeur, hauteur = dimensions(240)
        assert (video.codec_context.width, video.codec_context.height) == (largeur, hauteur)
        assert audio is not None, "la piste son a disparu"
        images = sum(1 for _ in conteneur.decode(video))
        assert images == 25
    finally:
        conteneur.close()


def test_l_export_enregistre_bien_les_effets_de_tube(vue, source, tmp_path):
    """Ce qu'on exporte doit être ce qu'on voit, effets compris.

    Deux exports du même fichier, l'un sans effet de tube et l'autre avec
    courbure et lignes de balayage marquées, ne peuvent pas donner la même
    image. La courbure noircit les coins ; c'est mesurable.
    """
    from lecteur.export_video import ExportateurMP4, ReglagesExport
    from lecteur.vue_gl import ParametresRendu
    from tvcolor.son import ParametresSon

    def coin_moyen(courbure, arrondi):
        vue.appliquer(ParametresRendu(
            norme="PAL-BG", courbure=courbure, arrondi_coins=arrondi,
            lignes_balayage=0.0, animer=False,
        ))
        chemin = tmp_path / f"tube_{courbure}_{arrondi}.mp4"
        exportateur = ExportateurMP4(vue)
        exportateur.echouee.connect(lambda m: pytest.fail(f"export échoué : {m}"))
        exportateur.exporter(
            source,
            ReglagesExport(destination=str(chemin), hauteur=240, debit=2_000_000),
            "PAL-BG", ParametresSon(actif=False),
        )
        conteneur = av.open(str(chemin))
        try:
            flux = next(f for f in conteneur.streams if f.type == "video")
            trame = next(conteneur.decode(flux)).to_ndarray(format="rgb24")
        finally:
            conteneur.close()
        return float(trame[:12, :12].mean())

    plat = coin_moyen(0.0, 0.0)
    bombe = coin_moyen(1.0, 1.0)
    assert bombe < plat - 1.0, (
        f"les coins d'une dalle bombée doivent s'éteindre "
        f"(plat {plat:.1f}, bombé {bombe:.1f})"
    )
