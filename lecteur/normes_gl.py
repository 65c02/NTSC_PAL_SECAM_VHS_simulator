"""
Traduction des normes en jeux d'uniformes pour les shaders.

Les valeurs viennent toutes de `tvcolor.constantes` : il n'y a pas de seconde
table de constantes normatives dans le projet, et une correction faite pour le
simulateur de référence se propage donc au lecteur temps réel.

La différence essentielle avec `tvcolor` tient à la grille d'échantillonnage.
Le simulateur travaille à quatre fois la sous-porteuse — 753 points par ligne
en NTSC, 921 en PAL. Le lecteur garde ces mêmes largeurs, ce qui donne
environ quatre échantillons par cycle de sous-porteuse : le strict nécessaire
pour la représenter, et exactement ce que faisaient les filtres numériques des
téléviseurs de la fin de l'ère analogique.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sig

from tvcolor.constantes import (
    F_SC_SECAM_B,
    F_SC_SECAM_R,
    SECAM_DEVIATION_B,
    SECAM_DEVIATION_R,
    SECAM_EXCURSION_MAX,
    SECAM_EXCURSION_MIN,
    SECAM_F0,
    Norme,
    obtenir_norme,
)

QUALITES = {
    #  qualité   : (coefficients de filtrage, coefficients du piège)
    "rapide":  (13, 31),
    "normale": (21, 41),
    "haute":   (31, 61),
}
"""Le piège de sous-porteuse a besoin de bien plus de coefficients que les
passe-bas, et pour une raison simple : un passe-bas n'a qu'un flanc à former,
un réjecteur en a deux, encadrant une bande étroite. Mesuré sur la bande SECAM,
un noyau de 21 coefficients ne rejette que 11 dB — la sous-porteuse resterait
visible en clair dans l'image. À 41 coefficients on atteint 34 dB, à 61 on
dépasse 45."""


# ---------------------------------------------------------------------------
# Noyaux de filtrage
# ---------------------------------------------------------------------------

ORDRE_REFERENCE = 4
"""Ordre du Butterworth employé par `tvcolor.filtres`. Les noyaux du shader
sont taillés pour lui ressembler ; garder les deux valeurs liées évite qu'une
correction faite d'un côté ne soit oubliée de l'autre."""


def noyau_passe_bas(n_taps: int, f_coupure: float, f_ech: float) -> np.ndarray:
    """Noyau passe-bas à phase linéaire, calqué sur le filtre de référence.

    `tvcolor` emploie des Butterworth récursifs, fidèles à un réseau LC. Un
    shader ne peut pas être récursif — chaque fragment est indépendant — d'où
    le passage à un filtre à réponse finie.

    Reste à choisir lequel. Un sinus cardinal fenêtré est le réflexe, mais la
    fenêtre — de Blackman ou de Hamming — **affaisse la bande passante** : à
    31 coefficients elle perdait 2,9 dB à 1 MHz là où la référence n'en perd
    que 0,95. Le temps de montée s'allongeait de moitié, six points au lieu de
    neuf, et toutes les transitions de couleur s'élargissaient d'autant. Sur
    le SECAM, où l'écart se cumule avec la modulation de fréquence et la
    mémoire de ligne, les franges devenaient franchement voyantes.

    On synthétise donc le noyau pour qu'il **épouse la réponse du Butterworth
    aller-retour** de la référence, plutôt que de partir d'un gabarit idéal
    dont on sait qu'il ne sera pas tenu. Les deux chaînes se répondent alors
    par construction.
    """
    fc = float(np.clip(f_coupure / f_ech, 1e-4, 0.4999))
    if fc >= 0.4999:
        noyau = np.zeros(n_taps)
        noyau[n_taps // 2] = 1.0
        return noyau

    numerateur, denominateur = sig.butter(ORDRE_REFERENCE, 2.0 * fc, output="ba")
    # Grille explicite : `freqz` s'arrête juste avant Nyquist, que `firwin2`
    # exige au contraire de trouver comme dernier point.
    frequences = np.linspace(0.0, 0.5 * f_ech, 512)
    _, reponse = sig.freqz(numerateur, denominateur, worN=frequences, fs=f_ech)
    # Le filtrage aller-retour de la référence élève le module au carré.
    gabarit = np.abs(reponse) ** 2

    noyau = sig.firwin2(n_taps, frequences, gabarit, fs=f_ech)
    return noyau / noyau.sum()


ATTENUATION_DISCRIMINATEUR = 85.0
"""Plancher de bande atténuée, en décibels, du mélangeur du discriminateur SECAM."""


def noyau_demodulation_secam(n_taps: int, bande: float, f_ech: float) -> np.ndarray:
    """Passe-bas du mélangeur du discriminateur. Ici, la réjection prime sur tout.

    Ce noyau n'a pas le même cahier des charges que les autres, et lui donner
    le même a coûté cher.

    Le mélangeur transpose la luminance continue — qui vaut jusqu'à 1,0 — à la
    fréquence de repos, où la porteuse ne pèse que 0,246. Or le discriminateur
    mesure une **phase** : une fuite relative ε de la luminance se traduit par
    une erreur de chrominance de ε·f_ech/(2π·Δf), soit un facteur dix. Un
    pour-cent de fuite fait dix pour-cent d'erreur de couleur.

    Il faut donc une réjection de l'ordre de 74 dB — et surtout **garantie**.
    Un noyau ajusté sur une réponse de Butterworth laisse une ondulation dont
    la position dépend de la longueur : à 21 coefficients elle donnait 68 dB,
    à 25 seulement 58, à 29 encore 56. La qualité du rendu variait de façon
    erratique avec un réglage censé l'améliorer.

    La fenêtre de Kaiser, elle, garantit un plancher choisi d'avance et
    monotone. On y perd la ressemblance exacte avec la référence sur la forme
    de la bande passante ; on y gagne un comportement prévisible, ce qui vaut
    bien mieux ici.
    """
    fc = float(np.clip(bande / f_ech, 1e-4, 0.4999))
    noyau = sig.firwin(
        n_taps, 2.0 * fc, window=("kaiser", sig.kaiser_beta(ATTENUATION_DISCRIMINATEUR))
    )
    return noyau / noyau.sum()


def noyau_coupe_bande(
    n_taps: int, f_basse: float, f_haute: float, f_ech: float
) -> np.ndarray:
    """Réjecteur de sous-porteuse pour la voie luminance.

    Volontairement étroit — ±0,6 MHz autour de la sous-porteuse en NTSC et en
    PAL, comme un vrai piège LC. Un piège aussi large que la bande de
    chrominance avalerait toute trace de sous-porteuse, et le fourmillement des
    points ne se produirait jamais : on simulerait un téléviseur qui n'a pas
    existé.

    Le gabarit est obtenu par la méthode de Parks-McClellan (`remez`) plutôt
    que par fenêtrage. La différence n'est pas académique : à 41 coefficients,
    un noyau fenêtré ne rejette que 16 dB là où l'équiondulation en obtient 34,
    et 16 dB laissent une sous-porteuse parfaitement visible dans l'image.
    """
    nyquist = 0.5 * f_ech
    transition = 0.5e6
    bornes = [
        0.0,
        max(0.2e6, f_basse - transition),
        f_basse,
        f_haute,
        min(f_haute + transition, 0.985 * nyquist),
        nyquist,
    ]
    if all(bornes[i] < bornes[i + 1] for i in range(len(bornes) - 1)):
        try:
            noyau = sig.remez(n_taps, bornes, [1.0, 0.0, 1.0], fs=f_ech)
            return noyau / noyau.sum()
        except ValueError:
            pass   # l'algorithme n'a pas convergé : on retombe sur le fenêtrage

    f1 = float(np.clip(f_basse / nyquist, 1e-3, 0.99))
    f2 = float(np.clip(f_haute / nyquist, f1 + 1e-3, 0.995))
    noyau = sig.firwin(n_taps, cutoff=[f1, f2], window="blackman", pass_zero=True)
    return noyau / noyau.sum()


def _gain_cloche_maximal() -> float:
    """Gain crête du filtre cloche sur la plage réellement occupée."""
    f = np.linspace(
        F_SC_SECAM_B + SECAM_EXCURSION_MIN, F_SC_SECAM_R + SECAM_EXCURSION_MAX, 2001
    )
    grand_f = f / SECAM_F0 - SECAM_F0 / f
    gain = np.sqrt((1.0 + 256.0 * grand_f**2) / (1.0 + 1.5876 * grand_f**2))
    return float(gain.max())


GAIN_CLOCHE_MAX = _gain_cloche_maximal()

PLAFOND_TAPS = 81
PLAFOND_NOTCH = 161
"""Longueurs maximales des noyaux.

