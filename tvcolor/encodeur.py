"""
Codage : de l'image R'G'B' au signal composite échantillonné.

Le résultat est un tableau `(n_lignes, n_échantillons)` contenant le signal
vidéo tel qu'il circulerait dans un câble : une luminance, une sous-porteuse
modulée, et rien d'autre. Ce signal est ensuite malmené par `canal.py` puis
rendu à `decodeur.py`, qui n'a accès à aucune information privilégiée — il ne
voit que ce tableau, comme un vrai téléviseur.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import filtres, matrices, porteuse
from .constantes import (
    F_SC_SECAM_B,
    F_SC_SECAM_R,
    Norme,
    SECAM_DEVIATION_B,
    SECAM_DEVIATION_R,
    SECAM_EXCURSION_MAX,
    SECAM_EXCURSION_MIN,
)


# ---------------------------------------------------------------------------
# Normalisation du filtre cloche SECAM
# ---------------------------------------------------------------------------

def _gain_cloche_maximal() -> float:
    """Gain crête de la cloche sur la plage de fréquences réellement occupée.

    On s'en sert pour normaliser l'amplitude de la sous-porteuse SECAM : sans
    cela, la chrominance déborderait largement de l'excursion vidéo aux
    excursions extrêmes.
    """
    f = np.linspace(
        F_SC_SECAM_B + SECAM_EXCURSION_MIN,
        F_SC_SECAM_R + SECAM_EXCURSION_MAX,
        2001,
    )
    return float(np.max(filtres.gain_cloche(f)))


_GAIN_CLOCHE_MAX = _gain_cloche_maximal()


# ---------------------------------------------------------------------------
# Paramètres et résultat
# ---------------------------------------------------------------------------

@dataclass
class ParametresEncodage:
    """Réglages du codeur. `None` signifie « valeur normative de la norme »."""

    bande_y: float | None = None
    bande_c1: float | None = None
    bande_c2: float | None = None
    amplitude_chroma: float = 1.0     # gain de saturation à l'émission
    piedestal: bool = True            # applique le setup de la norme
    entrelace: bool = False
    numero_image: int = 0             # pour animer le fourmillement des points


@dataclass
class SignalVideo:
    """Signal composite, plus les références internes utiles au diagnostic.

    Les tableaux couvrent la **ligne entière**, temps de suppression compris.
    L'image utile occupe les colonnes `[marge, marge + largeur_active[`.

    Les champs `ref_*` ne sont **jamais** consultés par le décodeur : ils
    servent au mode « décodeur idéal » (qui mesure ce que coûterait une
    séparation Y/C parfaite) et aux instruments de mesure.
    """

    composite: np.ndarray
    norme: Norme
    indices: np.ndarray
    parametres: ParametresEncodage
    marge: int
    largeur_active: int

    ref_luma: np.ndarray = field(repr=False)
    ref_c1: np.ndarray = field(repr=False)
    ref_c2: np.ndarray = field(repr=False)
    ref_chroma: np.ndarray = field(repr=False)

    @property
    def n_lignes(self) -> int:
        return self.composite.shape[0]

    @property
    def n_echantillons(self) -> int:
        return self.composite.shape[1]

    @property
    def f_ech(self) -> float:
        return self.norme.f_echantillonnage

    def partie_active(self, tableau: np.ndarray) -> np.ndarray:
        """Extrait la portion visible d'un tableau à la géométrie de la ligne."""
        return tableau[:, self.marge : self.marge + self.largeur_active]

    @property
    def composite_actif(self) -> np.ndarray:
        return self.partie_active(self.composite)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def encoder(
    rgb_prime: np.ndarray,
    norme: Norme,
    params: ParametresEncodage | None = None,
) -> SignalVideo:
    """Code une image R'G'B' gamma-corrigée (H, W, 3) en signal composite.

    L'image est d'abord ramenée à la géométrie de la norme : `lignes_actives`
    rangées, `echantillons_par_ligne` colonnes. Ce second nombre n'est pas un
    choix esthétique — c'est le produit de la durée de ligne active par la
    fréquence d'échantillonnage 4·f_sc, soit 753 points en NTSC et 921 en PAL.
    Toute la résolution horizontale disponible tient là-dedans.
    """
    params = params or ParametresEncodage()
    rgb = np.asarray(rgb_prime, dtype=np.float64)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("l'image doit être de forme (H, W, 3)")

    # --- géométrie ---------------------------------------------------------
    #
    # On code la ligne ENTIÈRE, temps de suppression compris, et l'on prolonge
    # l'image dans ce temps de suppression en répliquant ses colonnes de bord.
    #
    # Ce détail conditionne toute la propreté du résultat. Un signal composite
    # est une porteuse modulée : on ne peut le prolonger artificiellement sans
    # créer une rupture de phase, que le moindre filtre étale ensuite vers
    # l'intérieur de l'image — sur cent colonnes, soit un bon dixième de la
    # largeur. En codant dès le départ la ligne complète, tous les
    # transitoires d'établissement tombent dans la suppression, exactement là
    # où ils tombent dans un vrai téléviseur, et le recadrage final les
    # élimine sans laisser de trace.
    rgb = filtres.reechantillonner_vertical(rgb, norme.lignes_actives)
    largeur_active = norme.echantillons_par_ligne
    marge = norme.marge_suppression
    canaux = [
        filtres.prolonger(
            filtres.reechantillonner(rgb[..., k], largeur_active),
            marge,
            mode="repliquer",
        )
        for k in range(3)
    ]
    rgb = np.stack(canaux, axis=-1)

    indices = porteuse.indices_lignes(
        norme, norme.lignes_actives, params.entrelace, params.numero_image
    )

    # --- matriçage et limitation de bande ----------------------------------
    if norme.famille == "SECAM":
        y, c1, c2, chroma = _coder_secam(rgb, norme, params, indices)
    elif norme.famille == "PAL":
        y, c1, c2, chroma = _coder_pal(rgb, norme, params, indices)
    else:
        y, c1, c2, chroma = _coder_ntsc(rgb, norme, params, indices)

    # --- assemblage du composite -------------------------------------------
    #
    #   S = piédestal + (1 - piédestal) · (Y' + C)
    #
    # Le piédestal (7,5 IRE en NTSC-M) remonte tout le signal image au-dessus
    # du niveau de suppression. Il comprime donc l'excursion utile de 7,5 % :
    # le noir n'est plus au niveau de suppression, et un récepteur mal réglé
    # affiche un noir gris. C'est l'une des raisons pour lesquelles le NTSC
    # japonais, qui s'en passe, paraît plus contrasté.
    piedestal = norme.piedestal if params.piedestal else 0.0
    composite = piedestal + (1.0 - piedestal) * (y + chroma)

    return SignalVideo(
        composite=composite,
        norme=norme,
        indices=indices,
        parametres=params,
        marge=marge,
        largeur_active=largeur_active,
        ref_luma=y,
        ref_c1=c1,
        ref_c2=c2,
        ref_chroma=chroma,
    )


