"""
Orchestration : de l'image de départ à l'image telle qu'un téléviseur l'affiche.

C'est le seul module que l'interface graphique a besoin de connaître.
Il enchaîne colorimétrie, codage, canal, décodage, et le chemin retour.

Un point de méthode : le trajet aller et le trajet retour sont **exactement
symétriques**. Si l'on désactive toute limitation de bande et tout défaut de
canal, l'image de sortie est identique à l'image d'entrée, au bruit numérique
près. Tout écart observé est donc imputable à un phénomène simulé, jamais à
une approximation de la chaîne — c'est ce que vérifie
`tests/test_pipeline.py::test_chaine_transparente`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import canal as canal_mod
from . import colorimetrie as col
from . import decodeur as dec
from . import encodeur as enc
from . import filtres
from . import tube as tube_mod
from . import vhs as vhs_mod
from .constantes import Norme, obtenir_norme


@dataclass
class Parametres:
    """Tous les réglages de la chaîne, en un seul objet."""

    norme: str = "PAL-BG"

    tube: tube_mod.ParametresTube = field(default_factory=tube_mod.ParametresTube)
    """La caméra, tout en amont — avant même la correction de gamma.

    Sa place n'est pas négociable : le tube analyseur est ce qui **fabrique**
    le signal, en mesurant la charge que la lumière a soutirée à sa cible. Tout
    ce qui suit, matriçage compris, travaille sur ce qu'il a bien voulu rendre."""

    encodage: enc.ParametresEncodage = field(default_factory=enc.ParametresEncodage)
    canal: canal_mod.ParametresCanal = field(default_factory=canal_mod.ParametresCanal)
    vhs: vhs_mod.ParametresVHS = field(default_factory=vhs_mod.ParametresVHS)
    """Passage par un magnétoscope, entre le canal et le téléviseur.

    La place n'est pas arbitraire : on enregistre ce qui sort de l'antenne, et
    l'on rebranche la cassette sur la prise du téléviseur. Le magnétoscope
    hérite donc du bruit du canal, et y ajoute le sien."""

    decodage: dec.ParametresDecodage = field(default_factory=dec.ParametresDecodage)

    primaires_source: str = "bt709"
    """Primaires attribuées à l'image de départ. Un fichier PNG ordinaire est
    en sRGB, donc en primaires BT.709."""

    simuler_primaires: bool = False
    """Si vrai, l'image est réinterprétée dans les primaires de la norme, puis
    ramenée en BT.709 pour l'affichage. C'est ce qui permet de voir à quoi
    ressemblait vraiment une image aux primaires NTSC 1953 sur un écran
    d'aujourd'hui. Si faux, on suppose que l'écran de restitution a les
    primaires de la norme — l'hypothèse implicite de tous les téléviseurs
    de l'époque."""

    simuler_gamma: bool = True
    """Applique la correction de gamma de la norme avant matriçage. C'est
    l'origine de la non-constant-luminance ; le désactiver revient à matricer
    en lumière linéaire, ce qu'aucune norme n'a jamais fait, mais qui montre
    bien ce que le gamma coûte."""

    taille_sortie: tuple[int, int] | None = None
    """(hauteur, largeur) de l'image rendue. Par défaut, celle de l'entrée."""


@dataclass
class Resultat:
    """Tout ce que produit un passage complet dans la chaîne."""

    source: np.ndarray
    """Image de départ en sRGB, ramenée à la taille de sortie."""

    finale: np.ndarray
    """Image après aller-retour complet, en sRGB."""

    norme: Norme
    parametres: Parametres

    signal: enc.SignalVideo = field(repr=False)
    composite_emis: np.ndarray = field(repr=False)
    composite_recu: np.ndarray = field(repr=False)
    decodee: dec.ImageDecodee = field(repr=False)

    rgb_prime_source: np.ndarray = field(repr=False)
    """R'G'B' à l'entrée du codeur, à la géométrie de la norme."""

    rgb_prime_decode: np.ndarray = field(repr=False)
    """R'G'B' en sortie du décodeur, avant écrêtage."""

    carte_ecretage: np.ndarray = field(repr=False)
    """Masque des pixels réellement tronqués par les bornes du cube RGB."""

    amplitude_ecretage: np.ndarray = field(repr=False)
    """De combien chaque pixel débordait, avant écrêtage."""

    @property
    def taux_ecretage(self) -> float:
        return float(np.mean(self.carte_ecretage))


# ---------------------------------------------------------------------------

