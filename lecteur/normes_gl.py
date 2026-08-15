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

def noyau_passe_bas(n_taps: int, f_coupure: float, f_ech: float) -> np.ndarray:
    """Noyau passe-bas à phase linéaire, fenêtré, normalisé en gain continu.

    `tvcolor` emploie des Butterworth récursifs, fidèles à un réseau LC. Un
    shader ne peut pas être récursif — chaque fragment est indépendant — d'où
    le passage à un filtre à réponse finie. La fenêtre de Blackman évite le
    rebond de Gibbs qu'une troncature brutale produirait sur les contours.
    """
    fc = float(np.clip(f_coupure / f_ech, 1e-4, 0.4999))
    if fc >= 0.4999:
        noyau = np.zeros(n_taps)
        noyau[n_taps // 2] = 1.0
        return noyau
    noyau = sig.firwin(n_taps, cutoff=2.0 * fc, window="blackman")
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

    largeur: int = field(init=False)
    hauteur: int = field(init=False)
    f_ech: float = field(init=False)
    uniformes: dict = field(init=False)

    def __post_init__(self) -> None:
        n = self.norme
        self.largeur = n.echantillons_par_ligne
        self.hauteur = n.lignes_actives
        self.f_ech = self.largeur / n.duree_ligne_active

        cycles_actifs = n.f_sc * n.duree_ligne_active
        frac_ligne = float(np.mod(n.f_sc / n.f_ligne, 1.0))
        # Avance de phase d'une image entière, réduite modulo un cycle. C'est
        # elle qui fait « ramper » les points au lieu de les laisser fixes.
        frac_image = float(np.mod(frac_ligne * n.lignes_totales, 1.0))

        bande_dec = max(n.bande_c1, n.bande_c2)

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
            "u_noyau_dec": noyau_passe_bas(self.n_taps, bande_dec, self.f_ech),
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


def longueur_minimale_discriminateur(
    f_ech: float, bande: float, f_repos: float, attenuation_db: float = 50.0
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
    plus courte qui atteigne l'atténuation voulue.
    """
    for n_taps in range(9, 81, 2):
        noyau = noyau_passe_bas(n_taps, bande, f_ech)
        _, reponse = sig.freqz(noyau, worN=4096, fs=f_ech)
        frequences = np.linspace(0.0, f_ech / 2.0, 4096, endpoint=False)
        indice = int(np.argmin(np.abs(frequences - f_repos)))
        if 20.0 * np.log10(max(abs(reponse[indice]), 1e-15)) <= -attenuation_db:
            return n_taps
    return 41


def reglage(code: str, qualite: str = "normale") -> ReglageGL:
    """Construit le jeu d'uniformes d'une norme, pour une qualité donnée."""
    if qualite not in QUALITES:
        raise KeyError(f"qualité inconnue : {qualite!r}")
    n_taps, n_notch = QUALITES[qualite]
    norme = obtenir_norme(code)

    if norme.famille == "SECAM":
        f_ech = norme.echantillons_par_ligne / norme.duree_ligne_active
        minimum = longueur_minimale_discriminateur(
            f_ech, max(norme.bande_c1, norme.bande_c2), F_SC_SECAM_B
        )
        n_taps = max(n_taps, minimum)

    return ReglageGL(norme, n_taps, n_notch)
