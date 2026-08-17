"""
Le moteur de rendu : trois normes, quelques passes, soixante images par seconde.

Enchaînement pour NTSC et PAL :

    vidéo ──[codage]──> composite ──[décodage]──> image ──[présentation]──> écran

Pour SECAM, deux étapes s'intercalent, imposées par la modulation de fréquence :

    vidéo ──[préparation]──> (écart, luma)
                                  │
                                  ├──[somme préfixe × 10]──> intégrale
                                  │                              │
                                  └──────────[codage]────────────┘
                                                 │
                                            composite ──[décodage]──> image

Chaque passe est un triangle plein écran. Aucune géométrie n'est transférée,
aucun tampon de sommets n'existe : tout le travail est dans le fragment shader.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from OpenGL import GL
from PyQt5 import QtCore, QtGui, QtWidgets

from tvcolor.constantes import obtenir_norme

from .gl_util import (
    Cible,
    Programme,
    Quad,
    TextureImage,
    assembler,
    assembler_simple,
    lire_source,
)
from tvcolor.vhs import RETARD_CHROMA as RETARD_CHROMA_VHS

from .normes_gl import ReglageGL, longueur_vhs, noyaux_vhs, reglage, sigma_du_tube

FICHIER_NORME = {"NTSC": "ntsc.glsl", "PAL": "pal.glsl", "SECAM": "secam.glsl"}

UNITE_SOURCE, UNITE_COMPOSITE, UNITE_PREPARE, UNITE_SCAN, UNITE_VHS = 0, 1, 2, 3, 4


@dataclass
class ParametresRendu:
    """Réglages modifiables à chaud, sans recompiler les shaders."""

    norme: str = "PAL-BG"
    qualite: str = "normale"

    separateur: int = 0            # 0 = peigne, 1 = réjecteur
    ligne_retard: bool = True      # PAL-D contre PAL-S
    amplitude_chroma: float = 1.0
    saturation: float = 1.0

    phase_differentielle: float = 0.0   # degrés par unité de luminance
    gain_differentiel: float = 0.0
    rapport_signal_bruit: float | None = None   # dB, None = pas de bruit

    lignes_balayage: float = 0.0
    masque_tube: float = 0.0
    luminosite: float = 1.0

    halo_intensite: float = 0.0
    """Fraction de la lumière qui repart en halo. 0 désactive les trois passes."""

    halo_seuil: float = 0.55
    """Niveau à partir duquel la lumière diffuse. À zéro c'est la halation, qui
    est linéaire ; relevé, c'est l'épanouissement du faisceau, qui ne touche que
    les hautes lumières."""

    halo_rayon: float = 0.025
    """Rayon du halo, en fraction de la hauteur d'image — donc indépendant de
    la résolution de la grille comme de celle de l'écran."""

    courbure: float = 0.0
    """Bombement de la dalle, de 0 (plate) à 1 (tube très rond des années 60).

    Traduit en rayon de courbure, exprimé en demi-diagonales d'image : 1
    donne 1,6 — soit 42 cm pour un tube de 21 pouces, un poste des années 60 ;
    0,4 donne 4, typique des années 80 ; 0,16 donne 10, la dalle presque plate
    des derniers tubes."""

    arrondi_coins: float = 0.0
    """Arrondi des coins, de 0 (angles vifs) à 1 (très arrondi)."""

    definition_tube: float = 0.0
    """Définition horizontale du tube, en lignes. 0 désactive la simulation du
    spot — c'est alors un écran parfait, qui restitue la sous-porteuse
    intégralement, ce qu'aucun téléviseur n'a jamais fait."""

    echantillonnage: str = "normatif"
    """Finesse de la grille de calcul : `normatif` (quatre points par cycle de
    sous-porteuse), `double`, `triple`, ou `ecran` pour caler la grille sur la
    largeur réellement affichée."""

    vhs_actif: bool = False
    vhs_vitesse: str = "SP"
    vhs_generation: int = 1
    vhs_usure: float = 0.15
    vhs_gigue: float = 0.35
    vhs_abandons: float = 0.25
    vhs_commutation: bool = True
    vhs_depassement: float = 0.8
    """Passage par un magnétoscope, entre le canal et le téléviseur.

    Les mêmes réglages que `tvcolor.vhs.ParametresVHS`, à plat pour rester
    dans l'esprit de cette dataclasse — un seul objet que l'interface remplit
    et que le moteur consomme."""

    animer: bool = True
    conserver_proportions: bool = True

    def bandes_vhs(self) -> tuple[float, float]:
        """Bandes luma et chroma de la cassette, usure et générations comprises.

        Déléguée à `tvcolor.vhs` : il n'y a pas deux tables de constantes dans
        ce projet, et une correction faite pour le simulateur de référence doit
        se propager ici sans qu'on ait à y penser.
        """
        from tvcolor.vhs import ParametresVHS

        return ParametresVHS(
            vitesse=self.vhs_vitesse,
            generation=self.vhs_generation,
            usure=self.vhs_usure,
        ).bandes()

    def largeur_grille(self, norme, largeur_affichee: int) -> int:
        """Largeur de la grille d'échantillonnage, en points par ligne active."""
        base = norme.echantillons_par_ligne
        if self.echantillonnage == "double":
            return 2 * base
        if self.echantillonnage == "triple":
            return 3 * base
        if self.echantillonnage == "ecran":
            # On arrondit à un multiple de quatre : cela évite de reconstruire
            # tous les programmes pour un pixel de différence pendant qu'on
            # redimensionne la fenêtre.
            return max(base, 4 * int(round(largeur_affichee / 4.0)))
        return base

    def sigma_bruit(self) -> float:
        if self.rapport_signal_bruit is None:
            return 0.0
        return 10.0 ** (-self.rapport_signal_bruit / 20.0)


