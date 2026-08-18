"""
Modulation et démodulation, sur enveloppe complexe.

POURQUOI L'ENVELOPPE COMPLEXE
-----------------------------

Simuler une porteuse à 446 mégahertz en échantillonnant la sinusoïde
demanderait un milliard de points par seconde, et n'apprendrait rien de plus :
la fréquence de la porteuse **n'intervient nulle part** dans ce qui ressort du
démodulateur. Elle décide de la propagation et de l'encombrement du spectre, pas
du son.

On travaille donc sur l'**enveloppe complexe** — ce que les récepteurs à
définition logicielle appellent I/Q :

    signal réel(t) = Re{ s(t) · e^{j 2π f_p t} }

`s(t)` porte toute l'information : son module est l'amplitude instantanée, son
argument la phase. La modulation d'amplitude agit sur le module, celle de
fréquence sur la dérivée de l'argument, la bande latérale unique sur les deux à
la fois. Le bruit d'un canal radio est gaussien complexe, et se simule
exactement. Ce n'est pas une approximation commode : c'est la représentation
exacte d'un signal à bande étroite, et c'est celle que manipule tout récepteur
moderne.

Une conséquence pratique qu'il faut avoir en tête : l'enveloppe complexe
échantillonnée à `f` couvre **toute** la bande de −f/2 à +f/2, et non la moitié
comme un signal réel. Un canal FM de 180 kHz tient donc dans 288 kilo-points par
seconde, ce qui est jouable.

TOUT EST EN FLUX
----------------

Chaque fonction de ce module qui a besoin de mémoire — l'intégrateur de phase du
modulateur FM, l'échantillon précédent du discriminateur, l'état du filtre de
Hilbert — la garde dans un objet dédié. Deux blocs consécutifs se raccordent
alors exactement, sans le clic qu'une remise à zéro produirait à chaque
frontière.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sig


# ---------------------------------------------------------------------------
# Modulation d'amplitude
# ---------------------------------------------------------------------------

def moduler_am(audio: np.ndarray, indice: float) -> np.ndarray:
    """Enveloppe complexe d'une modulation d'amplitude avec porteuse.

        s(t) = 1 + m · a(t)

    L'audio est supposé normalisé dans [−1, +1]. Le « 1 » est la porteuse, et
    c'est elle qui coûte les deux tiers de la puissance d'un émetteur AM pour
    ne transporter aucune information — le prix d'un détecteur d'enveloppe à une
    diode, qui a mis un poste dans chaque foyer.

    **Au-delà de m = 1, l'enveloppe passe par zéro et repart négative.** Le
    détecteur, lui, ne connaît que le module : il replie la partie négative et
    fabrique une distorsion massive. Le simulateur ne l'interdit pas — c'est le
    son de la CB poussée à fond, et il vaut mieux l'entendre.
    """
    return (1.0 + indice * np.asarray(audio, dtype=np.float64)).astype(np.complex128)


def demoduler_am(enveloppe: np.ndarray) -> np.ndarray:
    """Détecteur d'enveloppe : le module, tout simplement.

    C'est littéralement ce que fait une diode suivie d'un condensateur, et c'est
    pour cela que le repliement de la surmodulation est ici automatique : le
    module d'un nombre négatif est son opposé.
    """
    return np.abs(enveloppe)


# ---------------------------------------------------------------------------
# Modulation de fréquence
# ---------------------------------------------------------------------------

@dataclass
class EtatFM:
    """Mémoire du modulateur et du discriminateur, d'un bloc à l'autre."""

    phase: float = 0.0
    """Phase accumulée, en radians, réduite modulo 2π à chaque bloc pour que la
    précision ne se dégrade pas au bout d'une heure de lecture."""

    precedent: complex = 1.0 + 0.0j
    """Dernier échantillon du bloc précédent : le discriminateur compare deux
    échantillons consécutifs, et il lui en manquerait un à chaque frontière."""


