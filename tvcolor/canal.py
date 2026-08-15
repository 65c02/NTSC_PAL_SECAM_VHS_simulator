"""
Le canal de transmission — tout ce qui abîme le signal entre l'émetteur et l'écran.

Le même canal est appliqué aux trois normes, sans exception ni traitement de
faveur. C'est la condition d'une comparaison honnête : si SECAM encaisse une
erreur de phase que NTSC ne supporte pas, il faut que ce soit **le décodeur**
qui fasse la différence, pas la simulation.

Quatre dégradations, dans l'ordre où elles surviennent physiquement :

1. la **non-linéarité de l'émetteur**, qui produit les erreurs différentielles
   de phase et de gain ;
2. l'**écho**, réflexion du signal sur un obstacle ;
3. la **limitation de bande** du canal radio ;
4. le **bruit** thermique du récepteur.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from . import filtres
from .constantes import F_SC_SECAM_B, F_SC_SECAM_R, Norme


@dataclass
class ParametresCanal:
    """Dégradations infligées au signal composite."""

    rapport_signal_bruit: float | None = None
    """Rapport signal/bruit vidéo en dB (crête-à-crête sur bruit efficace).
    45 dB = excellente réception hertzienne, 30 dB = image « neigeuse »,
    20 dB = à peine regardable. `None` désactive le bruit."""

    phase_differentielle: float = 0.0
    """Erreur de phase, en degrés, pour une unité de luminance.

    C'est le défaut historique du NTSC. L'étage de puissance de l'émetteur
    n'est pas parfaitement linéaire : le déphasage qu'il introduit dépend du
    niveau instantané du signal. Comme la teinte *est* la phase, un visage
    dans l'ombre et le même visage en pleine lumière n'ont plus la même
    couleur. D'où le bouton « Tint » sur les téléviseurs américains — et le
    surnom *Never Twice the Same Color*."""

    gain_differentiel: float = 0.0
    """Variation relative du gain de chrominance par unité de luminance.
    Se traduit par une saturation qui dépend de la luminosité."""

    echo_amplitude: float = 0.0
    """Amplitude relative d'un écho (« image fantôme »)."""

    echo_retard_us: float = 0.5
    """Retard de l'écho en microsecondes."""

    bande_canal: float | None = None
    """Limitation de bande globale du canal, en Hz. `None` = bande de la norme."""

    graine: int = 12345
    """Germe du générateur de bruit, pour des résultats reproductibles."""

    @property
    def est_transparent(self) -> bool:
        return (
            self.rapport_signal_bruit is None
            and self.phase_differentielle == 0.0
            and self.gain_differentiel == 0.0
            and self.echo_amplitude == 0.0
            and self.bande_canal is None
        )


# ---------------------------------------------------------------------------

def bande_chroma(norme: Norme) -> tuple[float, float]:
    """Fenêtre spectrale occupée par la chrominance, pour l'extraire du composite."""
    nyquist = 0.5 * norme.f_echantillonnage
    if norme.famille == "SECAM":
        basse = F_SC_SECAM_B - 0.9e6
        haute = F_SC_SECAM_R + 0.9e6
    else:
        basse = norme.f_sc - 1.5e6
        haute = norme.f_sc + 1.5e6
    return max(basse, 0.05e6), min(haute, 0.95 * nyquist)


def traverser(
    composite: np.ndarray, norme: Norme, params: ParametresCanal | None = None
) -> np.ndarray:
    """Fait subir au signal composite le voyage jusqu'au récepteur."""
    params = params or ParametresCanal()
    if params.est_transparent:
        return composite.copy()

    s = np.asarray(composite, dtype=np.float64)
    f_e = norme.f_echantillonnage

    s = _erreurs_differentielles(s, norme, params)
    s = _echo(s, f_e, params)
    s = _limiter_bande(s, norme, params)
    s = _bruit(s, norme, params)
    return s


# ---------------------------------------------------------------------------