class VueTelevision(QtWidgets.QOpenGLWidget):
    """Affiche une image RGB après l'avoir fait passer par une norme couleur."""

    fps_mesure = QtCore.pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parametres = ParametresRendu()
        self._reglage: ReglageGL | None = None
        self._image: np.ndarray | None = None
        self._image_a_televerser = False
        self._numero_image = 0
        self._pret = False
        self._recompiler = True

        self._cle_reglage: tuple | None = None
        self._capture_demandee = False
        self._capture: np.ndarray | None = None
        self._export_demande: tuple[int, int] | None = None
        self._export: np.ndarray | None = None

        self._instants: list[float] = []
        self.duree_gpu = 0.0
        """Durée du dernier rendu mesurée par la carte graphique, en secondes."""
        self.setMinimumSize(320, 240)

    # ------------------------------------------------------------------
    # Cycle de vie OpenGL
    # ------------------------------------------------------------------

    def initializeGL(self) -> None:
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_BLEND)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)

        self._quad = Quad()
        self._texture_source = TextureImage()
        self._sommet = lire_source("sommet.vert")

        self._programmes: dict[str, Programme] = {}
        self._cibles: dict[str, Cible] = {}

        # Ces deux-là portent déjà leur propre directive de version : ils ne
        # dépendent ni de `commun.glsl` ni de la longueur des noyaux.
        self._programme_scan = Programme(
            self._sommet, lire_source("scan.frag"), "scan"
        )
        self._programme_presentation = Programme(
            self._sommet, lire_source("presentation.frag"), "présentation"
        )
        # Deux programmes plutôt qu'un seul avec un branchement : le pilote
        # peut dérouler chaque boucle sans réserve.
        self._programme_halo_extraction = Programme(
            self._sommet,
            assembler_simple("bloom.glsl", {"PASSE_EXTRACTION": None}),
            "halo/extraction",
        )
        self._programme_halo_flou = Programme(
            self._sommet, assembler_simple("bloom.glsl"), "halo/flou"
        )
        # Chronomètre GPU. Mesurer le temps de rendu avec l'horloge du
        # processeur ne veut rien dire : les commandes OpenGL sont empilées et
        # rendent la main aussitôt, ce qui donne des cadences fantaisistes de
        # plusieurs centaines de milliers d'images par seconde. Une requête
        # GL_TIME_ELAPSED, elle, mesure le travail réellement accompli par la
        # carte. On la relit à l'image suivante pour ne jamais attendre.
        self._requetes = GL.glGenQueries(2)
        self._requete_courante = 0
        self._requete_en_vol = False

        self._pret = True
        self._construire()

    def _construire(self) -> None:
        """(Re)compile les programmes et alloue les cibles pour la norme courante.

        Appelée uniquement depuis `initializeGL` ou `paintGL`, c'est-à-dire là
        où Qt a déjà rendu le contexte courant. On se garde bien de l'appeler
        de l'extérieur avec `makeCurrent` : Qt gère lui-même l'activation, et
        s'immiscer dans sa mécanique fait perdre les rafraîchissements suivants.
        """
        if not self._pret:
            return

        for programme in self._programmes.values():
            programme.supprimer()
        for cible in self._cibles.values():
            cible.supprimer()
        self._programmes.clear()
        self._cibles.clear()

        if self._reglage is None:
            self._reevaluer_reglage()
        fichier = FICHIER_NORME[self._reglage.famille]
        defines = {
            "N_TAPS": self._reglage.n_taps,
            "N_NOTCH": self._reglage.n_notch,
        }

        etapes = {"decodage": {}}
        if self._reglage.famille == "SECAM":
            etapes["preparation"] = {"PASSE_PREPARATION": None}
            etapes["codage"] = {"PASSE_CODAGE": None}
        else:
            etapes["codage"] = {"PASSE_CODAGE": None}

        for nom, supplement in etapes.items():
            source = assembler(fichier, {**defines, **supplement})
            self._programmes[nom] = Programme(
                self._sommet, source, f"{self._reglage.norme.code}/{nom}"
            )

        # Le magnétoscope partage l'entête commun : il a besoin de `phase()`,
        # sans laquelle il ne saurait ni descendre ni remonter la chrominance.
        self._n_vhs = longueur_vhs(
            self.parametres.qualite,
            self._reglage.largeur,
            self._reglage.norme.echantillons_par_ligne,
        )
        self._programmes["vhs"] = Programme(
            self._sommet, assembler("vhs.glsl", {**defines, "N_VHS": self._n_vhs}),
            f"{self._reglage.norme.code}/vhs",
        )

        largeur, hauteur = self._reglage.largeur, self._reglage.hauteur
        self._cibles["composite"] = Cible(largeur, hauteur, GL.GL_R16F)
        # Deux tampons pour la cassette : une génération de copie repasse par
        # toute la chaîne, et l'on ne peut pas lire et écrire la même texture
        # dans une même passe.
        self._cibles["vhs_a"] = Cible(largeur, hauteur, GL.GL_R16F)
        self._cibles["vhs_b"] = Cible(largeur, hauteur, GL.GL_R16F)
        self._cibles["resultat"] = Cible(largeur, hauteur, GL.GL_RGBA8)

        # Le halo travaille au quart de la résolution. Il est flou par
        # définition : y consacrer la pleine résolution ne changerait rien à
        # l'image et coûterait seize fois plus.
        quart = (max(16, largeur // 4), max(16, hauteur // 4))
        for nom in ("halo_a", "halo_b"):
            self._cibles[nom] = Cible(*quart, GL.GL_RGBA16F, GL.GL_LINEAR)
        if self._reglage.famille == "SECAM":
            self._cibles["prepare"] = Cible(largeur, hauteur, GL.GL_RG32F)
            self._cibles["scan_a"] = Cible(largeur, hauteur, GL.GL_R32F)
            self._cibles["scan_b"] = Cible(largeur, hauteur, GL.GL_R32F)

        # Les unités de texture ne changent jamais : on les fixe une fois.
        for programme in self._programmes.values():
            programme.utiliser()
            programme.definir("u_source", UNITE_SOURCE)
            programme.definir("u_composite", UNITE_COMPOSITE)
            programme.definir("u_prepare", UNITE_PREPARE)
            programme.definir("u_scan", UNITE_SCAN)
            programme.definir("u_vhs_entree", UNITE_VHS)

        self._programme_scan.utiliser()
        self._programme_scan.definir("u_entree", 0)
        self._programme_presentation.utiliser()
        self._programme_presentation.definir("u_image", 0)

        self._recompiler = False

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def definir_image(self, image: np.ndarray) -> None:
        """Fournit l'image à afficher, en RGB 8 bits, de forme (H, W, 3)."""
        self._image = image
        self._image_a_televerser = True
        if self.parametres.animer:
            self._numero_image += 1
        self.update()

    def appliquer(self, parametres: ParametresRendu) -> None:
        self.parametres = parametres
        self._reevaluer_reglage()
        self.update()

    def _largeur_affichee(self) -> int:
        """Largeur, en pixels physiques, qu'occupe réellement l'image à l'écran."""
        ratio = self.devicePixelRatioF()
        largeur = max(1, int(self.width() * ratio))
        hauteur = max(1, int(self.height() * ratio))
        echelle, _ = self._cadrage(largeur, hauteur)
        return max(64, int(round(echelle[0] * largeur)))

    def _reevaluer_reglage(self) -> bool:
        """Recalcule le jeu de constantes si la norme, la qualité ou la grille change.

        Le calcul coûte quelques millisecondes de conception de filtres, mais
        il est fait tout de suite plutôt que reporté : l'interface doit pouvoir
        décrire la norme courante sans attendre le prochain rendu. Seul le
        travail OpenGL — compilation et allocation — est repoussé dans `paintGL`.
        """
        norme = obtenir_norme(self.parametres.norme)
        largeur = self.parametres.largeur_grille(norme, self._largeur_affichee())
        cle = (self.parametres.norme, self.parametres.qualite, largeur)
        if cle == self._cle_reglage:
            return False
        self._cle_reglage = cle
        self._reglage = reglage(self.parametres.norme, self.parametres.qualite, largeur)
        self._recompiler = True
        return True

    def pixels_par_ligne(self) -> float:
        """Nombre de pixels d'écran qui reviennent à une ligne de balayage.

        La grandeur décide de ce que la fenêtre est capable de montrer, et
        aucun raffinement de shader ne la contourne. Restituer un motif d'une
        ligne claire et d'une ligne sombre demande deux pixels par ligne, et
        Shannon ne se négocie pas : en dessous, le motif ne peut être
        qu'atténué — c'est ce que fait l'intégration analytique du profil — ou
        replié, ce qui donne un moirage. En 625 lignes il faut donc une fenêtre
        d'au moins 1 152 pixels de haut pour que les lignes existent vraiment,
        et le double pour qu'elles soient franches.
        """
        if self._reglage is None:
            return 0.0
        ratio = self.devicePixelRatioF()
        largeur = max(1, int(self.width() * ratio))
        hauteur = max(1, int(self.height() * ratio))
        echelle, _ = self._cadrage(largeur, hauteur)
        return echelle[1] * hauteur / self._reglage.hauteur

    def description(self) -> str:
        if self._reglage is None:
            return ""
        finesse = self.pixels_par_ligne()
        if finesse >= 2.0:
            note = f"{finesse:.2f} pixel par ligne"
        else:
            note = f"{finesse:.2f} pixel par ligne — sous la limite de Shannon"
        return f"{self._reglage.description()} · {note}"

    def rendre_pour_export(self, largeur: int, hauteur: int) -> np.ndarray | None:
        """Rend une image complète, effets de tube compris, hors écran.

        C'est ce que l'export MP4 enregistre : non pas l'image décodée nue,
        mais **ce que la fenêtre montre** — courbure, réponse du tube, halo,
        lignes de balayage. Exporter autre chose serait déroutant : on
        enregistre ce qu'on a réglé.

        Comme pour `image_rendue`, la demande est déposée puis honorée à
        l'intérieur de la passe de rendu, jamais depuis l'extérieur.
        """
        if not self._pret:
            return None
        self._export_demande = (int(largeur), int(hauteur))
        self._export = None
        self.update()
        QtWidgets.QApplication.processEvents()
        return self._export

    def _rendre_export(self) -> None:
        largeur, hauteur = self._export_demande
        cible = self._cibles.get("export")
        if cible is None or (cible.largeur, cible.hauteur) != (largeur, hauteur):
            if cible is not None:
                cible.supprimer()
            cible = Cible(largeur, hauteur, GL.GL_RGBA8, GL.GL_LINEAR)
            self._cibles["export"] = cible

        self._passe_presentation(cible)

        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, cible.fbo)
        donnees = GL.glReadPixels(0, 0, largeur, hauteur, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
        tableau = np.frombuffer(donnees, dtype=np.uint8).reshape(hauteur, largeur, 3)
        self._export = tableau[::-1].copy()
        self._export_demande = None

    def image_rendue(self) -> np.ndarray | None:
        """Relit le résultat décodé, à la géométrie de la norme. Pour les tests.

        La relecture est demandée puis effectuée **à l'intérieur** de la passe
        de rendu. Attraper le contexte depuis l'extérieur avec `makeCurrent`
        paraît plus direct, mais Qt gère lui-même l'activation du contexte
        autour de `paintGL` : intervenir entre les deux fait silencieusement
        ignorer les demandes de rafraîchissement suivantes, et l'on relit
        alors une image périmée sans le moindre message d'erreur.
        """
        if not self._pret or "resultat" not in self._cibles:
            return None
        self._capture_demandee = True
        self._capture = None
        self.update()
        QtWidgets.QApplication.processEvents()
        return self._capture

    def _capturer(self) -> None:
        cible = self._cibles["resultat"]
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, cible.fbo)
        donnees = GL.glReadPixels(
            0, 0, cible.largeur, cible.hauteur, GL.GL_RGB, GL.GL_UNSIGNED_BYTE
        )
        tableau = np.frombuffer(donnees, dtype=np.uint8).reshape(
            cible.hauteur, cible.largeur, 3
        )
        # OpenGL rend l'origine en bas ; l'image, elle, se lit du haut.
        self._capture = tableau[::-1].copy()
        self._capture_demandee = False

    # ------------------------------------------------------------------
    # Rendu
    # ------------------------------------------------------------------

    def paintGL(self) -> None:
        if not self._pret:
            return
        # En mode « résolution de l'écran », la grille suit la taille de la
        # fenêtre : on vérifie à chaque image si elle a changé.
        if self.parametres.echantillonnage == "ecran" or self._reglage is None:
            self._reevaluer_reglage()
        if self._recompiler:
            self._construire()

        self._relire_chronometre()
        GL.glBeginQuery(GL.GL_TIME_ELAPSED, self._requetes[self._requete_courante])

        if self._image is not None and self._image_a_televerser:
            self._texture_source.televerser(self._image)
            self._image_a_televerser = False

        if self._image is not None:
            if self._reglage.famille == "SECAM":
                self._passe_preparation()
                self._passes_scan()
            self._passe_codage()
            if self.parametres.vhs_actif:
                self._passes_vhs()
            self._passe_decodage()
            if self._capture_demandee:
                self._capturer()
            if self.parametres.halo_intensite > 0.0:
                self._passes_halo()
            if self._export_demande is not None:
                self._rendre_export()

        self._passe_presentation()

        GL.glEndQuery(GL.GL_TIME_ELAPSED)
        self._requete_en_vol = True

    def _relire_chronometre(self) -> None:
        """Relit la requête de l'image précédente, si son résultat est prêt.

        On alterne entre deux requêtes et on ne relit jamais celle qu'on vient
        d'émettre : attendre son résultat synchroniserait le processeur sur la
        carte graphique, ce qui est précisément ce qu'on veut éviter.
        """
        if not self._requete_en_vol:
            return
        precedente = self._requetes[self._requete_courante]
        if GL.glGetQueryObjectiv(precedente, GL.GL_QUERY_RESULT_AVAILABLE):
            nanosecondes = GL.glGetQueryObjectuiv(precedente, GL.GL_QUERY_RESULT)
            self._requete_en_vol = False
            self._requete_courante = 1 - self._requete_courante
            if nanosecondes > 0:
                self.duree_gpu = nanosecondes * 1e-9
                self._instants.append(self.duree_gpu)
                if len(self._instants) >= 20:
                    moyenne = sum(self._instants) / len(self._instants)
                    self._instants.clear()
                    if moyenne > 0:
                        self.fps_mesure.emit(1.0 / moyenne)

    # -- uniformes communs ---------------------------------------------

    def _uniformes_communs(self, programme: Programme) -> None:
        p = self.parametres
        r = self._reglage
        programme.definir_tous(
            {k: v for k, v in r.uniformes.items() if k != "u_frac_image"}
        )
        programme.definir(
            "u_phase_image",
            float(np.mod(r.uniformes["u_frac_image"] * self._numero_image, 1.0)),
        )
        programme.definir("u_amplitude_chroma", float(p.amplitude_chroma))
        programme.definir("u_saturation", float(p.saturation))
        programme.definir("u_phase_diff", float(np.deg2rad(p.phase_differentielle)))
        programme.definir("u_gain_diff", float(p.gain_differentiel))
        programme.definir("u_bruit", float(p.sigma_bruit()))
        programme.definir("u_graine", float((self._numero_image % 1024) * 0.6180339887))
        programme.definir("u_separateur", int(p.separateur))
        programme.definir("u_ligne_retard", int(p.ligne_retard))

    # -- passes ---------------------------------------------------------

    def _passe_preparation(self) -> None:
        cible = self._cibles["prepare"]
        cible.activer()
        programme = self._programmes["preparation"]
        programme.utiliser()
        self._uniformes_communs(programme)
        self._texture_source.lier(UNITE_SOURCE)
        self._quad.dessiner()

    def _passes_scan(self) -> None:
        """Somme préfixe par doublement récursif.

        Dix passes pour une ligne de 920 points, chacune ne lisant que deux
        texels. On alterne entre deux cibles — on ne peut pas lire et écrire
        la même texture dans une même passe — et la première lit directement
        le canal rouge de la texture de préparation.
        """
        largeur, hauteur = self._reglage.largeur, self._reglage.hauteur
        a, b = self._cibles["scan_a"], self._cibles["scan_b"]

        self._programme_scan.utiliser()
        self._programme_scan.definir("u_taille", (float(largeur), float(hauteur)))

        texture_source = self._cibles["prepare"].texture
        destination = a
        ecart = 1

        while ecart < largeur:
            destination.activer()
            self._programme_scan.definir("u_ecart", float(ecart))
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture_source)
            self._quad.dessiner()

            texture_source = destination.texture
            destination = b if destination is a else a
            ecart *= 2

        self._texture_scan = texture_source

    def _passe_codage(self) -> None:
        # Sans cassette, c'est la sortie du codeur que le décodeur lit.
        self._texture_composite = self._cibles["composite"]
        cible = self._cibles["composite"]
        cible.activer()
        programme = self._programmes["codage"]
        programme.utiliser()
        self._uniformes_communs(programme)
        self._texture_source.lier(UNITE_SOURCE)
        if self._reglage.famille == "SECAM":
            self._cibles["prepare"].lier(UNITE_PREPARE)
            GL.glActiveTexture(GL.GL_TEXTURE0 + UNITE_SCAN)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture_scan)
        self._quad.dessiner()

    def _passes_vhs(self) -> None:
        """Une passe par génération de copie.

        Une copie de copie repasse réellement par toute la chaîne — c'est ce
        qui rendait les cassettes échangées entre amis si reconnaissables — et
        l'on enchaîne donc autant de passes que de générations, en alternant
        entre deux tampons.
        """
        p = self.parametres
        reglage = self._reglage
        bande_luma, bande_chroma = p.bandes_vhs()

        programme = self._programmes["vhs"]
        programme.utiliser()
        self._uniformes_communs(programme)

        noyaux = noyaux_vhs(self._n_vhs, reglage.f_ech, bande_luma, bande_chroma)
        programme.definir("u_vhs_noyau_luma", noyaux["luma"])
        programme.definir("u_vhs_noyau_douce", noyaux["douce"])
        programme.definir("u_vhs_noyau_chroma", noyaux["chroma"])

        usure = float(np.clip(p.vhs_usure, 0.0, 1.0))
        # Arrondi à l'échantillon, pour la même raison que la gigue : la
        # lecture et la phase de démodulation doivent désigner le même point.
        programme.definir(
            "u_vhs_retard", float(round(RETARD_CHROMA_VHS * reglage.f_ech))
        )
        programme.definir(
            "u_vhs_gigue",
            float(p.vhs_gigue) * 0.30e-6 * (0.4 + 0.6 * usure) * reglage.f_ech,
        )
        programme.definir("u_vhs_depassement", float(p.vhs_depassement))
        programme.definir("u_vhs_bruit_luma", 0.005 * (0.4 + usure))
        programme.definir("u_vhs_bruit_chroma", 0.004 * (0.4 + usure))

        # NOMBRE de pertes attendu par image — et non une probabilité par
        # segment. Le shader tire les positions plutôt que de tester chacune
        # d'elles ; c'est ce qui lui permet de descendre à des taux réalistes,
        # une bande VHS neuve étant spécifiée à dix ou vingt pertes par MINUTE.
        #
        # L'échelle est quadratique : le bas du curseur doit rester discret et
        # le haut spectaculaire.
        programme.definir(
            "u_vhs_abandons",
            3.0 * float(p.vhs_abandons) ** 2 * (0.2 + 0.8 * usure),
        )
        programme.definir("u_vhs_commutation", 6.0 if p.vhs_commutation else 0.0)

        source = self._cibles["composite"]
        a, b = self._cibles["vhs_a"], self._cibles["vhs_b"]
        destination = a

        for generation in range(max(1, int(p.vhs_generation))):
            destination.activer()
            # Le numéro d'image entre dans la graine : sans lui, le même
            # morceau de bande repasserait à chaque image et les défauts
            # resteraient figés d'un bout à l'autre du film. En pause, en
            # revanche, le compteur ne bouge plus et le motif se fige — ce
            # qui est exactement ce que fait un magnétoscope sur arrêt sur
            # image, où la même piste est relue en boucle.
            programme.definir(
                "u_vhs_graine",
                float(17.0 * generation + 3.0
                      + (self._numero_image % 4096) * 1.6180339887),
            )
            source.lier(UNITE_VHS)
            self._quad.dessiner()
            source = destination
            destination = b if destination is a else a

        self._texture_composite = source

    def _passe_decodage(self) -> None:
        cible = self._cibles["resultat"]
        cible.activer()
        programme = self._programmes["decodage"]
        programme.utiliser()
        self._uniformes_communs(programme)
        self._texture_composite.lier(UNITE_COMPOSITE)
        self._quad.dessiner()

    def _passes_halo(self) -> None:
        """Extraction, flou horizontal, flou vertical — au quart de résolution."""
        p = self.parametres
        source = self._cibles["resultat"]
        a, b = self._cibles["halo_a"], self._cibles["halo_b"]
        taille_quart = (float(a.largeur), float(a.hauteur))

        # Le rayon est donné en fraction de la hauteur d'image ; on le convertit
        # en texels du tampon réduit, ce qui le rend indépendant de la grille.
        sigma = max(0.05, p.halo_rayon * a.hauteur)

        a.activer()
        self._programme_halo_extraction.utiliser()
        self._programme_halo_extraction.definir("u_image", 0)
        self._programme_halo_extraction.definir(
            "u_taille", (float(source.largeur), float(source.hauteur))
        )
        # Le seuil se règle en niveau AFFICHÉ — c'est ainsi qu'on le pense en
        # tournant le bouton — mais se compare en LUMIÈRE, seul domaine où
        # additionner des sources a un sens. La conversion se fait ici.
        gamma = float(self._reglage.norme.gamma_affichage)
        bas = float(np.clip(p.halo_seuil, 0.0, 0.99)) ** gamma
        haut = float(np.clip(p.halo_seuil + 0.22, 0.02, 1.0)) ** gamma
        self._programme_halo_extraction.definir("u_seuil", bas)
        self._programme_halo_extraction.definir("u_seuil_haut", max(haut, bas + 1e-4))
        self._programme_halo_extraction.definir("u_gamma", gamma)
        source.lier(0)
        self._quad.dessiner()

        self._programme_halo_flou.utiliser()
        self._programme_halo_flou.definir("u_image", 0)
        self._programme_halo_flou.definir("u_taille", taille_quart)
        self._programme_halo_flou.definir("u_sigma", float(sigma))

        for cible, entree, direction in ((b, a, (1.0, 0.0)), (a, b, (0.0, 1.0))):
            cible.activer()
            self._programme_halo_flou.definir("u_direction", direction)
            entree.lier(0)
            self._quad.dessiner()

    def _passe_presentation(self, cible=None) -> None:
        """Dessine l'image finale, dans la fenêtre ou dans une cible hors écran.

        Le second cas sert à l'export : la géométrie du tube — courbure,
        arrondi des coins, pas des lignes de balayage — se calcule à partir de
        la taille de la SURFACE VISÉE, pas de celle de la fenêtre. Exporter en
        1440 points de haut depuis une fenêtre de 700 donne donc, et c'est
        voulu, des lignes de balayage bien plus franches : il y a deux fois
        plus de pixels pour les porter.
        """
        if cible is None:
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            ratio = self.devicePixelRatioF()
            largeur = max(1, int(self.width() * ratio))
            hauteur = max(1, int(self.height() * ratio))
            GL.glViewport(0, 0, largeur, hauteur)
        else:
            cible.activer()
            largeur, hauteur = cible.largeur, cible.hauteur
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        if "resultat" not in self._cibles:
            return

        echelle, decalage = self._cadrage(largeur, hauteur)

        p = self.parametres
        programme = self._programme_presentation
        programme.utiliser()
        programme.definir("u_taille_source",
                          (float(self._reglage.largeur), float(self._reglage.hauteur)))
        programme.definir("u_taille_ecran", (float(largeur), float(hauteur)))
        programme.definir("u_echelle", echelle)
        programme.definir("u_decalage", decalage)
        programme.definir("u_lignes", float(p.lignes_balayage))
        programme.definir("u_masque", float(p.masque_tube))
        programme.definir("u_luminosite", float(p.luminosite))
        programme.definir(
            "u_sigma_tube",
            sigma_du_tube(p.definition_tube, self._reglage.largeur),
        )
        # Géométrie de la dalle. Les demi-dimensions sont exprimées en
        # demi-diagonales d'image, ce qui rend le rayon de courbure
        # indépendant du format et de la résolution.
        aspect = echelle[0] * largeur / max(echelle[1] * hauteur, 1.0)
        diagonale = math.hypot(aspect, 1.0)
        programme.definir("u_demi_largeur", float(aspect / diagonale))
        programme.definir("u_demi_hauteur", float(1.0 / diagonale))
        programme.definir(
            "u_rayon_dalle", float(1.6 / max(p.courbure, 0.02))
        )
        # Distance d'observation : six demi-diagonales, soit environ 1,6 m
        # devant un tube de 21 pouces. C'est ce qui donne la perspective ;
        # à l'infini, la dalle ne se creuserait plus, elle s'étirerait.
        programme.definir("u_distance_oeil", 6.0)
        # Exposant de la superellipse : très grand pour des angles vifs, 2,2
        # pour un coin franchement rond.
        programme.definir(
            "u_coins",
            0.0 if p.arrondi_coins <= 0.0 else float(12.0 - 9.8 * min(p.arrondi_coins, 1.0)),
        )

        programme.definir("u_halo", 1)
        programme.definir("u_halo_intensite", float(p.halo_intensite))
        programme.definir("u_gamma", float(self._reglage.norme.gamma_affichage))
        if p.halo_intensite > 0.0:
            self._cibles["halo_a"].lier(1)

        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._cibles["resultat"].texture)
        # Les mipmaps servent au cas inverse du précédent : quand l'image est
        # affichée PLUS PETITE que la grille de calcul, un simple filtrage
        # bilinéaire replierait le grain fin de la sous-porteuse en un moirage
        # grossier, bien plus visible que le grain lui-même.
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        GL.glTexParameteri(
            GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR
        )
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        self._quad.dessiner()

    def _cadrage(self, largeur: int, hauteur: int):
        """Facteur d'échelle et décalage pour insérer l'image dans la fenêtre."""
        if self._image is None or not self.parametres.conserver_proportions:
            return (1.0, 1.0), (0.0, 0.0)

        source = self._image.shape[1] / self._image.shape[0]
        fenetre = largeur / hauteur
        if source > fenetre:
            facteur = (1.0, fenetre / source)
        else:
            facteur = (source / fenetre, 1.0)
        decalage = (0.5 * (1.0 - facteur[0]), 0.5 * (1.0 - facteur[1]))
        return facteur, decalage
