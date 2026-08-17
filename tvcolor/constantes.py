"""
Constantes normatives des trois systèmes de télévision couleur.

Sources : UIT-R BT.470-6 (systèmes M, B/G, I, D/K, L), BT.601-7,
SMPTE 170M (NTSC-M), EBU Tech. 3213 (primaires PAL/SECAM).

Toutes les fréquences sont en hertz, toutes les durées en secondes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Fréquences fondamentales
# ---------------------------------------------------------------------------

# Système M (525 lignes / 59,94 Hz).
#
# À l'origine, le noir et blanc utilisait exactement 60 Hz et f_H = 15 750 Hz.
# L'introduction de la couleur a imposé de décaler l'ensemble d'un facteur
# 1000/1001 pour éloigner la sous-porteuse son (4,5 MHz) du battement avec la
# sous-porteuse couleur. D'où les valeurs « bizarres » qui ont survécu jusqu'à
# aujourd'hui dans le monde de la vidéo (29,97 im/s, timecode drop-frame…).
F_TRAME_M = 60_000.0 / 1001.0          # 59,940059… Hz
F_LIGNE_M = 525.0 * F_TRAME_M / 2.0    # 15 734,264… Hz

# La sous-porteuse NTSC est un multiple DEMI-ENTIER de la fréquence ligne :
# 455/2 = 227,5. C'est la clé de l'entrelacement spectral (cf. cours, ch. 5)
# et la raison pour laquelle la phase tourne exactement de 180° d'une ligne
# à la suivante.
F_SC_NTSC = 455.0 / 2.0 * F_LIGNE_M    # 3 579 545,45… Hz

# Systèmes B/G/I/D/K/L (625 lignes / 50 Hz).
F_TRAME_625 = 50.0
F_LIGNE_625 = 625.0 * F_TRAME_625 / 2.0   # 15 625 Hz exactement

# La sous-porteuse PAL n'est pas un simple demi-entier : elle vaut
# (1135/4 + 1/625)·f_H. Le quart-entier 283,75 découle du décalage de phase
# de 90° par ligne nécessaire au PAL ; le terme +1/625 (un décalage de 25 Hz)
# corrige la visibilité résiduelle du motif de sous-porteuse d'une trame à
# l'autre (cf. cours, ch. 8).
F_SC_PAL = (1135.0 / 4.0 + 1.0 / 625.0) * F_LIGNE_625   # 4 433 618,75 Hz

# SECAM : deux sous-porteuses, multiples ENTIERS de f_H, une par composante.
F_SC_SECAM_B = 272.0 * F_LIGNE_625     # 4 250 000 Hz   (D'B, ligne « bleue »)
F_SC_SECAM_R = 282.0 * F_LIGNE_625     # 4 406 250 Hz   (D'R, ligne « rouge »)

# Excursions de fréquence SECAM (BT.470, système L).
SECAM_DEVIATION_B = 280_000.0          # Hz par unité de D'B
SECAM_DEVIATION_R = 230_000.0          # Hz par unité de D'R
SECAM_EXCURSION_MIN = -506_000.0       # butée basse, relative au repos
SECAM_EXCURSION_MAX = +350_000.0       # butée haute, relative au repos

# Préaccentuation basse fréquence SECAM : A(f) = (1 + j f/f1) / (1 + j f/(3 f1))
SECAM_F1 = 85_000.0                    # Hz

# Préaccentuation haute fréquence SECAM (« filtre cloche ») :
#   G(F) = M0 (1 + j 16 F) / (1 + j 1,26 F),  F = f/f0 - f0/f
SECAM_F0 = 4_286_000.0                 # Hz, fréquence de repos moyenne
SECAM_CLOCHE_A = 16.0
SECAM_CLOCHE_B = 1.26
SECAM_AMPLITUDE_REPOS = 0.115          # amplitude relative de la sous-porteuse au repos

# ---------------------------------------------------------------------------
# Matriçage luminance / différences de couleur
# ---------------------------------------------------------------------------

# Coefficients de luma. Ils proviennent de la seconde ligne de la matrice
# RGB→XYZ des primaires NTSC 1953 sous illuminant C (cf. colorimetrie.py, la
# dérivation est refaite numériquement et vérifiée par les tests). BT.470 les
# a conservés pour PAL et SECAM alors même que les primaires avaient changé —
# c'est une incohérence assumée, au nom de la compatibilité.
KR = 0.299
KG = 0.587
KB = 0.114

# Facteurs d'échelle des différences de couleur. Ils sont choisis pour que
# l'excursion crête du signal composite reste dans ±1/3 de l'amplitude vidéo
# sur les couleurs saturées (cf. cours, ch. 4).
FACTEUR_U = 0.492111              # U = 0,492 (B'-Y')
FACTEUR_V = 0.877283              # V = 0,877 (R'-Y')

# Rotation des axes I/Q de NTSC par rapport à U/V.
ANGLE_IQ_DEG = 33.0

# Facteurs SECAM (BT.470). Le signe négatif de D'R inverse la polarité du
# rouge : c'est un choix de norme, destiné à minimiser l'excursion crête.
FACTEUR_DB = +1.505
FACTEUR_DR = -1.902

# ---------------------------------------------------------------------------
# Niveaux
# ---------------------------------------------------------------------------

PIEDESTAL_NTSC_M = 0.075          # 7,5 IRE de « setup » (Amérique du Nord)
PIEDESTAL_ZERO = 0.0              # NTSC-J, PAL, SECAM : noir = niveau de suppression

BURST_CYCLES_NTSC = 9
BURST_PHASE_NTSC = 180.0          # degrés, soit l'axe -U
BURST_PHASE_PAL = 135.0           # ±45° autour de 180° : le « burst oscillant »
BURST_AMPLITUDE = 0.30            # relative à l'amplitude vidéo


# ---------------------------------------------------------------------------
# La voie son
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VoieSon:
    """Description de la porteuse son d'un système de télévision.

    Le son d'un téléviseur analogique ne voyage **pas** dans le signal vidéo :
    il occupe sa propre porteuse, plus haut dans le même canal radio, quelques
    mégahertz au-dessus de la porteuse image. Les deux voyagent ensemble,
    subissent le même bruit, et se retrouvent dans le même amplificateur à
    fréquence intermédiaire — c'est de cette cohabitation que naissent le
    ronflement de trame et le sifflement de ligne.

    Les récepteurs à *intercarrier*, qui sont la quasi-totalité d'entre eux
    depuis les années 1950, ne démodulent pas la porteuse son directement :
    ils exploitent le **battement** entre elle et la porteuse image, dont la
    fréquence est par construction la différence des deux — 4,5 MHz en système
    M, 5,5 en B/G, 6,5 en L. Le procédé est d'une stabilité remarquable, la
    dérive de l'oscillateur local s'annulant dans la soustraction. Il a un
    prix : toute modulation de phase parasite de la porteuse image se retrouve
    telle quelle sur le battement, et donc dans le haut-parleur.
    """

    decalage: float
    """Écart entre porteuse son et porteuse image, en hertz. C'est aussi, et
    exactement, la fréquence du battement intercarrier."""

    modulation: str
    """« FM » ou « AM ». Le système L, celui de la France, est le seul d'Europe
    occidentale à moduler son en amplitude — choix qui va de pair avec sa
    modulation vidéo positive, et qui rend son son bien plus fragile au bruit
    que celui de ses voisins."""

    deviation: float
    """Excursion de fréquence crête, en hertz. Sans objet en AM."""

    taux_am: float
    """Taux de modulation en AM. Sans objet en FM."""

    preaccentuation: float
    """Constante de temps de préaccentuation, en secondes. 50 µs en Europe,
    75 µs en Amérique du Nord. Zéro quand il n'y en a pas.

    Elle relève les aigus à l'émission pour les rabaisser à la réception. Le
    bruit d'un discriminateur FM croissant en fréquence — il est *triangulaire*
    et non blanc — l'abaissement de la réception attaque le bruit là où il est
    le plus fort, sans avoir touché au signal."""

    bande_audio: float
    """Bande passante audio, en hertz."""

    niveau_porteuse_db: float
    """Puissance de la porteuse son, en décibels sous la crête de la porteuse
    image. Toujours négative : le son est émis nettement plus faible que
    l'image, parce que la modulation de fréquence n'a pas besoin de plus."""


SON_M = VoieSon(
    decalage=4.5e6, modulation="FM", deviation=25e3, taux_am=0.0,
    preaccentuation=75e-6, bande_audio=15e3, niveau_porteuse_db=-10.0,
)
"""Système M. L'excursion n'est que de ±25 kHz, moitié de celle de l'Europe :
le canal de 6 MHz était trop étroit pour davantage. Le son du NTSC est donc,
toutes choses égales par ailleurs, plus bruité que celui du PAL."""

SON_BG = VoieSon(
    decalage=5.5e6, modulation="FM", deviation=50e3, taux_am=0.0,
    preaccentuation=50e-6, bande_audio=15e3, niveau_porteuse_db=-13.0,
)

SON_I = VoieSon(
    decalage=6.0e6, modulation="FM", deviation=50e3, taux_am=0.0,
    preaccentuation=50e-6, bande_audio=15e3, niveau_porteuse_db=-10.0,
)

SON_L = VoieSon(
    decalage=6.5e6, modulation="AM", deviation=0.0, taux_am=0.54,
    preaccentuation=0.0, bande_audio=15e3, niveau_porteuse_db=-10.0,
)
"""Système L, celui de la France. Son en **amplitude**, sans préaccentuation.