def _erreurs_differentielles(s, norme, params):
    """Non-linéarité de l'émetteur : le retard et le gain dépendent du niveau.

    **Phase différentielle.** On ne fait pas tourner artificiellement un
    vecteur de chrominance : on applique au signal entier un **retard variable
    avec le niveau instantané**, ce qu'est physiquement une phase
    différentielle. Un retard τ déphase la sous-porteuse de 2π·f_sc·τ ; en
    faisant varier τ proportionnellement à la luminance, on obtient
    exactement le défaut mesuré sur les émetteurs.

    Ce choix de modélisation a une conséquence importante et voulue : le
    SECAM y est naturellement insensible dans les aplats, puisqu'un retard
    constant ne change pas une fréquence instantanée. Il n'y a là aucun
    traitement de faveur — le même signal traverse le même canal ; c'est la
    modulation de fréquence qui est indifférente à ce que la modulation
    d'amplitude subit de plein fouet.

    **Gain différentiel.** Amplification de la chrominance dépendant du
    niveau. Le SECAM l'ignore aussi, mais pour une autre raison : son
    discriminateur ne lit que la fréquence, et le limiteur écrase toute
    information d'amplitude avant lui.
    """
    dp = params.phase_differentielle
    dg = params.gain_differentiel
    if dp == 0.0 and dg == 0.0:
        return s

    f_e = norme.f_echantillonnage
    # Niveau de luminance « lent » : c'est lui qui pilote la non-linéarité.
    niveau = filtres.passe_bas(s, 0.5e6, f_e)

    if dg != 0.0:
        basse, haute = bande_chroma(norme)
        chroma = filtres.passe_bande(s, basse, haute, f_e)
        s = s + dg * niveau * chroma

    if dp != 0.0:
        # Retard, en échantillons, correspondant à dp degrés de sous-porteuse
        # pour une unité de luminance.
        retard = (dp / 360.0) / norme.f_sc * f_e * niveau
        n_lignes, n_ech = s.shape
        colonnes = np.arange(n_ech)[None, :] - retard
        rangees = np.broadcast_to(np.arange(n_lignes)[:, None], s.shape)
        # Ordre 5 : à quatre échantillons par cycle de sous-porteuse, une
        # spline cubique se trompe encore de 3 % sur le déphasage ; une
        # quintique tombe à 0,4 %.
        s = ndimage.map_coordinates(
            s, [rangees, colonnes], order=5, mode="nearest"
        )
    return s


def _echo(s, f_e, params):
    """Ajoute une réplique retardée du signal — l'image fantôme des antennes râteau."""
    if params.echo_amplitude == 0.0:
        return s
    retard = int(round(params.echo_retard_us * 1e-6 * f_e))
    if retard <= 0:
        return s
    decale = np.zeros_like(s)
    decale[:, retard:] = s[:, :-retard]
    return s + params.echo_amplitude * decale


def _limiter_bande(s, norme, params):
    """Coupe le signal à la bande du canal radio."""
    if params.bande_canal is None:
        return s
    return filtres.passe_bas(s, params.bande_canal, norme.f_echantillonnage)


def _bruit(s, norme, params):
    """Bruit blanc gaussien, limité à la bande du canal.

    Le rapport signal/bruit est défini à la manière de la vidéo : amplitude
    crête-à-crête du signal image (1,0 en unités normalisées) divisée par la
    valeur efficace du bruit.

    Le bruit qui tombe dans la bande de chrominance est celui qui compte le
    plus : en NTSC et PAL il perturbe amplitude *et* phase, donc saturation
    *et* teinte. En SECAM il ne perturbe que la fréquence instantanée — mais
    quand il devient assez fort pour faire décrocher le discriminateur, il
    produit des taches colorées brutales et isolées, le « feu » caractéristique
    des images SECAM bruitées.
    """
    if params.rapport_signal_bruit is None:
        return s
    sigma = 10.0 ** (-params.rapport_signal_bruit / 20.0)
    rng = np.random.default_rng(params.graine)
    bruit = rng.standard_normal(s.shape)
    bruit = filtres.passe_bas(
        bruit, params.bande_canal or norme.bande_y, norme.f_echantillonnage
    )
    # Le filtrage réduit la variance : on renormalise pour respecter le S/B demandé.
    efficace = float(np.sqrt(np.mean(bruit**2)))
    if efficace > 0.0:
        bruit *= sigma / efficace
    return s + bruit
