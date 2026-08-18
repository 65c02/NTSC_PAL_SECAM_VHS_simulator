"""
Arty : écrire du son dans l'onde de l'image.

Un signal composite est une onde. Une pile d'opérateurs à modulation de
fréquence — celle d'un DX7 — en est une autre. Les additionner revient
exactement à ce que fait un brouilleur sur une antenne, et le résultat n'est pas
un effet plaqué sur l'image : c'est le décodeur du téléviseur qui interprète
l'intrus, et qui en fait des barres, des damiers ou de la couleur selon la
fréquence.

C'est tout l'intérêt de l'exercice. La géométrie qu'on voit n'est pas dessinée,
elle est **déduite** du rapport entre la fréquence du son et celle du balayage.

Voir `arty.dx7` pour les opérateurs, `arty.injection` pour la base de temps, et
`docs/arty.md` pour la table des correspondances.
"""

from .dx7 import ALGORITHMES, Enveloppe, Operateur, Voix, obtenir_algorithme  # noqa: F401
from .injection import ParametresArty, base_de_temps, motif, rendre  # noqa: F401