Les uniformes de shader ne sont pas gratuits : GLSL 3.30 ne garantit que
1024 composantes flottantes par étage fragment, et l'on déclare cinq tableaux.
Avec 81 et 161, on en occupe 404 — confortable partout. Au-delà, la réjection
cesse de progresser proportionnellement de toute façon."""

BANDE_DEMODULATION_SECAM = 0.85e6
"""Coupure du passe-bas de démodulation SECAM, en hertz.

Elle ne vaut pas les 1,5 MHz de la bande de chrominance, et c'est délibéré :
c'est ainsi qu'on rend compte de la **désaccentuation basse fréquence**, que le
shader ne peut pas implémenter telle quelle.

Le filtre normatif A(f) = (1 + jf/f₁)/(1 + jf/3f₁), avec f₁ = 85 kHz, a son
coude si bas qu'à 17,6 MHz d'échantillonnage il demanderait plus de deux cents
coefficients — hors de portée du budget d'uniformes. Mais son effet est
mesurable : il atténue de 7 dB dès 255 kHz et de 9,4 dB au-delà, soit un
facteur trois.

Sans lui, le discriminateur restituait les transitions de couleur avec un
**dépassement** de 0,26 en U, là où la référence n'en montre que 0,004. C'est ce
dépassement qui dessinait une frange verte vive et striée sur les contours —
l'artefact le plus voyant du SECAM simulé, et il n'avait rien d'authentique.

