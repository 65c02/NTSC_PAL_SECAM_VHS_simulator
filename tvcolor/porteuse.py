"""
L'horloge de sous-porteuse — le cœur horaire de la simulation.

Rien de ce qui suit n'est un artifice de rendu. La phase de la sous-porteuse
n'est **jamais** remise à zéro en début de ligne : elle est calculée en temps
absolu depuis le début de l'image,

    φ(ligne n, échantillon k) = 2π · f_sc · ( n·T_ligne + k/f_e )  + φ₀

et c'est de cette seule formule que découlent, sans qu'on ait rien à ajouter :

* l'alternance de 180° par ligne en NTSC (puisque f_sc = 455/2 · f_H, donc
  f_sc·T_ligne = 227,5 cycles, dont la partie fractionnaire vaut exactement ½) ;
* le fonctionnement du filtre en peigne, qui n'est que la conséquence de
  cette alternance ;
* le motif de points rampants (*dot crawl*) le long des contours ;
* la rotation de 270,6° par ligne en PAL, et sa séquence à huit trames.

Modifier arbitrairement cette phase reviendrait à trafiquer le résultat.
"""

from __future__ import annotations

import numpy as np

from .constantes import Norme

DEUX_PI = 2.0 * np.pi


# ---------------------------------------------------------------------------
# Numérotation des lignes
# ---------------------------------------------------------------------------