def encoder_decoder(image_srgb: np.ndarray, params: Parametres | None = None) -> Resultat:
    """Fait subir à une image sRGB (H, W, 3) dans [0, 1] le trajet complet."""
    params = params or Parametres()
    norme = obtenir_norme(params.norme)

    source = np.clip(np.asarray(image_srgb, dtype=np.float64), 0.0, 1.0)
    if source.ndim == 2:
        source = np.repeat(source[..., None], 3, axis=-1)
    if source.shape[-1] == 4:
        source = source[..., :3]

    # ---- aller : du fichier au signal R'G'B' du studio ---------------------
    lineaire = col.srgb_vers_lineaire(source)
    if params.simuler_primaires:
        lineaire = col.convertir_primaires(
            lineaire, params.primaires_source, norme.primaires
        )
    lineaire = tube_mod.appliquer(lineaire, params.tube)
    gamma = norme.gamma_affichage if params.simuler_gamma else 1.0
    rgb_prime = col.oetf_camera(lineaire, gamma)

    # ---- codage, transmission, décodage ------------------------------------
    signal = enc.encoder(rgb_prime, norme, params.encodage)
    recu = canal_mod.traverser(signal.composite, norme, params.canal)
    recu = vhs_mod.enregistrer_et_relire(recu, norme, params.vhs)
    decodee = dec.decoder(recu, signal, params.decodage)

    # ---- retour : du R'G'B' reçu à l'image affichée ------------------------
    rgb_decode = decodee.rgb_prime

    # L'écrêtage n'est pas un détail d'implémentation, c'est une étape
    # physique : le tube ne sait pas produire une luminance négative, ni plus
    # de lumière que son maximum. Après matriçage inverse, les couleurs dont
    # la chrominance a bavé hors du cube RGB sont tronquées — et l'écrêtage
    # d'un seul canal déplace la teinte, il ne fait pas que la désaturer.
    #
    # Le seuil compte : un dépassement de 10⁻⁶ n'est pas un écrêtage, c'est du
    # bruit d'arrondi. On ne retient que ce qui déplacerait la valeur d'au
    # moins un échelon sur huit bits — en dessous, rien n'est visible et la
    # statistique ne dirait plus rien.
    seuil = 1.0 / 255.0
    depassement = np.maximum(np.maximum(-rgb_decode, rgb_decode - 1.0), 0.0)
    amplitude_ecretage = depassement.max(axis=-1)
    carte_ecretage = amplitude_ecretage > seuil
    rgb_affiche = np.clip(rgb_decode, 0.0, 1.0)

    lineaire_sortie = col.eotf_ecran(rgb_affiche, gamma)
    if params.simuler_primaires:
        lineaire_sortie = col.convertir_primaires(
            lineaire_sortie, norme.primaires, params.primaires_source
        )
    finale = np.clip(col.lineaire_vers_srgb(lineaire_sortie), 0.0, 1.0)

    # ---- mise à la taille de sortie ----------------------------------------
    hauteur, largeur = params.taille_sortie or source.shape[:2]
    finale = _redimensionner(finale, hauteur, largeur)
    source_alignee = _redimensionner(source, hauteur, largeur)

    return Resultat(
        source=source_alignee,
        finale=finale,
        norme=norme,
        parametres=params,
        signal=signal,
        composite_emis=signal.composite,
        composite_recu=recu,
        decodee=decodee,
        rgb_prime_source=rgb_prime,
        rgb_prime_decode=rgb_decode,
        carte_ecretage=carte_ecretage,
        amplitude_ecretage=amplitude_ecretage,
    )


def _redimensionner(image: np.ndarray, hauteur: int, largeur: int) -> np.ndarray:
    if image.shape[0] != hauteur:
        image = filtres.reechantillonner_vertical(image, hauteur)
    if image.shape[1] != largeur:
        canaux = [filtres.reechantillonner(image[..., k], largeur) for k in range(3)]
        image = np.stack(canaux, axis=-1)
    return np.clip(image, 0.0, 1.0)


def comparer_normes(
    image_srgb: np.ndarray,
    codes: tuple[str, ...] = ("NTSC-M", "PAL-BG", "SECAM-L"),
    params: Parametres | None = None,
) -> dict[str, Resultat]:
    """Passe la même image dans plusieurs normes, à réglages de canal identiques."""
    import copy

    resultats = {}
    for code in codes:
        p = copy.deepcopy(params or Parametres())
        p.norme = code
        if p.taille_sortie is None:
            p.taille_sortie = image_srgb.shape[:2]
        resultats[code] = encoder_decoder(image_srgb, p)
    return resultats