La valeur retenue n'est pas déduite d'une formule mais **mesurée** : on balaie
la coupure et l'on garde celle qui minimise l'écart au simulateur de référence.
À 0,85 MHz, l'écart colorimétrique médian tombe à 4,6 et le dépassement à 0,058.

Reste ensuite une frange colorée à chaque transition, plus large qu'en PAL.
Celle-là est authentique : la chrominance SECAM est bien plus lente que la
luminance, et le passage du jaune au cyan traverse réellement le vert."""

LARGEUR_TRAP = 0.6e6
"""Demi-largeur du piège de sous-porteuse, en hertz. Même valeur que
`tvcolor.decodeur.LARGEUR_TRAP`, et pour la même raison."""


# ---------------------------------------------------------------------------

@dataclass
class ReglageGL:
    """Tout ce dont les shaders ont besoin pour une norme donnée."""

    norme: Norme
    n_taps: int
    n_notch: int
    largeur_forcee: int | None = None
    """Largeur de la grille d'échantillonnage, en points par ligne active.

    `None` donne la valeur normative, quatre points par cycle de sous-porteuse
    — le strict nécessaire pour la représenter. La forcer plus haut ne change
    rien à la physique : la phase se calcule en cycles par largeur d'image, et
    les bandes passantes sont en hertz. Seule la finesse de représentation de
    la sous-porteuse change, et avec elle l'aspect du résidu, qui passe d'un
    escalier de quatre points à une sinusoïde lisse.

    Le nombre de LIGNES, lui, ne se règle pas : 480 ou 576 lignes actives, c'est
    la norme, et les lignes sont bien réelles."""

    largeur: int = field(init=False)
    hauteur: int = field(init=False)
    f_ech: float = field(init=False)
    uniformes: dict = field(init=False)

    def __post_init__(self) -> None:
        n = self.norme
        self.largeur = int(self.largeur_forcee or n.echantillons_par_ligne)
        self.hauteur = n.lignes_actives
        self.f_ech = self.largeur / n.duree_ligne_active

        cycles_actifs = n.f_sc * n.duree_ligne_active
        frac_ligne = float(np.mod(n.f_sc / n.f_ligne, 1.0))
        # Avance de phase d'une image entière, réduite modulo un cycle. C'est
        # elle qui fait « ramper » les points au lieu de les laisser fixes.
        frac_image = float(np.mod(frac_ligne * n.lignes_totales, 1.0))

        # Le passe-bas placé après le mélangeur. En SECAM il sert un
        # discriminateur, dont l'exigence de réjection est d'un tout autre
        # ordre que celle d'un démodulateur synchrone : il lui faut son propre
        # gabarit, garanti par une fenêtre de Kaiser.
        if n.famille == "SECAM":
            noyau_dec = noyau_demodulation_secam(
                self.n_taps, BANDE_DEMODULATION_SECAM, self.f_ech
            )
        else:
            noyau_dec = noyau_passe_bas(
                self.n_taps, max(n.bande_c1, n.bande_c2), self.f_ech
            )

        self.uniformes = {
            "u_taille": (float(self.largeur), float(self.hauteur)),
            "u_cycles_actifs": float(cycles_actifs),
            "u_frac_ligne": frac_ligne,
            "u_frac_image": frac_image,
            "u_piedestal": float(n.piedestal),
            "u_gamma": float(n.gamma_affichage),
            "u_f_ech": float(self.f_ech),
            "u_noyau_luma": noyau_passe_bas(self.n_taps, n.bande_y, self.f_ech),
            "u_noyau_c1": noyau_passe_bas(self.n_taps, n.bande_c1, self.f_ech),
            "u_noyau_c2": noyau_passe_bas(self.n_taps, n.bande_c2, self.f_ech),
            "u_noyau_dec": noyau_dec,
            "u_noyau_notch": self._noyau_notch(),
            "u_secam_repos": (float(F_SC_SECAM_B), float(F_SC_SECAM_R)),
            "u_secam_dev": (float(SECAM_DEVIATION_B), float(SECAM_DEVIATION_R)),
            "u_secam_butees": (float(SECAM_EXCURSION_MIN), float(SECAM_EXCURSION_MAX)),
            "u_secam_f0": float(SECAM_F0),
            "u_secam_gain_max": GAIN_CLOCHE_MAX,
        }

    def _noyau_notch(self) -> np.ndarray:
        n = self.norme
        if n.famille == "SECAM":
            # Les deux sous-porteuses plus leurs bandes latérales.
            basse, haute = F_SC_SECAM_B - 0.9e6, F_SC_SECAM_R + 0.9e6
        else:
            basse, haute = n.f_sc - LARGEUR_TRAP, n.f_sc + LARGEUR_TRAP
        return noyau_coupe_bande(self.n_notch, basse, haute, self.f_ech)

    @property
    def famille(self) -> str:
        return self.norme.famille

    def description(self) -> str:
        n = self.norme
        return (
            f"{n.nom} — {self.largeur}×{self.hauteur} échantillons à "
            f"{self.f_ech / 1e6:.2f} MHz, sous-porteuse {n.f_sc / 1e6:.4f} MHz "
            f"({n.avance_phase_par_ligne_deg:.1f}° par ligne)"
        )


def amplitude_porteuse_au_repos() -> float:
    """Amplitude de la sous-porteuse SECAM quand la couleur est neutre.

    C'est la référence à laquelle se compare la fuite de luminance : le
    filtre cloche l'atténue fortement au repos, ce qui rend justement le
    discriminateur plus vulnérable là où l'image est peu colorée."""
    grand_f = F_SC_SECAM_B / SECAM_F0 - SECAM_F0 / F_SC_SECAM_B
    gain = np.sqrt((1.0 + 256.0 * grand_f**2) / (1.0 + 1.5876 * grand_f**2))
    return float(gain / GAIN_CLOCHE_MAX)