# ---------------------------------------------------------------------------
# NTSC
# ---------------------------------------------------------------------------

def _coder_ntsc(rgb, norme, params, indices):
    """Codage NTSC : matriçage Y'IQ, bandes asymétriques, modulation en quadrature."""
    f_e = norme.f_echantillonnage
    yiq = matrices.rgb_vers_yiq(rgb)
    y, i, q = yiq[..., 0], yiq[..., 1], yiq[..., 2]

    y = filtres.passe_bas(y, params.bande_y or norme.bande_y, f_e)

    # L'asymétrie I/Q est la signature du NTSC : 1,3 MHz sur l'axe orange-cyan,
    # 0,4 MHz seulement sur l'axe vert-magenta. L'œil distingue très mal les
    # variations fines de cette seconde teinte : on peut la brider d'un facteur
    # trois sans que personne ne s'en plaigne. En pratique, la quasi-totalité
    # des récepteurs a ignoré cette subtilité et décodé les deux axes à la même
    # bande étroite — le fameux décodage « I/Q égal », plus simple et moins bon.
    i = filtres.passe_bas(i, params.bande_c1 or norme.bande_c1, f_e)
    q = filtres.passe_bas(q, params.bande_c2 or norme.bande_c2, f_e)

    u, v = matrices.iq_vers_uv(i, q)
    phi = porteuse.phase(norme, indices, y.shape[1])
    chroma = params.amplitude_chroma * porteuse.moduler_quadrature(u, v, phi)
    return y, i, q, chroma


# ---------------------------------------------------------------------------
# PAL
# ---------------------------------------------------------------------------

