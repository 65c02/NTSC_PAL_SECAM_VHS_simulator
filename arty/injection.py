"""
Où le son rencontre l'image : la base de temps du balayage.

TOUT TIENT DANS UNE FORMULE
---------------------------

Un signal composite est un signal **à une dimension**. Le tableau à deux
dimensions qu'on manipule n'est qu'un pliage : l'échantillon `k` de la ligne `n`
est émis à l'instant

    t(n, k) = n / f_ligne + k / f_échantillonnage

C'est ce pliage qui fait toute la géométrie. Une sinusoïde de fréquence `f`
ajoutée au composite y dessine :

- **f / f_ligne cycles par ligne**, c'est-à-dire autant de barres verticales ;
- et une avance de phase d'une ligne à la suivante de `2π f / f_ligne`, dont
  seule la partie fractionnaire compte.

D'où trois cas, et ils sont tout le sujet :

| f / f_ligne | avance par ligne | ce qu'on voit |
|---|---|---|
| entier | 0° | barres verticales **immobiles** |
| demi-entier | 180° | damier, une ligne sur deux inversée |
| quelconque | reste | barres **penchées**, d'autant plus que le reste est grand |

Et un quatrième, le plus spectaculaire : si `f` tombe près de la sous-porteuse,
le décodeur ne peut plus faire la différence entre l'intrus et de la couleur.
**Il choisit la couleur.** Un son devient alors une teinte, sans qu'on l'ait
demandé — c'est le cross-color du chapitre 10, provoqué exprès.

CE QUE CE MODULE NE FAIT PAS
----------------------------

Il ne touche **pas au son**. La voie audio du téléviseur a sa propre porteuse,
plusieurs mégahertz plus haut, et rien de ce qui est écrit ici ne l'approche :
ce qu'on injecte va dans le composite vidéo, exactement là où un brouilleur
agirait. Un test le vérifie en comparant la sortie audio avec et sans
perturbation, qui doivent être identiques au bit près.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from tvcolor import mires
from tvcolor.canal import ParametresCanal
from tvcolor.constantes import Norme, obtenir_norme
from tvcolor.decodeur import ParametresDecodage
from tvcolor.pipeline import Parametres, Resultat, encoder_decoder

from .dx7 import Voix


def base_de_temps(norme: Norme, lignes: int, instant: float = 0.0) -> np.ndarray:
    """Instant d'émission de chaque échantillon du composite, en secondes.

    `instant` décale l'origine : c'est le début de la trame. Le faire avancer
    d'une trame à l'autre anime le motif, comme la phase de la sous-porteuse
    anime le fourmillement des points au chapitre 6.
    """
    colonnes = np.arange(norme.echantillons_ligne_totale) / norme.f_echantillonnage
    rangs = np.arange(lignes) / norme.f_ligne
    return instant + rangs[:, None] + colonnes[None, :]


def motif(frequence: float, norme: Norme) -> dict:
    """Ce qu'une fréquence donnée dessinera, avant même de l'avoir tracée.

    Rendu sous forme de dictionnaire pour que l'interface puisse l'afficher : la
    moitié de l'intérêt de cet outil est de pouvoir prédire le motif, puis de
    vérifier qu'il est bien là.
    """
    cycles = frequence / norme.f_ligne
    reste = cycles % 1.0
    avance = reste * 360.0

    if reste < 0.02 or reste > 0.98:
        allure = "barres verticales immobiles"
    elif abs(reste - 0.5) < 0.02:
        allure = "damier — une ligne sur deux inversée"
    elif reste < 0.5:
        allure = "barres penchées vers la droite"
    else:
        allure = "barres penchées vers la gauche"

    ecart_porteuse = abs(frequence - norme.f_sc)
    if ecart_porteuse < norme.bande_c1:
        allure += " — et de la COULEUR : le décodeur y voit de la chrominance"

    return {
        "frequence": frequence,
        "cycles_par_ligne": cycles,
        "avance_par_ligne": avance,
        "au_dela_de_la_bande": frequence > norme.bande_y,
        "ecart_a_la_sous_porteuse": ecart_porteuse,
        "allure": allure,
    }


@dataclass
class ParametresArty:
    """Tout ce que l'outil sait faire, en un objet."""

    norme: str = "PAL-BG"
    voix: Voix = field(default_factory=Voix)

    niveau: float = 0.08
    """Amplitude injectée, en unités du composite — où le noir vaut 0 et le
    blanc 1. Un centième se devine, un dixième s'impose, la moitié efface
    l'image."""

    instant: float = 0.0
    """Début de la trame, en secondes. Sert à animer le motif."""

    mire: str = "Mire TDF (France)"
    image: np.ndarray | None = None
    """Si `image` est fournie, elle l'emporte sur la mire."""

    taille: tuple[int, int] = (576, 768)

    rapport_signal_bruit: float | None = None
    separateur: str = "peigne"

    def resolue(self) -> Norme:
        return obtenir_norme(self.norme)

    def source(self) -> np.ndarray:
        if self.image is not None:
            return np.clip(np.asarray(self.image, dtype=np.float64), 0.0, 1.0)
        return mires.obtenir_mire(self.mire, *self.taille)


def perturbation(params: ParametresArty, lignes: int) -> np.ndarray:
    """L'onde à ajouter au composite, à la géométrie de la norme."""
    norme = params.resolue()
    temps = base_de_temps(norme, lignes, params.instant)
    return params.niveau * params.voix.rendre(temps)


def rendre(params: ParametresArty | None = None) -> Resultat:
    """Encode, injecte, décode — et rend le résultat complet.

    On passe par `tvcolor.pipeline` sans le contourner : l'onde injectée arrive
    au même endroit qu'un brouilleur, entre le codeur et le canal, et tout ce
    qui suit est la chaîne ordinaire. Les artefacts qu'on observe sont donc ceux
    du chapitre 10, provoqués exprès plutôt que subis.
    """
    params = params or ParametresArty()
    norme = params.resolue()
    source = params.source()

    chaine = Parametres(
        norme=params.norme,
        taille_sortie=source.shape[:2],
        canal=ParametresCanal(rapport_signal_bruit=params.rapport_signal_bruit),
        decodage=ParametresDecodage(separateur=params.separateur),
    )
    chaine.perturbation = perturbation(params, norme.lignes_actives)
    return encoder_decoder(source, chaine)
