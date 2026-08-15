"""
tvcolor — simulation du codage couleur de la télévision analogique.

Bibliothèque de calcul pure (numpy/scipy), sans aucune dépendance à Qt.
Elle reconstruit le *signal composite réel* d'une image, ligne par ligne,
puis le décode comme le ferait un téléviseur : les artefacts visibles
(dot crawl, cross-color, barres de Hanover, « feu » SECAM) ne sont jamais
dessinés, ils émergent du calcul.

Chaîne complète, cf. `pipeline.encoder_decoder` :

    sRGB → linéaire → primaires → OETF caméra → R'G'B'
         → matriçage Y'/chroma → limitation de bande
         → modulation sur sous-porteuse → canal
         → séparation Y/C → démodulation → matriçage inverse → sRGB
"""

from .constantes import NORMES, Norme, obtenir_norme
from .pipeline import Parametres, Resultat, encoder_decoder

__all__ = [
    "NORMES",
    "Norme",
    "obtenir_norme",
    "Parametres",
    "Resultat",
    "encoder_decoder",
]

__version__ = "1.0.0"