def moduler_fm(
    audio: np.ndarray, excursion: float, f_ech: float, etat: EtatFM
) -> np.ndarray:
    """Enveloppe complexe d'une modulation de fréquence.

        s(t) = exp( j 2π Δf ∫ a(τ) dτ )

    Le module vaut 1 partout : **une porteuse FM a une amplitude constante**.
    C'est de là que vient l'immunité au bruit d'amplitude, et c'est pourquoi un
    limiteur peut précéder le discriminateur sans rien perdre.

    L'intégrale est cumulée d'un bloc au suivant : la phase d'une porteuse ne se
    remet pas à zéro, pas plus ici que celle de la sous-porteuse couleur du
    chapitre 5.
    """
    audio = np.asarray(audio, dtype=np.float64)
    increment = 2.0 * np.pi * excursion / f_ech
    phase = etat.phase + increment * np.cumsum(audio)
    etat.phase = float(np.mod(phase[-1], 2.0 * np.pi)) if phase.size else etat.phase
    return np.exp(1j * phase)


def demoduler_fm(
    enveloppe: np.ndarray, excursion: float, f_ech: float, etat: EtatFM
) -> np.ndarray:
    """Discriminateur : la dérivée de l'argument, prise par différence de phase.

        a(t) = arg( s(t) · conj(s(t−T)) ) · f_ech / (2π Δf)

    Écrire `np.diff(np.angle(s))` serait le piège classique : l'argument saute
    de +π à −π à chaque tour, et la dérivée y verrait une impulsion géante. Le
    produit par le conjugué donne directement l'écart de phase, déjà ramené dans
    (−π, +π] par `angle` — c'est exactement ce que fait un discriminateur à
    quadrature, et cela ne réclame aucun déroulement.

    **Le seuil FM tombe de cette formule sans qu'on ait rien à faire.** Quand le
    bruit devient comparable à la porteuse, le vecteur somme passe de temps en
    temps de l'autre côté de l'origine ; l'écart de phase fait alors un tour
    complet, et le discriminateur sort une impulsion. Ce sont les
    craquements qu'on entend juste avant qu'une station lointaine ne décroche.
    """
    enveloppe = np.asarray(enveloppe, dtype=np.complex128)
    if enveloppe.size == 0:
        return np.zeros(0)
    precedent = np.concatenate(([etat.precedent], enveloppe[:-1]))
    etat.precedent = complex(enveloppe[-1])
    ecart = np.angle(enveloppe * np.conj(precedent))
    return ecart * f_ech / (2.0 * np.pi * excursion)


# ---------------------------------------------------------------------------
# Bande latérale unique
# ---------------------------------------------------------------------------

LONGUEUR_HILBERT = 255
"""Longueur du filtre de Hilbert. Impair, pour que le retard soit un nombre
entier d'échantillons et que la voie en phase puisse être retardée d'autant."""


@dataclass
class EtatBLU:
    """Mémoire du filtre de Hilbert et de la voie en phase."""

    noyau: np.ndarray = field(default_factory=lambda: _noyau_hilbert(LONGUEUR_HILBERT))
    zi_q: np.ndarray | None = None
    zi_i: np.ndarray | None = None
    phase: float = 0.0


def _noyau_hilbert(longueur: int) -> np.ndarray:
    """Transformateur de Hilbert à réponse impulsionnelle finie.

    La réponse idéale est `2/(πn)` pour n impair et zéro pour n pair — une suite
    infinie, qu'on tronque et qu'on fenêtre. Le retard de groupe vaut
    `(longueur−1)/2` échantillons, et la voie en phase doit être retardée
    d'autant, sans quoi les deux voies ne seraient pas en quadrature et la bande
    latérale indésirable ne s'annulerait pas.
    """
    demi = longueur // 2
    n = np.arange(-demi, demi + 1)
    noyau = np.zeros(longueur)
    impair = n % 2 != 0
    noyau[impair] = 2.0 / (np.pi * n[impair])
    return noyau * np.hamming(longueur)