def indices_lignes(
    norme: Norme,
    n_lignes: int,
    entrelace: bool = False,
    numero_image: int = 0,
) -> np.ndarray:
    """Position temporelle de chaque rangée d'image, en nombre de lignes de balayage.

    En balayage progressif, la rangée *r* est simplement la ligne *r*.

    En entrelacé, les rangées paires appartiennent à la première trame et les
    impaires à la seconde ; or une trame ne compte pas un nombre entier de
    lignes — 312,5 en 625 lignes, 262,5 en 525. Ce **demi-écart** est
    volontaire : c'est lui qui fait que la seconde trame se dessine entre les
    lignes de la première. Il décale aussi la phase de la sous-porteuse d'une
    trame à l'autre, et c'est ce qui fait « ramper » les points au lieu de les
    laisser fixes.

    On renvoie donc des indices **fractionnaires**, ce qui rend le demi-écart
    exactement représentable.
    """
    base = float(numero_image) * norme.lignes_totales
    rangees = np.arange(n_lignes)
    if not entrelace:
        return base + rangees.astype(np.float64)
    demi_trame = norme.lignes_totales / 2.0
    return base + np.where(rangees % 2 == 0, rangees // 2, demi_trame + rangees // 2)


def numeros_lignes_transmises(indices: np.ndarray) -> np.ndarray:
    """Rang entier de la ligne dans l'ordre d'émission.

    Sert aux commutateurs qui comptent les lignes plutôt que le temps :
    l'inverseur de V du PAL et le permutateur séquentiel du SECAM.
    """
    return np.floor(np.asarray(indices, dtype=np.float64)).astype(np.int64)


# ---------------------------------------------------------------------------
# Phase
# ---------------------------------------------------------------------------

def phase(
    norme: Norme,
    indices: np.ndarray,
    n_echantillons: int,
    f_sc: float | None = None,
    phase_initiale_deg: float = 0.0,
) -> np.ndarray:
    """Matrice de phase de la sous-porteuse, en radians, de forme (n_lignes, n_ech).

    `f_sc` permet d'utiliser une autre sous-porteuse que celle de la norme —
    indispensable en SECAM, où les lignes « bleues » et « rouges » n'ont pas
    la même fréquence de repos.

    Détail d'implémentation qui compte : on réduit modulo 1 la contribution
    des lignes **avant** de la convertir en radians. Sans cela, une image de
    576 lignes accumulerait plus de 160 000 cycles, et les derniers bits de
    la mantisse — précisément ceux qui portent le demi-cycle — se perdraient
    dans l'arrondi.

    Note : le décalage de phase dû au temps de suppression ligne (front porch,
    synchro, back porch — environ 10,9 µs en 625 lignes) est le même sur
    toutes les lignes. C'est donc une constante additive, absorbée par
    `phase_initiale_deg`, et sans effet puisque le décodeur se réfère au même
    burst que le codeur.
    """
    f_sc = norme.f_sc if f_sc is None else f_sc
    indices = np.asarray(indices, dtype=np.float64)

    cycles_par_ligne = f_sc / norme.f_ligne
    cycles_ligne = np.mod(cycles_par_ligne * indices, 1.0)
    cycles_echantillon = (f_sc / norme.f_echantillonnage) * np.arange(n_echantillons)

    return DEUX_PI * (cycles_ligne[:, None] + cycles_echantillon[None, :]) + np.deg2rad(
        phase_initiale_deg
    )


def avance_de_phase_par_ligne(norme: Norme, f_sc: float | None = None) -> float:
    """Rotation de la sous-porteuse d'une ligne à la suivante, en degrés.

    * NTSC : 180,000° — la chroma s'inverse, le peigne fonctionne.
    * PAL  : 270,576° — trois quarts de tour, plus le fameux décalage de 25 Hz.
    * SECAM : sans objet, les sous-porteuses sont des multiples entiers de f_H
      et retombent donc en phase à chaque ligne (0°).
    """
    f_sc = norme.f_sc if f_sc is None else f_sc
    return float(np.mod(f_sc / norme.f_ligne, 1.0) * 360.0)


# ---------------------------------------------------------------------------
# Commutateurs de ligne
# ---------------------------------------------------------------------------

def signe_pal(indices: np.ndarray) -> np.ndarray:
    """Signe de la composante V pour chaque ligne : +1 ou -1, en alternance.

    C'est *tout* le PAL — *Phase Alternating Line*. À l'émission, une ligne
    sur deux voit sa composante V inversée. Le récepteur, prévenu par la
    phase du burst (135° ou 225°), rétablit le signe avant de moyenner deux
    lignes consécutives. Une erreur de phase du canal, qui ferait tourner la
    teinte dans un sens sur une ligne, la fait tourner dans l'autre sens sur
    la suivante : la moyenne des deux est exempte d'erreur de teinte.

    Retourne un vecteur colonne, diffusable sur toute la largeur de l'image.
    """
    n = numeros_lignes_transmises(indices)
    return np.where(n % 2 == 0, 1.0, -1.0)[:, None]


def phase_burst_pal(indices: np.ndarray) -> np.ndarray:
    """Phase du burst PAL : 135° ou 225°, selon le signe de V — le « burst oscillant ».

    Le burst n'est pas seulement une référence de phase : son oscillation de
    ±45° autour de 180° indique au récepteur quel est le signe de V sur la
    ligne qui suit. Sans cette indication, le récepteur ne saurait pas dans
    quel sens rétablir V, et l'image afficherait les couleurs complémentaires
    une ligne sur deux.
    """
    return np.where(signe_pal(indices)[:, 0] > 0, 135.0, 225.0)


def secam_ligne_rouge(indices: np.ndarray) -> np.ndarray:
    """Vrai sur les lignes qui transmettent D'R, faux sur celles qui transmettent D'B.

    En SECAM, les deux composantes de chrominance ne sont **jamais** émises
    en même temps : chaque ligne n'en porte qu'une, en alternance. C'est le
    « séquentiel » de *Séquentiel Couleur À Mémoire*. Le récepteur garde la
    ligne précédente en mémoire pour reconstituer le couple manquant — d'où
    le « À Mémoire », et d'où la division par deux de la résolution
    chromatique verticale.
    """
    n = numeros_lignes_transmises(indices)
    return (n % 2) == 1


# ---------------------------------------------------------------------------
# Modulation / démodulation en quadrature
# ---------------------------------------------------------------------------

def moduler_quadrature(u: np.ndarray, v: np.ndarray, phi: np.ndarray) -> np.ndarray:
    """Chrominance NTSC/PAL : C(t) = U·sin(φ) + V·cos(φ).

    Deux signaux indépendants voyagent sur une seule porteuse, en quadrature.
    C'est la modulation d'amplitude à porteuse supprimée : lorsque U = V = 0
    (un gris), C est identiquement nul et l'image est parfaitement compatible
    avec un récepteur noir et blanc. Le vecteur (U, V) se lit directement dans
    l'amplitude et la phase de C — le vectorscope ne fait rien d'autre.
    """
    return u * np.sin(phi) + v * np.cos(phi)


def demoduler_frequence(
    chroma: np.ndarray,
    f_repos: np.ndarray | float,
    f_ech: float,
    passe_bas,
    bande: float = 1.8e6,
) -> np.ndarray:
    """Discriminateur de fréquence — l'organe central du décodage SECAM.

    Retourne l'écart, en hertz, entre la fréquence instantanée et la fréquence
    de repos, échantillon par échantillon.

    Méthode, qui est celle d'un vrai détecteur à quadrature :

    1. on ramène la sous-porteuse en bande de base en la multipliant par un
       oscillateur local à la fréquence de repos, en phase puis en quadrature ;
    2. un passe-bas élimine les produits de somme, il ne reste que le vecteur
       complexe z(t) dont l'argument est l'écart de phase accumulé ;
    3. l'écart de fréquence est la dérivée de cet argument, obtenue par
       « retard et multiplication » : arg(z[k+1]·z*[k]).

    Le point important est que **tout est local**. Chaque échantillon de sortie
    ne dépend que de ses voisins immédiats. Une transformée de Hilbert, elle,
    est globale : elle exige toute la ligne, sa périodisation implicite crée
    une rupture de phase aux extrémités, et le discriminateur y voit une
    excursion de plusieurs dizaines de kilohertz — c'est-à-dire une couleur
    franche, sur le bord gauche d'une image blanche.

    Prendre l'argument revient à ignorer complètement le module : c'est le
    limiteur, et c'est de là que vient l'insensibilité du SECAM au gain.
    """
    chroma = np.atleast_2d(np.asarray(chroma, dtype=np.float64))
    n = chroma.shape[1]
    omega = 2.0 * np.pi * np.asarray(f_repos, dtype=np.float64) / f_ech
    k = np.arange(n)
    argument = omega * k if np.ndim(f_repos) == 0 else omega * k[None, :]

    voie_i = passe_bas(chroma * (2.0 * np.cos(argument)), bande, f_ech)
    voie_q = passe_bas(chroma * (-2.0 * np.sin(argument)), bande, f_ech)

    z = voie_i + 1j * voie_q
    increment = np.angle(z[:, 1:] * np.conj(z[:, :-1]))
    increment = np.concatenate([increment[:, :1], increment], axis=1)
    return increment / (2.0 * np.pi) * f_ech


def demoduler_quadrature(
    chroma: np.ndarray, phi: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Démodulation synchrone : retour à (U, V) — avant filtrage passe-bas.

    On multiplie par la référence locale :

        2·C·sin(φ) = U·(1 - cos2φ) + V·sin2φ  →  U + termes en 2φ
        2·C·cos(φ) = U·sin2φ + V·(1 + cos2φ)  →  V + termes en 2φ

    Les termes à 2φ, autour de 7 à 9 MHz, sont éliminés par le passe-bas qui
    suit. Toute la précision du décodage tient dans l'exactitude de φ : c'est
    exactement là que le NTSC est vulnérable, et là que le PAL se protège.
    """
    return 2.0 * chroma * np.sin(phi), 2.0 * chroma * np.cos(phi)