def _coder_pal(rgb, norme, params, indices):
    """Codage PAL : comme NTSC, mais la composante V change de signe à chaque ligne."""
    f_e = norme.f_echantillonnage
    yuv = matrices.rgb_vers_yuv(rgb)
    y, u, v = yuv[..., 0], yuv[..., 1], yuv[..., 2]

    y = filtres.passe_bas(y, params.bande_y or norme.bande_y, f_e)
    u = filtres.passe_bas(u, params.bande_c1 or norme.bande_c1, f_e)
    v = filtres.passe_bas(v, params.bande_c2 or norme.bande_c2, f_e)

    phi = porteuse.phase(norme, indices, y.shape[1])
    signe = porteuse.signe_pal(indices)          # ±1, une valeur par ligne

    # C = U·sin φ ± V·cos φ. L'unique différence avec NTSC tient dans ce signe.
    chroma = params.amplitude_chroma * porteuse.moduler_quadrature(u, signe * v, phi)
    return y, u, v, chroma


# ---------------------------------------------------------------------------
# SECAM
# ---------------------------------------------------------------------------

def _coder_secam(rgb, norme, params, indices):
    """Codage SECAM : une seule composante par ligne, modulée en fréquence.

    Enchaînement complet :

    1. matriçage Y'D'RD'B ;
    2. limitation de bande des composantes de chrominance ;
    3. **sélection séquentielle** — la ligne ne transporte que D'R ou que D'B ;
    4. **préaccentuation basse fréquence** (rapport 3, autour de 85 kHz) ;
    5. **modulation de fréquence** autour de 4,40625 MHz (rouge) ou
       4,250 MHz (bleu), avec écrêtage de l'excursion ;
    6. **préaccentuation haute fréquence** — le filtre cloche, qui atténue la
       sous-porteuse quand la couleur est proche du gris.

    L'étape 5 est ce qui distingue radicalement SECAM des deux autres : ce
    n'est plus l'amplitude qui porte la couleur, mais la fréquence. D'où
    l'insensibilité totale aux erreurs de phase et de gain du canal — et d'où
    l'impossibilité de faire un fondu enchaîné sur un signal SECAM.
    """
    f_e = norme.f_echantillonnage
    ydrdb = matrices.rgb_vers_ydrdb(rgb)
    y, dr, db = ydrdb[..., 0], ydrdb[..., 1], ydrdb[..., 2]

    y = filtres.passe_bas(y, params.bande_y or norme.bande_y, f_e)
    dr = filtres.passe_bas(dr, params.bande_c2 or norme.bande_c2, f_e)
    db = filtres.passe_bas(db, params.bande_c1 or norme.bande_c1, f_e)

    # 3. Séquentiel : on jette une composante sur deux. Ce n'est pas une perte
    #    définitive — le récepteur la retrouvera dans sa mémoire de ligne —
    #    mais c'est bien une division par deux de la résolution verticale
    #    de la chrominance, et elle est irrécupérable.
    est_rouge = porteuse.secam_ligne_rouge(indices)[:, None]
    composante = np.where(est_rouge, dr, db)

    # 4. Préaccentuation BF.
    composante = filtres.appliquer_reponse(
        composante, filtres.reponse_preaccentuation_bf, f_e
    )

    # 5. Modulation de fréquence.
    f_repos = np.where(est_rouge, F_SC_SECAM_R, F_SC_SECAM_B)
    deviation = np.where(est_rouge, SECAM_DEVIATION_R, SECAM_DEVIATION_B)
    ecart = np.clip(composante * deviation, SECAM_EXCURSION_MIN, SECAM_EXCURSION_MAX)
    f_instantanee = f_repos + ecart

    # La phase est l'intégrale de la fréquence instantanée. On l'initialise
    # sur chaque ligne à la phase qu'aurait la sous-porteuse au repos : les
    # deux fréquences SECAM étant des multiples ENTIERS de f_H (272 et 282),
    # elles retombent en phase à chaque début de ligne. C'est délibéré, cela
    # rend le motif de sous-porteuse stable verticalement plutôt que rampant.
    phi = 2.0 * np.pi * np.cumsum(f_instantanee, axis=1) / f_e

    chroma = np.cos(phi)

    # 6. Filtre cloche, appliqué au signal déjà modulé.
    chroma = filtres.appliquer_reponse(
        chroma, lambda f: filtres.reponse_cloche(f), f_e
    )
    chroma *= params.amplitude_chroma / _GAIN_CLOCHE_MAX

    return y, db, dr, chroma
