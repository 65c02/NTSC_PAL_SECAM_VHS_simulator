"""
Le canal radio : ce qui se passe entre l'antenne d'émission et celle du poste.

Rien n'est peint ici non plus. Le bruit est un bruit gaussien complexe, la
station voisine est une vraie porteuse à sa vraie fréquence, l'évanouissement
est un processus aléatoire filtré. Le sifflement de deux avions qui parlent
ensemble n'est pas un oscillateur qu'on ajoute : c'est le battement de deux
porteuses, et sa fréquence est leur écart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sig

from .modulation import EtatDecalage, decaler


def sigma_bruit(
    cn_db: float, f_travail: float, largeur_recepteur: float,
    puissance_porteuse: float = 1.0,
) -> float:
    """Écart-type du bruit complexe à injecter, pour un rapport C/N donné.

    Le point délicat, et il vaut d'être posé clairement : **le rapport
    porteuse/bruit se définit dans la bande du RÉCEPTEUR**, pas dans celle de la
    simulation. Le bruit thermique est blanc, donc sa puissance est
    proportionnelle à la largeur où on le mesure ; l'enveloppe complexe, elle,
    est échantillonnée bien plus large que le canal pour laisser de la place aux
    flancs des filtres.

    On injecte donc un bruit plus fort qu'il n'y paraît, dans le rapport des
    deux largeurs, pour qu'après le filtre de fréquence intermédiaire il reste
    exactement ce qui était demandé :

        σ² = P_porteuse · 10^(−C/N sur 10) · f_travail / B_récepteur

    Le bénéfice du filtre est ainsi **émergent** : rétrécir la bande passante du
    poste améliore le rapport signal/bruit sans qu'on ait à l'écrire nulle part.
    C'est ce que vérifie `tests/test_radio.py`.
    """
    rapport = 10.0 ** (cn_db / 10.0)
    variance = puissance_porteuse / rapport * f_travail / max(largeur_recepteur, 1.0)
    return float(np.sqrt(variance))


def bruit_complexe(taille: int, sigma: float, alea: np.random.Generator) -> np.ndarray:
    """Bruit blanc gaussien complexe circulaire.

    La puissance totale est `sigma²`, répartie à parts égales entre les deux
    quadratures — d'où le facteur `1/√2` sur chacune. C'est le modèle exact du
    bruit thermique vu à travers un étage à bande étroite, et c'est ce qui rend
    le seuil FM correct sans qu'on ait à le mettre à la main : ce sont les
    excursions de ce vecteur autour de l'origine qui font les craquements.
    """
    if sigma <= 0.0 or taille <= 0:
        return np.zeros(taille, dtype=np.complex128)
    echelle = sigma / np.sqrt(2.0)
    return alea.normal(0.0, echelle, taille) + 1j * alea.normal(0.0, echelle, taille)


# ---------------------------------------------------------------------------
# Évanouissement
# ---------------------------------------------------------------------------

@dataclass
class EtatEvanouissement:
    """Mémoire du filtre qui donne au fading sa lenteur."""

    zi: np.ndarray | None = None
    sos: np.ndarray | None = None
    gain: float = 1.0


def evanouissement(
    enveloppe: np.ndarray, profondeur: float, vitesse: float, f_ech: float,
    etat: EtatEvanouissement, alea: np.random.Generator,
) -> np.ndarray:
    """Évanouissement plat : l'amplitude du signal reçu varie lentement.

    Deux trajets qui arrivent avec des retards différents s'additionnent parfois
    en phase, parfois en opposition. Quand la bande du signal est étroite devant
    l'inverse de l'écart de retard, tout le canal monte et descend ensemble —
    c'est l'évanouissement **plat**, celui d'un poste mobile qui roule ou d'une
    liaison décamétrique qui rebondit sur l'ionosphère.

    On le simule pour ce qu'il est : un processus gaussien complexe filtré
    passe-bas à la fréquence Doppler. Le module d'un tel processus suit une loi
    de Rayleigh, ce qui est le résultat classique — et il n'a pas fallu l'écrire,
    il tombe du filtrage.

    `vitesse` est la fréquence Doppler en hertz : une fraction de hertz pour la
    propagation décamétrique de la CB, quelques hertz pour un poste VHF en
    voiture.
    """
    enveloppe = np.asarray(enveloppe, dtype=np.complex128)
    if profondeur <= 0.0 or enveloppe.size == 0:
        return enveloppe

    if etat.sos is None:
        coupure = max(vitesse, 0.05) / (f_ech / 2.0)
        etat.sos = sig.butter(2, min(coupure, 0.45), btype="low", output="sos")
        etat.zi = sig.sosfilt_zi(etat.sos) * 0.0
        etat.zi = np.repeat(etat.zi[:, None, :], 1, axis=1)[:, 0, :]

    brut = alea.normal(0.0, 1.0, enveloppe.size) + 1j * alea.normal(0.0, 1.0, enveloppe.size)
    lent, etat.zi = sig.sosfilt(etat.sos, brut, zi=etat.zi)

    # Le filtre a considérablement réduit la variance ; on la rétablit pour que
    # `profondeur` garde le même sens quelle que soit la vitesse choisie.
    if etat.gain == 1.0:
        etat.gain = 1.0 / max(float(np.std(lent)), 1e-9)
    module = np.abs(lent * etat.gain) / np.sqrt(2.0)

    return enveloppe * (1.0 - profondeur + profondeur * module)


# ---------------------------------------------------------------------------
# Bruit atmosphérique
# ---------------------------------------------------------------------------

@dataclass
class EtatAtmospherique:
    reste: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.complex128))


def atmospherique(
    taille: int, taux: float, amplitude: float, f_ech: float,
    etat: EtatAtmospherique, alea: np.random.Generator,
) -> np.ndarray:
    """Parasites impulsionnels — les craquements d'orage des ondes basses.

    Le bruit atmosphérique n'est pas gaussien, et c'est tout ce qui le
    distingue : il est **impulsionnel**. Un éclair à mille kilomètres met dans
    l'antenne une impulsion large bande dont le poste ne garde que ce qui tient
    dans son canal — soit une brève oscillation amortie. On tire donc des
    instants d'arrivée selon une loi de Poisson, et l'on y place des impulsions
    à décroissance exponentielle.

    C'est la signature des ondes moyennes et de la CB, et elle ne s'entend pas
    du tout comme un souffle : un souffle se supporte, un craquement fait
    sursauter.
    """
    if taux <= 0.0 or amplitude <= 0.0 or taille <= 0:
        return np.zeros(taille, dtype=np.complex128)

    sortie = np.zeros(taille + 512, dtype=np.complex128)
    if etat.reste.size:
        n = min(etat.reste.size, sortie.size)
        sortie[:n] += etat.reste[:n]

    nombre = alea.poisson(taux * taille / f_ech)
    if nombre:
        positions = alea.integers(0, taille, nombre)
        forces = amplitude * alea.exponential(1.0, nombre)
        phases = alea.uniform(0.0, 2.0 * np.pi, nombre)
        # Décroissance de l'ordre de la milliseconde : c'est la réponse
        # impulsionnelle du filtre de canal qui la fixe, pas l'éclair.
        duree = max(4, int(0.001 * f_ech))
        forme = np.exp(-np.arange(duree) / (duree / 4.0))
        for position, force, phase in zip(positions, forces, phases):
            impulsion = force * np.exp(1j * phase) * forme
            sortie[position : position + duree] += impulsion

    etat.reste = sortie[taille:].copy()
    return sortie[:taille]


# ---------------------------------------------------------------------------
# Stations voisines
# ---------------------------------------------------------------------------

@dataclass
class EtatBrouilleur:
    decalage: EtatDecalage = field(default_factory=EtatDecalage)
    phase_audio: float = 0.0


def co_canal(
    taille: int, niveau: float, ecart: float, f_ech: float, etat: EtatBrouilleur,
) -> np.ndarray:
    """Une seconde porteuse, non modulée, à `ecart` hertz de la nôtre.

    C'est le cas de deux avions qui appuient ensemble sur l'alternat. Les deux
    porteuses s'additionnent, et le détecteur d'enveloppe voit leur module
    battre à la fréquence de leur écart : **le sifflement est l'écart de
    fréquence des deux émetteurs**, rien d'autre. À mille hertz d'écart on
    entend mille hertz.

    Rien n'est ajouté au son : on additionne deux nombres complexes, et le
    sifflement sort du module. C'est aussi pour cela que l'aéronautique est
    restée en amplitude — en fréquence, le plus fort aurait effacé l'autre en
    silence, et personne n'aurait su qu'il y avait eu collision.
    """
    if niveau <= 0.0 or taille <= 0:
        return np.zeros(taille, dtype=np.complex128)
    porteuse = np.full(taille, niveau, dtype=np.complex128)
    return decaler(porteuse, ecart, f_ech, etat.decalage)


def canal_adjacent(
    taille: int, niveau: float, ecart: float, excursion: float, f_ech: float,
    etat: EtatBrouilleur, modulation: str = "AM",
) -> np.ndarray:
    """La station du canal voisin, modulée par un ton, décalée de `ecart`.

    Le filtre de fréquence intermédiaire la rejette — mais jamais complètement,
    et ce qui passe se mêle au signal utile. En radiodiffusion AM, l'espacement
    étant de neuf kilohertz, c'est le **sifflement à neuf kilohertz** qu'on
    entendait sur toutes les stations le soir, quand la propagation ramenait les
    émetteurs lointains.
    """
    if niveau <= 0.0 or taille <= 0:
        return np.zeros(taille, dtype=np.complex128)

    increment = 2.0 * np.pi * 900.0 / f_ech
    phase = etat.phase_audio + increment * np.arange(1, taille + 1)
    etat.phase_audio = float(np.mod(phase[-1], 2.0 * np.pi))
    audio = np.sin(phase)

    if modulation == "FM":
        porteuse = niveau * np.exp(
            1j * 2.0 * np.pi * excursion * np.cumsum(audio) / f_ech
        )
    else:
        porteuse = (niveau * (1.0 + 0.7 * audio)).astype(np.complex128)
    return decaler(porteuse, ecart, f_ech, etat.decalage)