C'est la particularité la plus audible du SECAM-L, et elle n'a rien de
théorique : privée du gain de démodulation de la FM — une vingtaine de
décibels — la voie son se dégrade en même temps que l'image, au lieu de rester
propre bien après que celle-ci ait commencé à neiger."""

SON_DK = VoieSon(
    decalage=6.5e6, modulation="FM", deviation=50e3, taux_am=0.0,
    preaccentuation=50e-6, bande_audio=15e3, niveau_porteuse_db=-13.0,
)


# ---------------------------------------------------------------------------
# Description d'une norme
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Norme:
    """Jeu complet de paramètres décrivant un système de télévision couleur."""

    code: str                     # identifiant court, ex. « PAL-BG »
    nom: str                      # libellé lisible
    famille: str                  # « NTSC » | « PAL » | « SECAM »

    lignes_totales: int
    lignes_actives: int
    f_trame: float                # trames par seconde (2 trames = 1 image)
    f_ligne: float                # Hz
    duree_ligne_active: float     # s, portion utile d'une ligne

    f_sc: float                   # sous-porteuse principale
    f_sc_secondaire: float | None # SECAM uniquement : sous-porteuse « bleue »

    bande_y: float                # Hz, bande passante de luminance
    bande_c1: float               # Hz, bande de U (ou I, ou D'B)
    bande_c2: float               # Hz, bande de V (ou Q, ou D'R)

    piedestal: float              # niveau de noir au-dessus de la suppression
    gamma_affichage: float        # gamma supposé du tube (BT.470)
    primaires: str                # clef dans colorimetrie.PRIMAIRES

    base_chroma: str = "UV"       # « UV », « IQ » ou « DRDB »
    surechantillonnage: int = 4   # f_échantillonnage = N · f_sc
    son: VoieSon = SON_BG         # porteuse son du système

    # Champs dérivés, remplis par __post_init__
    duree_ligne: float = field(init=False)
    f_echantillonnage: float = field(init=False)
    echantillons_par_ligne: int = field(init=False)
    echantillons_ligne_totale: int = field(init=False)
    marge_suppression: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "duree_ligne", 1.0 / self.f_ligne)
        # On échantillonne le composite à un multiple entier de la sous-porteuse
        # principale : la phase se calcule alors exactement et la démodulation
        # synchrone tombe naturellement sur les axes I/Q.
        f_e = self.surechantillonnage * self.f_sc
        object.__setattr__(self, "f_echantillonnage", f_e)
        actifs = int(round(f_e * self.duree_ligne_active))
        total = int(round(f_e * self.duree_ligne))
        object.__setattr__(self, "echantillons_par_ligne", actifs)
        object.__setattr__(self, "echantillons_ligne_totale", total)
        # Temps de suppression ligne, réparti de part et d'autre de l'image.
        # Ce n'est pas du remplissage : c'est le délai dont disposent tous les
        # filtres du récepteur pour s'établir avant que l'image ne commence.
        object.__setattr__(self, "marge_suppression", max(0, (total - actifs) // 2))

    @property
    def images_par_seconde(self) -> float:
        return self.f_trame / 2.0

    @property
    def cycles_sous_porteuse_par_ligne(self) -> float:
        """Nombre de cycles de sous-porteuse dans une ligne complète.

        La partie fractionnaire donne l'avance de phase d'une ligne à la
        suivante : 0,5 en NTSC (180°), 0,7516 en PAL (270,6°).
        """
        return self.f_sc / self.f_ligne

    @property
    def avance_phase_par_ligne_deg(self) -> float:
        return (self.cycles_sous_porteuse_par_ligne % 1.0) * 360.0

    def __str__(self) -> str:  # pragma: no cover - confort d'affichage
        return f"{self.nom} ({self.lignes_totales}/{self.f_trame:.2f})"


# ---------------------------------------------------------------------------
# Les normes concrètes
# ---------------------------------------------------------------------------

NTSC_M = Norme(
    code="NTSC-M",
    nom="NTSC-M (Amérique du Nord)",
    famille="NTSC",
    lignes_totales=525,
    lignes_actives=480,
    f_trame=F_TRAME_M,
    f_ligne=F_LIGNE_M,
    duree_ligne_active=52.6e-6,
    f_sc=F_SC_NTSC,
    f_sc_secondaire=None,
    bande_y=4.2e6,
    bande_c1=1.3e6,      # I, l'axe orange-cyan, bien perçu par l'œil
    bande_c2=0.4e6,      # Q, l'axe vert-magenta, mal perçu → on peut le brider
    piedestal=PIEDESTAL_NTSC_M,
    gamma_affichage=2.2,
    primaires="smpte-c",
    base_chroma="IQ",
    son=SON_M,
)

NTSC_J = Norme(
    code="NTSC-J",
    nom="NTSC-J (Japon, sans piédestal)",
    famille="NTSC",
    lignes_totales=525,
    lignes_actives=480,
    f_trame=F_TRAME_M,
    f_ligne=F_LIGNE_M,
    duree_ligne_active=52.6e-6,
    f_sc=F_SC_NTSC,
    f_sc_secondaire=None,
    bande_y=4.2e6,
    bande_c1=1.3e6,
    bande_c2=0.4e6,
    piedestal=PIEDESTAL_ZERO,
    gamma_affichage=2.2,
    primaires="smpte-c",
    base_chroma="IQ",
    son=SON_M,
)

NTSC_1953 = Norme(
    code="NTSC-1953",
    nom="NTSC 1953 (primaires d'origine)",
    famille="NTSC",
    lignes_totales=525,
    lignes_actives=480,
    f_trame=F_TRAME_M,
    f_ligne=F_LIGNE_M,
    duree_ligne_active=52.6e-6,
    f_sc=F_SC_NTSC,
    f_sc_secondaire=None,
    bande_y=4.2e6,
    bande_c1=1.3e6,
    bande_c2=0.4e6,
    piedestal=PIEDESTAL_NTSC_M,
    gamma_affichage=2.2,
    primaires="ntsc1953",
    base_chroma="IQ",
    son=SON_M,
)

PAL_BG = Norme(
    code="PAL-BG",
    nom="PAL-B/G (Europe continentale)",
    famille="PAL",
    lignes_totales=625,
    lignes_actives=576,
    f_trame=F_TRAME_625,
    f_ligne=F_LIGNE_625,
    duree_ligne_active=51.95e-6,
    f_sc=F_SC_PAL,
    f_sc_secondaire=None,
    bande_y=5.0e6,
    bande_c1=1.3e6,
    bande_c2=1.3e6,
    piedestal=PIEDESTAL_ZERO,
    gamma_affichage=2.8,
    primaires="ebu",
    base_chroma="UV",
    son=SON_BG,
)

PAL_I = Norme(
    code="PAL-I",
    nom="PAL-I (Royaume-Uni, Irlande)",
    famille="PAL",
    lignes_totales=625,
    lignes_actives=576,
    f_trame=F_TRAME_625,
    f_ligne=F_LIGNE_625,
    duree_ligne_active=51.95e-6,
    f_sc=F_SC_PAL,
    f_sc_secondaire=None,
    bande_y=5.5e6,
    bande_c1=1.3e6,
    bande_c2=1.3e6,
    piedestal=PIEDESTAL_ZERO,
    gamma_affichage=2.8,
    primaires="ebu",
    base_chroma="UV",
    son=SON_I,
)

SECAM_L = Norme(
    code="SECAM-L",
    nom="SECAM-L (France)",
    famille="SECAM",
    lignes_totales=625,
    lignes_actives=576,
    f_trame=F_TRAME_625,
    f_ligne=F_LIGNE_625,
    duree_ligne_active=51.95e-6,
    f_sc=F_SC_SECAM_R,             # sous-porteuse « rouge », la plus haute
    f_sc_secondaire=F_SC_SECAM_B,  # sous-porteuse « bleue »
    bande_y=6.0e6,
    bande_c1=1.5e6,                # D'B avant modulation
    bande_c2=1.5e6,                # D'R avant modulation
    piedestal=PIEDESTAL_ZERO,
    gamma_affichage=2.8,
    primaires="ebu",
    base_chroma="DRDB",
    son=SON_L,
)

SECAM_DK = Norme(
    code="SECAM-DK",
    nom="SECAM-D/K (Europe de l'Est)",
    famille="SECAM",
    lignes_totales=625,
    lignes_actives=576,
    f_trame=F_TRAME_625,
    f_ligne=F_LIGNE_625,
    duree_ligne_active=51.95e-6,
    f_sc=F_SC_SECAM_R,
    f_sc_secondaire=F_SC_SECAM_B,
    bande_y=6.0e6,
    bande_c1=1.5e6,
    bande_c2=1.5e6,
    piedestal=PIEDESTAL_ZERO,
    gamma_affichage=2.8,
    primaires="ebu",
    base_chroma="DRDB",
    son=SON_DK,
)


NORMES: dict[str, Norme] = {
    n.code: n
    for n in (NTSC_M, NTSC_J, NTSC_1953, PAL_BG, PAL_I, SECAM_L, SECAM_DK)
}


def obtenir_norme(code: str) -> Norme:
    """Retourne la norme correspondant au code, ex. « PAL-BG »."""
    try:
        return NORMES[code]
    except KeyError:
        connus = ", ".join(sorted(NORMES))
        raise KeyError(f"norme inconnue : {code!r}. Normes connues : {connus}") from None


# ---------------------------------------------------------------------------
# Niveaux de référence en IRE
# ---------------------------------------------------------------------------

# L'unité IRE (Institute of Radio Engineers) divise l'excursion
# suppression → blanc en 100 parts. La synchro descend à -40 IRE.
IRE_SYNCHRO = -40.0
IRE_SUPPRESSION = 0.0
IRE_BLANC = 100.0


def vers_ire(signal, piedestal: float = 0.0):
    """Convertit un signal vidéo normalisé (0 = noir, 1 = blanc) en IRE."""
    return (piedestal + (1.0 - piedestal) * signal) * 100.0