def longueur_minimale_discriminateur(
    f_ech: float, bande: float, erreur_admise: float = 0.01
) -> int:
    """Longueur de noyau minimale pour que le discriminateur SECAM tienne debout.

    Le mélangeur du discriminateur multiplie le signal composite par un
    oscillateur local à la fréquence de repos. La luminance, qui est du
    continu, se retrouve donc transposée **à cette fréquence de repos**, et
    c'est au passe-bas qui suit de l'y rejeter.

    L'enjeu est un rapport de niveaux : la luminance vaut jusqu'à 1,0 quand la
    sous-porteuse n'atteint que 0,24. Une réjection de 33 dB — ce qu'un noyau
    de treize coefficients obtient — laisse donc un résidu valant 9 % de la
    porteuse. Ce résidu est un vecteur quasi constant qui s'ajoute à la bande
    de base : il ne brouille pas l'amplitude, dont le discriminateur se moque,
    mais il fausse **la phase**, c'est-à-dire précisément la grandeur mesurée.
    Le SECAM décroche alors complètement.

    Plutôt que d'inscrire en dur une longueur trouvée à l'essai, on cherche la
    plus courte qui tienne un **budget d'erreur de chrominance** donné.

    Deux pièges, tous deux payés comptant :

    * le critère porte sur le pire cas de **toute la bande** que la porteuse
      occupe, excursion comprise, et non sur la seule fréquence de repos.
      Évaluée au seul point 4,25 MHz, une longueur de onze coefficients
      affichait 64 dB — mais ce point tombait dans un creux d'ondulation, et
      le pire cas de la bande n'était que de 34 dB ;

    * le seuil se **déduit** de l'erreur de couleur admise au lieu d'être un
      chiffre rond. Un seuil de 50 dB paraissait large ; il laissait en
      réalité 13 % d'erreur de chrominance, le facteur dix de la
      transposition étant passé inaperçu.
    """
    basse = F_SC_SECAM_B + SECAM_EXCURSION_MIN
    haute = F_SC_SECAM_R + SECAM_EXCURSION_MAX
    frequences = np.linspace(0.0, 0.5 * f_ech, 4096)
    dans_la_bande = (frequences >= basse) & (frequences <= haute)

    # Budget d'erreur, déduit et non choisi : une fuite relative ε de la
    # luminance devient une erreur de chrominance ε·f_ech/(2π·Δf).
    fuite_admise = (
        erreur_admise * 2.0 * np.pi * min(SECAM_DEVIATION_B, SECAM_DEVIATION_R)
        / f_ech * amplitude_porteuse_au_repos()
    )
    seuil_db = 20.0 * np.log10(fuite_admise)

    for n_taps in range(9, 81, 2):
        noyau = noyau_demodulation_secam(n_taps, bande, f_ech)
        _, reponse = sig.freqz(noyau, worN=frequences, fs=f_ech)
        pire = float(np.max(np.abs(reponse[dans_la_bande])))
        if 20.0 * np.log10(max(pire, 1e-15)) <= seuil_db:
            return n_taps
    return 41


