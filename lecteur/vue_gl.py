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
UNITE_CHARGE, UNITE_ECLAIREMENT, UNITE_ECLAIREMENT_AVANT = 5, 6, 7

CHAMPS_AMORCAGE = 24
"""Trames de mise en régime de la cible, quand elle vient d'être allouée.

Une cible vide se décharge mal : la première trame sortirait trop sombre.
Une vraie caméra a le même défaut à l'allumage, mais on ne peut pas se le
permettre sur une image arrêtée, où il n'y aura jamais de trame suivante
pour rattraper. Vingt-quatre suffisent : le résidu est alors sous 10⁻⁶."""


@dataclass
class ParametresRendu:
    """Réglages modifiables à chaud, sans recompiler les shaders."""

    norme: str = "PAL-BG"
    qualite: str = "haute"

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

    tube_actif: bool = False
    tube_modele: str = "plumbicon-reportage"
    tube_faisceau: float = 1.30
    tube_anti_comete: float = 0.0
    tube_remanence: float = 0.35
    tube_genou: float = 0.10
    tube_charge_max: float = 6.0
    tube_pont: float = 0.0
    """Portée du pont temporel, en pixels. **Nul par défaut**, et c'est un choix.

    C'est une interpolation et non un phénomène : elle comble ce que
    l'échantillonnage temporel de la source a laissé vide, et elle le fait bien
    sur un reflet isolé. Sur une image chargée, en revanche, elle diverge du
    simulateur de référence — 41 % de blanc saturé contre 29 % sur une scène
    chaude en mouvement — parce que la tache de diffusion de la carte graphique
    est 23 % plus large que la gaussienne exacte, et que le pont amplifie cet
    écart le long de ses huit directions.

    On ne l'allume donc que pour ce à quoi il sert : un reflet vif et rapide qui
    sortirait en chapelet. Le reste du temps, il coûte plus qu'il ne rend."""
    tube_masquage: float = 1.0
    tube_biais: float = 0.02
    tube_eclat: float = 2.5
    tube_seuil: float = 0.94
    tube_diffusion: float = 0.009
    tube_voile: float = 0.35
    tube_voile_rayon: float = 0.06
    tube_desalignement: float = 2.0
    """La caméra à tubes, tout en amont de la chaîne.

    `tube_modele` n'est qu'une étiquette : c'est l'interface qui, en choisissant
    un modèle, pose les six réglages qui suivent. Le moteur ne consulte jamais
    ce champ — il ne doit y avoir qu'une façon de décrire une caméra, et ce sont
    ses caractéristiques.

    Mêmes réglages que `tvcolor.tube.ParametresTube`, à plat. `desalignement`
    est ici en pixels au coin de l'image, comme dans le simulateur de
    référence ; le shader, lui, reçoit une fraction d'écran."""

    cadence_source: float = 0.0
    """Images par seconde de la source, ou 0 si on l'ignore.

    Sert uniquement à la caméra, mais elle en a absolument besoin. Un tube se
    décharge une fois par TRAME — cinquante fois par seconde en 625 lignes — et
    non une fois par image. Une vidéo à 25 im/s ne fournit donc qu'une image
    pour deux trames : sans cette cadence, la cible n'avancerait que d'une trame
    par image et toutes les traînées dureraient exactement deux fois trop
    longtemps. C'est la faute qu'avait le premier jet, et elle ne se voyait pas
    sur une mesure faite en trames — seulement à la montre."""

    animer: bool = True
    conserver_proportions: bool = True

    comparaison: bool = False
    """Volet de comparaison : à gauche la vidéo, à droite le téléviseur.

    La position du volet n'est **pas** ici, et c'est délibéré. Elle vient de la
    souris, que seule la vue connaît ; la mettre dans cette dataclasse
    obligerait le panneau de réglages à la relire et à la réécrire à chaque
    application, et le premier clic sur un curseur ramènerait le volet où il
    était. La vue la garde donc pour elle — voir `VueTelevision.volet`."""

    def parametres_tube(self):
        """Les mêmes réglages, sous la forme que `tvcolor.tube` attend.

        Déléguée pour la même raison que `bandes_vhs` : il n'y a pas deux
        tables de constantes dans ce projet, et `capacite()` — qui décide de la
        longueur des traînées — ne doit être écrite qu'une fois.
        """
        from tvcolor.tube import ParametresTube

        return ParametresTube(
            actif=self.tube_actif,
            faisceau=self.tube_faisceau,
            anti_comete=self.tube_anti_comete,
            remanence=self.tube_remanence,
            genou_remanence=self.tube_genou,
            charge_maximale=self.tube_charge_max,
            diffusion=self.tube_diffusion,
            voile=self.tube_voile,
            voile_rayon=self.tube_voile_rayon,
            pont_temporel=self.tube_pont,
            masquage=self.tube_masquage,
            lumiere_de_biais=self.tube_biais,
            eclat_reflets=self.tube_eclat,
            seuil_reflets=self.tube_seuil,
            desalignement=self.tube_desalignement,
        )

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
        self._images_recues = 0
        self._tube_image = -1
        self._tube_signature: tuple | None = None
        self._tube_a_amorcer = True
        self._dette_champs = 0.0
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

        self.volet = 0.5
        """Abscisse du volet de comparaison, en fraction de la largeur affichée.

        Suit la souris quand `parametres.comparaison` est vrai, et garde sa
        dernière valeur quand le pointeur quitte la vue — sans quoi le volet
        sauterait au bord dès qu'on va chercher un réglage dans le panneau."""

        self.setMinimumSize(320, 240)
        # Le survol suffit : on ne demande pas de tenir un bouton enfoncé pour
        # déplacer le volet, on passe la souris sur l'image.
        self.setMouseTracking(True)

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
        # Le tube analyseur ne dépend ni de la norme ni de la longueur des
        # noyaux : il est compilé une fois pour toutes. Deux programmes, parce
        # que la passe de charge et la passe de signal écrivent deux choses
        # différentes à partir du même calcul.
        self._programme_tube_emission = Programme(
            self._sommet,
            assembler_simple("tube.glsl", {"PASSE_EMISSION": None}),
            "tube/émission",
        )
        self._programme_tube_eclairement = Programme(
            self._sommet,
            assembler_simple("tube.glsl", {"PASSE_ECLAIREMENT": None}),
            "tube/éclairement",
        )
        self._programme_tube_pont = Programme(
            self._sommet,
            assembler_simple("tube.glsl", {"PASSE_PONT": None}),
            "tube/pont",
        )
        self._programme_tube_signal = Programme(
            self._sommet, assembler_simple("tube.glsl"), "tube/signal"
        )
        self._programme_tube_charge = Programme(
            self._sommet,
            assembler_simple("tube.glsl", {"PASSE_CHARGE": None}),
            "tube/charge",
        )
        self._programmes_tube = (
            self._programme_tube_emission,
            self._programme_tube_eclairement,
            self._programme_tube_pont,
            self._programme_tube_signal,
            self._programme_tube_charge,
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

        # La caméra : le signal lu, et les deux tampons de charge. Ce sont les
        # seules textures de ce moteur qui survivent d'une image à l'autre —
        # c'est la charge restée sur la cible qui fait la queue de comète.
        # Trente-deux bits, et non seize. La colorimétrie de la caméra fait un
        # aller-retour matriciel — contamination des filtres, puis son inverse —
        # dont la reconstruction procède par SOUSTRACTION : les erreurs
        # relatives d'un demi-flottant, dérisoires prises une à une, s'y
        # amplifient et coûtaient quatre niveaux sur 255 au milieu d'une barre
        # de couleur. La charge et l'éclairement montent donc en simple
        # précision. Mesuré : l'écart retombe sous le niveau de quantification.
        self._cibles["tube"] = Cible(largeur, hauteur, GL.GL_RGBA16F)
        self._cibles["eclairement"] = Cible(largeur, hauteur, GL.GL_RGBA32F)
        # Deux tampons pour l'éclairement d'avant le pont : celui-ci et celui
        # de l'image précédente. Le pont ne consulte qu'eux, jamais la charge —
        # c'est ce qui l'empêche de se nourrir de sa propre sortie.
        # Seize bits suffisent ici — l'émission est une fraction dans [0, 1] —
        # et la pyramide de mipmaps se reconstruit à chaque image : la moitié
        # de la bande passante s'y voit tout de suite.
        self._cibles["emis"] = Cible(largeur, hauteur, GL.GL_RGBA16F, mipmaps=True)
        self._cibles["eclairement_a"] = Cible(largeur, hauteur, GL.GL_RGBA32F)
        self._cibles["eclairement_b"] = Cible(largeur, hauteur, GL.GL_RGBA32F)
        for nom in ("charge_a", "charge_b"):
            self._cibles[nom] = Cible(largeur, hauteur, GL.GL_RGBA32F)
        self._tube_a_amorcer = True

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

        for programme in self._programmes_tube:
            programme.utiliser()
            programme.definir("u_source", UNITE_SOURCE)
            programme.definir("u_charge", UNITE_CHARGE)
            programme.definir("u_eclairement", UNITE_ECLAIREMENT)
            programme.definir("u_eclairement_avant", UNITE_ECLAIREMENT_AVANT)

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
        # Compté à part du numéro d'image : celui-ci sert la phase de
        # sous-porteuse et n'avance pas quand l'animation est arrêtée, alors
        # que la cible du tube doit se décharger chaque fois qu'une image
        # nouvelle se présente, et une seule fois.
        self._images_recues += 1
        if self.parametres.animer:
            self._numero_image += 1
        self.update()

    def appliquer(self, parametres: ParametresRendu) -> None:
        avant = self.parametres.comparaison
        self.parametres = parametres
        if parametres.comparaison != avant:
            # Le curseur en dit plus long qu'une case cochée à l'autre bout de
            # la fenêtre : dès qu'il change de forme au-dessus de l'image, on
            # comprend que le pointeur commande quelque chose.
            if parametres.comparaison:
                self.setCursor(QtCore.Qt.SplitHCursor)
            else:
                self.unsetCursor()
        self._reevaluer_reglage()
        self.update()

    def mouseMoveEvent(self, evenement):  # noqa: N802 - API Qt
        """Le volet suit le pointeur, en fraction de la largeur de la vue."""
        if self.parametres.comparaison and self.width() > 0:
            volet = min(max(evenement.x() / float(self.width()), 0.0), 1.0)
            if volet != self.volet:
                self.volet = volet
                self.update()
        super().mouseMoveEvent(evenement)

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
            if self.parametres.tube_actif:
                self._passes_tube()
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

    # -- la caméra ------------------------------------------------------

    def _lier_scene(self) -> None:
        """Branche sur l'unité de source ce que le codeur doit voir.

        Avec une caméra à tubes, ce n'est plus le fichier : c'est ce que le
        faisceau a bien voulu rendre de la cible.
        """
        if self.parametres.tube_actif:
            self._cibles["tube"].lier(UNITE_SOURCE)
        else:
            self._texture_source.lier(UNITE_SOURCE)

    def _uniformes_tube(self, programme: Programme) -> None:
        from tvcolor.tube import CONTAMINATION, RAYON_REFLET, matrice_masquage

        p = self.parametres
        largeur, hauteur = self._reglage.largeur, self._reglage.hauteur

        # Le rayon est isotrope À L'ÉCRAN, donc en 4:3, et non sur la grille de
        # calcul, qui est étirée : 920 points pour 576 lignes.
        rayon_y = RAYON_REFLET
        rayon_x = RAYON_REFLET * 3.0 / 4.0

        # Chacun des seize points de la couronne représente un morceau du
        # voisinage, et doit donc être lu dans un mipmap qui moyenne déjà ce
        # morceau : le tiers du rayon, mesuré sur la texture source.
        pixels = max(2.0, rayon_y * max(2, self._texture_source.hauteur) / 3.0)

        programme.utiliser()
        programme.definir("u_taille", (float(largeur), float(hauteur)))
        programme.definir("u_tube_rayon", (rayon_x, rayon_y))
        programme.definir("u_tube_lod", float(math.log2(pixels)))
        programme.definir("u_tube_faisceau", float(p.parametres_tube().capacite()))
        programme.definir("u_tube_remanence", float(p.tube_remanence))
        programme.definir("u_tube_genou", float(p.tube_genou))
        programme.definir("u_tube_charge_max", float(p.tube_charge_max))
        # La portée du pont est donnée en pixels d'une image 4:3 à pixels
        # carrés ; en coordonnées de texture elle est donc anisotrope, la
        # grille de calcul étant étirée.
        pont = float(p.tube_pont)
        programme.definir(
            "u_tube_pont", (pont / (4.0 / 3.0 * hauteur), pont / hauteur)
        )
        # Les deux matrices viennent de `tvcolor.tube` : la contamination des
        # filtres et son antidote électronique n'existent qu'à un seul endroit.
        programme.definir("u_tube_filtres", CONTAMINATION)
        programme.definir("u_tube_masquage", matrice_masquage(p.tube_masquage))
        programme.definir("u_tube_biais", float(p.tube_biais))
        programme.definir("u_tube_eclat", float(p.tube_eclat))
        programme.definir("u_tube_seuil", float(p.tube_seuil))
        # Les rayons sont donnés en fraction de la HAUTEUR, et doivent donc
        # être anisotropes en coordonnées de texture : la grille est étirée.
        # Un niveau de mipmap est une moyenne de boîte : une boîte de largeur
        # L a pour écart-type L/√12. Un rayon sigma donné en fraction de la
        # HAUTEUR correspond donc au niveau log2(√12 · sigma · hauteur).
        for nom, rayon in (("coeur", p.tube_diffusion), ("voile", p.tube_voile_rayon)):
            if rayon <= 0.0:
                programme.definir(f"u_tube_lod_{nom}", 0.0)
                programme.definir(f"u_tube_pas_{nom}", (0.0, 0.0))
                continue
            # Le « − 1 » n'est pas un ajustement : la tente à quatre prises
            # DOUBLE l'écart-type du noyau. Une boîte de côté L a l'écart-type
            # L/√12 = 0,289 L ; les prises à un demi-texel en ajoutent 0,5 L, et
            # les variances s'additionnent — soit 0,577 L au total. Il faut donc
            # une boîte deux fois plus petite. Sans cette division, la carte
            # graphique étalait deux fois trop : 38 % de blanc sur une scène
            # chaude contre 29 % pour le simulateur de référence.
            cote = math.sqrt(12.0) * rayon * hauteur / 2.0
            niveau = max(0.0, math.log2(max(cote, 1.0)))
            programme.definir(f"u_tube_lod_{nom}", float(niveau))
            # Un texel de ce niveau, en coordonnées de texture.
            echelle = 2.0**niveau
            programme.definir(
                f"u_tube_pas_{nom}", (echelle / largeur, echelle / hauteur)
            )
        programme.definir("u_tube_voile", float(p.tube_voile))
        # Le désalignement est donné en pixels au coin ; le shader travaille en
        # fraction d'écran, l'échelle étant rapportée à la demi-diagonale.
        demi_diagonale = 0.5 * math.hypot(largeur, hauteur)
        programme.definir("u_tube_ecart", float(p.tube_desalignement) / demi_diagonale)

    def _passe_eclairement(self) -> None:
        """Ce que l'objectif dépose vraiment sur la cible, pont temporel compris.

        La passe chère, et la seule : seize points de couverture pour
        reconnaître un reflet, et jusqu'à cent vingt-huit sondages pour combler
        ce que l'échantillonnage de la source a laissé vide. Elle ne tourne
        qu'une fois par image reçue ; les deux autres ne lisent que son
        résultat.
        """
        # 1. L'émission : l'excès, une fois la porte de couverture passée. La
        #    porte s'applique donc à la SOURCE de la lumière et non à sa
        #    destination — l'inverse laissait une barre blanche déborder sur sa
        #    voisine, et coûtait la transparence sur mire immobile.
        self._cibles["emis"].activer()
        self._programme_tube_emission.utiliser()
        self._texture_source.lier(UNITE_SOURCE)
        self._quad.dessiner()
        self._cibles["emis"].generer_mipmaps()

        # 2. L'optique : le cœur étroit et le voile large de l'objectif.
        source, avant = self._cibles["eclairement_a"], self._cibles["eclairement_b"]
        source.activer()
        self._programme_tube_eclairement.utiliser()
        self._texture_source.lier(UNITE_SOURCE)
        self._cibles["emis"].lier(UNITE_ECLAIREMENT)
        self._quad.dessiner()

        # Le pont dans SA passe, et lisant l'éclairement déjà filtré par la
        # porte de couverture. Le faire dans la passe précédente l'obligeait à
        # recalculer l'éclairement de ses sondages SANS la porte, faute de
        # pouvoir la refaire cent vingt-huit fois : un grand aplat écrêté
        # comptait alors comme un reflet neuf, et la tache blanche mangeait
        # l'image de proche en proche — 23 % à la première image, 85 % à la
        # dixième.
        self._cibles["eclairement"].activer()
        self._programme_tube_pont.utiliser()
        source.lier(UNITE_ECLAIREMENT)
        avant.lier(UNITE_ECLAIREMENT_AVANT)
        self._quad.dessiner()

        self._cibles["eclairement_a"], self._cibles["eclairement_b"] = avant, source

    def _passe_charge(self) -> None:
        """Une trame de pose : la cible intègre, le faisceau évacue ce qu'il peut."""
        source = self._cibles["charge_a"]
        destination = self._cibles["charge_b"]
        destination.activer()
        self._programme_tube_charge.utiliser()
        source.lier(UNITE_CHARGE)
        self._cibles["eclairement"].lier(UNITE_ECLAIREMENT)
        self._quad.dessiner()
        self._cibles["charge_a"], self._cibles["charge_b"] = destination, source

    def _passe_signal_tube(self) -> None:
        """Le courant de faisceau, c'est-à-dire le signal vidéo."""
        self._cibles["tube"].activer()
        self._programme_tube_signal.utiliser()
        self._cibles["charge_a"].lier(UNITE_CHARGE)
        self._cibles["eclairement"].lier(UNITE_ECLAIREMENT)
        self._quad.dessiner()

    def _passes_tube(self) -> None:
        """La caméra, en une ou deux passes selon qu'une image est arrivée.

        L'ORDRE COMPTE, et c'est le seul piège de cette passe. Les deux
        programmes lisent la charge que la trame PRÉCÉDENTE a laissée : le
        signal doit donc être lu avant que la charge ne soit mise à jour. Dans
        l'autre ordre, le signal serait celui d'une cible déjà déchargée —
        l'image sortirait à peu près juste, et la traînée aurait une trame de
        moins que ce que le modèle prescrit.

        Et l'on n'avance la cible que pour une image RÉELLEMENT nouvelle : sans
        cela, la longueur de la traînée dépendrait du nombre de redessins, donc
        de la taille de la fenêtre et de l'humeur du gestionnaire de fenêtres.
        """
        p = self.parametres
        # `tube_genou` doit figurer ici : l'oublier ferait garder à la cible
        # la charge laissée par un tout autre tube.
        signature = (
            p.tube_faisceau, p.tube_anti_comete, p.tube_remanence, p.tube_genou,
            p.tube_charge_max, p.tube_biais, p.tube_eclat, p.tube_seuil,
            p.tube_desalignement, p.tube_pont, p.tube_masquage,
            p.tube_diffusion, p.tube_voile, p.tube_voile_rayon,
        )
        if signature != self._tube_signature:
            self._tube_signature = signature
            self._tube_a_amorcer = True

        for programme in self._programmes_tube:
            self._uniformes_tube(programme)

        if self._tube_a_amorcer:
            self._cibles["charge_a"].effacer()
            self._cibles["charge_b"].effacer()
            self._passe_eclairement()
            for _ in range(CHAMPS_AMORCAGE):
                self._passe_charge()
            self._tube_a_amorcer = False
            self._tube_image = self._images_recues
            self._passe_signal_tube()
        elif self._images_recues != self._tube_image:
            # L'éclairement se recalcule sur la charge d'AVANT le dépôt : c'est
            # elle qui porte la trace que le pont doit rejoindre.
            self._passe_eclairement()
            self._passe_signal_tube()
            for _ in range(self._champs_a_rattraper()):
                self._passe_charge()
            self._tube_image = self._images_recues
        else:
            self._passe_signal_tube()

    def _champs_a_rattraper(self) -> int:
        """Nombre de trames que la cible doit poser pour l'image qui arrive.

        Une cible se décharge à la CADENCE TRAME de la norme — cinquante fois
        par seconde en 625 lignes — et la vidéo, elle, arrive à sa propre
        cadence. Une source à 25 im/s vaut donc deux trames par image, et une
        source à 24 im/s en vaut 2,08 : on garde la partie fractionnaire d'une
        image à l'autre plutôt que de l'arrondir à chaque fois, sans quoi la
        durée des traînées dériverait de 4 %.

        Sans cadence connue — une image fixe, un banc de mesure — on s'en tient
        à une trame par image, ce qui est la seule convention défendable.
        """
        cadence = float(self.parametres.cadence_source)
        if cadence <= 0.0:
            return 1

        self._dette_champs += self._reglage.norme.f_trame / cadence
        champs = int(self._dette_champs)
        self._dette_champs -= champs
        return champs

    # -- passes ---------------------------------------------------------

    def _passe_preparation(self) -> None:
        cible = self._cibles["prepare"]
        cible.activer()
        programme = self._programmes["preparation"]
        programme.utiliser()
        self._uniformes_communs(programme)
        self._lier_scene()
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
        self._lier_scene()
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

        programme.definir("u_comparaison", 1.0 if p.comparaison else 0.0)
        programme.definir("u_volet", float(self.volet))
        programme.definir("u_source_brute", 2)
        if p.comparaison:
            # La texture de source, et non la cible « tube » : à gauche du
            # volet on montre le fichier tel qu'il est entré, caméra comprise
            # dans ce qui est comparé.
            self._texture_source.lier(2)

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