def moduler_blu(
    audio: np.ndarray, superieure: bool, etat: EtatBLU
) -> np.ndarray:
    """Enveloppe complexe d'une bande latérale unique.

        s(t) = a(t) ± j · H{a}(t)

    Le signe décide de la bande conservée : « + » pour la latérale supérieure,
    « − » pour l'inférieure. Il n'y a **ni porteuse ni seconde bande latérale** :
    toute la puissance est dans la parole, ce qui vaut au procédé neuf décibels
    d'avantage sur l'AM à puissance crête égale.
    """
    audio = np.asarray(audio, dtype=np.float64)
    if etat.zi_q is None:
        etat.zi_q = np.zeros(etat.noyau.size - 1)
        etat.zi_i = np.zeros(etat.noyau.size - 1)

    quadrature, etat.zi_q = sig.lfilter(etat.noyau, [1.0], audio, zi=etat.zi_q)
    # La voie en phase passe par un filtre à retard pur de même longueur : sans
    # cela, les deux voies seraient décalées de 127 échantillons et la bande
    # indésirable réapparaîtrait à pleine puissance.
    retard = np.zeros(etat.noyau.size)
    retard[etat.noyau.size // 2] = 1.0
    en_phase, etat.zi_i = sig.lfilter(retard, [1.0], audio, zi=etat.zi_i)

    signe = 1.0 if superieure else -1.0
    return en_phase + 1j * signe * quadrature


def demoduler_blu(
    enveloppe: np.ndarray, superieure: bool, desaccord: float, f_ech: float,
    etat: EtatBLU,
) -> np.ndarray:
    """Détection par battement avec l'oscillateur local du récepteur.

    On multiplie par `exp(−j 2π δ t)` et l'on garde la partie réelle. Le
    désaccord `δ` est l'erreur d'accord du poste, en hertz.

    **Et c'est là que la BLU se distingue de tout le reste.** En AM comme en FM,
    une erreur d'accord de cent hertz ne s'entend pas. Ici, elle décale
    l'intégralité du spectre audio de cent hertz — pas d'un facteur, d'un
    décalage : les harmoniques ne sont plus des multiples de la fondamentale, et
    la voix prend ce timbre métallique que les cibistes appellent Donald. C'est
    pour cela qu'un poste BLU a un bouton d'accord fin, et qu'on l'entend
    tourner jusqu'à ce que la voix redevienne humaine.
    """
    enveloppe = np.asarray(enveloppe, dtype=np.complex128)
    if enveloppe.size == 0:
        return np.zeros(0)
    increment = 2.0 * np.pi * desaccord / f_ech
    phase = etat.phase + increment * np.arange(1, enveloppe.size + 1)
    etat.phase = float(np.mod(phase[-1], 2.0 * np.pi))
    signe = 1.0 if superieure else -1.0
    return np.real(enveloppe * np.exp(-1j * signe * phase))


# ---------------------------------------------------------------------------
# Décalage de fréquence, commun à tout le monde
# ---------------------------------------------------------------------------

@dataclass
class EtatDecalage:
    phase: float = 0.0


def decaler(
    enveloppe: np.ndarray, decalage: float, f_ech: float, etat: EtatDecalage
) -> np.ndarray:
    """Translate l'enveloppe en fréquence — l'erreur d'accord du récepteur.

    Sur une enveloppe complexe, changer de fréquence est une simple
    multiplication par une exponentielle : c'est tout l'intérêt de cette
    représentation, et c'est ainsi que le simulateur désaccorde un poste ou
    place une station interférente à côté de la bonne.
    """
    enveloppe = np.asarray(enveloppe, dtype=np.complex128)
    if enveloppe.size == 0 or decalage == 0.0:
        return enveloppe
    increment = 2.0 * np.pi * decalage / f_ech
    phase = etat.phase + increment * np.arange(1, enveloppe.size + 1)
    etat.phase = float(np.mod(phase[-1], 2.0 * np.pi))
    return enveloppe * np.exp(1j * phase)
