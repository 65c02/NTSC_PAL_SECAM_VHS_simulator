"""
Simulateur de radiodiffusion et de radiocommunication.

Le pendant sonore de `tvcolor` : on reconstruit le **signal réellement
transmis** — l'enveloppe complexe de la porteuse, modulée en amplitude ou en
fréquence — on lui fait traverser un canal bruité, et on le démodule comme le
ferait le récepteur. Ce qu'on entend n'est pas un effet appliqué à un son ;
c'est ce qui ressort de la démodulation.

Voir `radio.services` pour la table des services simulés, et `docs/radio.md`
pour le détail de la chaîne.
"""

from .services import SERVICES, Service, obtenir_service  # noqa: F401