def _impair(valeur: float, plafond: int) -> int:
    """Arrondit à l'entier impair le plus proche, borné. Un noyau symétrique
    veut un nombre impair de coefficients, pour avoir un centre."""
    n = int(round(valeur))
    n = max(5, min(n, plafond))
    return n if n % 2 else n + 1


def sigma_du_tube(lignes_de_definition: float, largeur_grille: int) -> float:
    """Écart-type du spot d'un tube, en points de la grille d'échantillonnage.

    Un tube cathodique ne restitue pas les hautes fréquences à pleine
    amplitude : le spot du faisceau a une largeur finie, et l'amplificateur
    vidéo sa propre bande passante. Leur effet combiné se modélise très bien
    par une gaussienne, dont la transformée est elle-même gaussienne :

        MTF(f) = exp(−2π² σ² f²)

    On paramètre par la grandeur que les constructeurs affichaient : les
    **lignes de résolution horizontale**. Par convention, N lignes signifient
    N/2 alternances sur une largeur égale à la HAUTEUR de l'image ; en 4:3
    cela fait (N/2)·(4/3) alternances par largeur d'image. On cale la
    gaussienne pour que la modulation y tombe à 10 %, seuil usuel de lisibilité.

    C'est la pièce manquante qui explique l'observation de départ : un
    téléviseur d'appartement affichait 300 à 400 lignes, et restituait donc la
    sous-porteuse — à 229 alternances par largeur — à moins d'un quart de son
    amplitude. Un moniteur, lui, la rend intégralement.
    """
    if lignes_de_definition <= 0:
        return 0.0
    f_limite = 0.5 * lignes_de_definition * (4.0 / 3.0)
    sigma_largeurs = 0.34157 / f_limite       # sqrt(ln 10 / (2π²)) / f_limite
    return sigma_largeurs * largeur_grille


def reglage(
    code: str, qualite: str = "normale", largeur: int | None = None
) -> ReglageGL:
    """Construit le jeu d'uniformes d'une norme, pour une qualité donnée."""
    if qualite not in QUALITES:
        raise KeyError(f"qualité inconnue : {qualite!r}")
    n_taps, n_notch = QUALITES[qualite]
    norme = obtenir_norme(code)
    largeur_effective = int(largeur or norme.echantillons_par_ligne)

    # Les longueurs de noyau suivent la finesse de la grille, et ce n'est pas
    # un raffinement : c'est indispensable.
    #
    # Un filtre à réponse finie se conçoit en fréquence NORMALISÉE. Doubler la
    # fréquence d'échantillonnage sans toucher au noyau divise par deux la
    # largeur relative de la bande à rejeter, et le même nombre de
    # coefficients ne sait plus la former. Mesuré sur le résidu SECAM d'une
    # image blanche : à grille double et noyaux inchangés, il passait de 2,1 à
    # 17,6 niveaux sur 255 — huit fois pire, alors qu'on croyait raffiner.
    facteur = largeur_effective / norme.echantillons_par_ligne
    n_taps = _impair(n_taps * facteur, PLAFOND_TAPS)
    n_notch = _impair(n_notch * facteur, PLAFOND_NOTCH)

    if norme.famille == "SECAM":
        f_ech = largeur_effective / norme.duree_ligne_active
        minimum = longueur_minimale_discriminateur(f_ech, BANDE_DEMODULATION_SECAM)
        n_taps = min(max(n_taps, minimum), PLAFOND_TAPS)

    return ReglageGL(norme, n_taps, n_notch, largeur_effective)
