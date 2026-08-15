"""
Décodage : du signal composite reçu à l'image R'G'B'.

Le décodeur ne voit que le tableau `composite`. Il ne sait pas ce qu'il y
avait dans l'image d'origine, ni ce que le canal a fait subir au signal. Il
doit tout reconstruire à partir de deux hypothèses :

* la sous-porteuse est à telle fréquence et telle phase (que le burst lui
  confirme à chaque ligne) ;
* la luminance varie peu d'une ligne à la suivante.

La seconde hypothèse est fausse partout où l'image a un contour horizontal.
Toute la famille des artefacts de séparation Y/C — points rampants,
moirages colorés — naît de cette hypothèse prise en défaut.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sig

from . import canal, filtres, matrices, porteuse
from .constantes import (
    F_SC_SECAM_B,
    F_SC_SECAM_R,
    Norme,
    SECAM_DEVIATION_B,
    SECAM_DEVIATION_R,
)
from .encodeur import SignalVideo

SEPARATEURS = ("parfait", "notch", "peigne", "peigne3")


@dataclass
class ParametresDecodage:
    """Réglages du récepteur."""

    separateur: str = "peigne"
    """Comment séparer luminance et chrominance :

    * `parfait` — court-circuite le composite et reprend les composantes
      telles qu'elles ont été limitées en bande à l'émission. Ce n'est pas un
      décodeur réalisable : c'est la **référence** qui isole le coût du seul
      matriçage et de la seule limitation de bande.
    * `notch` — réjecteur de bande centré sur la sous-porteuse. Le décodeur
      du pauvre, universel jusque dans les années 1980.
    * `peigne` — filtre en peigne à une ligne (NTSC) ou deux lignes (PAL).
    * `peigne3` — peigne symétrique à trois lignes.

    SECAM ignore ce réglage : ses sous-porteuses sont des multiples entiers de
    la fréquence ligne, elles ne s'inversent donc jamais d'une ligne à
    l'autre, et aucun peigne ne peut les annuler. Seul le réjecteur existe."""

    ligne_a_retard: bool = True
    """PAL uniquement. À `True`, c'est le PAL-D : le récepteur moyenne deux
    lignes et l'erreur de phase se compense. À `False`, c'est le PAL-S des
    tout premiers récepteurs, qui s'en remettait à l'œil du spectateur — d'où
    les **barres de Hanover**, ce striage horizontal des couleurs quand la
    phase dérive."""

    bande_chroma: float | None = None
    """Coupure du passe-bas appliqué aux composantes démodulées, en Hz."""

    desaccord_sous_porteuse: float = 0.0
    """Écart, en Hz, entre l'oscillateur local et la vraie sous-porteuse.
    Produit une dérive de teinte progressive le long de chaque ligne."""

    erreur_teinte: float = 0.0
    """Déréglage du bouton « teinte », en degrés."""

    gain_saturation: float = 1.0
    """Réglage de saturation du récepteur."""


@dataclass
class ImageDecodee:
    rgb_prime: np.ndarray
    luma: np.ndarray
    chroma1: np.ndarray
    chroma2: np.ndarray
    composite_recu: np.ndarray = field(repr=False)
    chroma_extraite: np.ndarray = field(repr=False)
    norme: Norme = field(repr=False, default=None)


# ---------------------------------------------------------------------------

def decoder(
    signal_recu: np.ndarray,
    reference: SignalVideo,
    params: ParametresDecodage | None = None,
) -> ImageDecodee:
    """Décode le composite reçu. `reference` fournit la géométrie et la norme."""
    params = params or ParametresDecodage()
    norme = reference.norme

    # On retire le piédestal : le récepteur cale son noir sur le niveau de
    # suppression et étire ce qui reste sur toute la dynamique.
    piedestal = norme.piedestal if reference.parametres.piedestal else 0.0
    s = (np.asarray(signal_recu, dtype=np.float64) - piedestal) / (1.0 - piedestal)

    if norme.famille == "SECAM":
        image = _decoder_secam(s, reference, params)
    else:
        image = _decoder_quadrature(s, reference, params)

    # Recadrage sur la partie visible. Tous les transitoires d'établissement
    # des filtres sont restés dans le temps de suppression.
    return _recadrer(image, reference)


def _recadrer(image: ImageDecodee, reference: SignalVideo) -> ImageDecodee:
    # `partie_active` découpe l'axe 1, ce qui convient aussi bien à un plan
    # (lignes, colonnes) qu'à une image (lignes, colonnes, 3).
    decoupe = reference.partie_active
    return ImageDecodee(
        rgb_prime=decoupe(image.rgb_prime),
        luma=decoupe(image.luma),
        chroma1=decoupe(image.chroma1),
        chroma2=decoupe(image.chroma2),
        composite_recu=decoupe(image.composite_recu),
        chroma_extraite=decoupe(image.chroma_extraite),
        norme=image.norme,
    )


# ---------------------------------------------------------------------------
# Séparation luminance / chrominance
# ---------------------------------------------------------------------------

LARGEUR_TRAP = 0.6e6
"""Demi-largeur du piège de sous-porteuse dans la voie luminance, en hertz.

Un point de fidélité qui change tout. Dans un téléviseur, la voie luminance
et la voie chrominance ne sont **pas** complémentaires : ce sont deux filtres
indépendants, un réjecteur étroit d'un côté, un amplificateur passe-bande de
l'autre. Leur somme ne reconstitue pas le composite.

Si l'on imposait la complémentarité (chroma = composite - luma), le piège
devrait être aussi large que la bande de chrominance, soit ±1,3 MHz, et il
avalerait toute trace de sous-porteuse : plus aucun dot crawl n'apparaîtrait.
On aurait simulé un téléviseur qui n'a jamais existé. Un vrai piège LC est
étroit — ±0,6 MHz environ — et laisse donc passer les bandes latérales de la
chrominance, celles-là mêmes qui dessinent les points rampants sur les
contours verticaux des aplats colorés.
"""


def separer_y_c(
    s: np.ndarray, norme: Norme, methode: str
) -> tuple[np.ndarray, np.ndarray]:
    """Sépare le composite en (luminance, chrominance).

    Les deux sorties sont produites par des chemins indépendants, comme dans
    un récepteur réel. Ce qui fuit de l'une vers l'autre est précisément ce
    qui produit les artefacts : chrominance résiduelle dans la luma
    (*dot crawl*), luminance fine captée par la voie chroma (*cross-color*).
    """
    f_e = norme.f_echantillonnage
    basse, haute = canal.bande_chroma(norme)

    # La voie chrominance est la même pour tous les séparateurs : un
    # passe-bande centré sur la sous-porteuse. Ce qui change d'un séparateur
    # à l'autre, c'est ce qu'on lui présente en entrée.
    if methode == "notch":
        luma = filtres.coupe_bande(
            s, norme.f_sc - LARGEUR_TRAP, norme.f_sc + LARGEUR_TRAP, f_e
        )
        chroma = filtres.passe_bande(s, basse, haute, f_e)
        return luma, chroma

    if methode in ("peigne", "peigne3"):
        # Combien de lignes de retard faut-il pour que la chroma s'inverse ?
        #
        # NTSC : 180,00° par ligne → une seule ligne suffit.
        # PAL  : 270,58° par ligne, ce qui ne convient pas ; mais sur DEUX
        #        lignes cela fait 541,15°, soit 181,15° modulo un tour — assez
        #        proche de l'inversion pour que le peigne fonctionne. C'est
        #        exactement pourquoi les peignes PAL utilisent un retard de
        #        2H (128 µs) là où les peignes NTSC se contentent de 1H.
        avance = porteuse.avance_de_phase_par_ligne(norme)
        retard = 1 if abs(avance - 180.0) < 45.0 else 2

        if methode == "peigne3":
            luma, difference = _peigne_symetrique(s, retard)
        else:
            precedente = filtres._decaler_lignes(s, retard)
            luma = 0.5 * (s + precedente)
            difference = 0.5 * (s - precedente)

        # La différence entre lignes contient la chrominance… et tout ce que
        # l'image a de discontinu verticalement. Le passe-bande n'en garde que
        # la part située dans la fenêtre de sous-porteuse ; le reste — les
        # contours horizontaux — passera quand même, et ressortira en couleur.
        chroma = filtres.passe_bande(difference, basse, haute, f_e)
        return luma, chroma

    raise ValueError(f"séparateur inconnu : {methode!r}")


def _peigne_symetrique(s: np.ndarray, retard: int):
    precedente = filtres._decaler_lignes(s, retard)
    suivante = filtres._decaler_lignes(s, -retard)
    luma = 0.25 * precedente + 0.5 * s + 0.25 * suivante
    return luma, s - luma


# ---------------------------------------------------------------------------
# NTSC et PAL
# ---------------------------------------------------------------------------

def _decoder_quadrature(s, reference, params):
    norme = reference.norme
    f_e = norme.f_echantillonnage
    indices = reference.indices
    n_ech = s.shape[1]
    coupure = params.bande_chroma or max(norme.bande_c1, norme.bande_c2)

    if params.separateur == "parfait":
        # Référence théorique : on reprend les composantes telles qu'elles ont
        # été filtrées à l'émission, sans passer par le composite. Aucune
        # diaphotie possible, donc aucun dot crawl ni cross-color : il ne
        # reste que la perte due au matriçage et à la bande passante.
        luma = reference.ref_luma
        if norme.famille == "NTSC":
            u, v = matrices.iq_vers_uv(reference.ref_c1, reference.ref_c2)
        else:
            u, v = reference.ref_c1, reference.ref_c2
        chroma_extraite = np.zeros_like(luma)
    else:
        luma, chroma_extraite = separer_y_c(s, norme, params.separateur)

        # Oscillateur local du récepteur. S'il est légèrement désaccordé, sa
        # phase dérive le long de la ligne : la teinte glisse de gauche à
        # droite, en un arc-en-ciel horizontal.
        phi = porteuse.phase(
            norme,
            indices,
            n_ech,
            f_sc=norme.f_sc + params.desaccord_sous_porteuse,
            phase_initiale_deg=params.erreur_teinte,
        )
        u_brut, v_brut = porteuse.demoduler_quadrature(chroma_extraite, phi)

        # Le passe-bas élimine les produits à 2·f_sc et borne la résolution
        # chromatique horizontale. C'est ici que se joue la bavure des
        # couleurs : 1,3 MHz sur une ligne active de 52 µs, cela fait environ
        # 68 alternances — soit à peine 135 « pixels de couleur » par ligne,
        # contre plus de 400 pour la luminance.
        u = filtres.passe_bas(u_brut, coupure, f_e)
        v = filtres.passe_bas(v_brut, coupure, f_e)

        if norme.famille == "PAL":
            # 1. rétablir le signe de V, que l'émetteur alternait ;
            v = v * porteuse.signe_pal(indices)
            # 2. moyenner avec la ligne précédente : les erreurs de phase,
            #    opposées d'une ligne à l'autre, s'annulent. Il ne reste
            #    qu'une perte de saturation en cos θ — invisible là où une
            #    dérive de teinte aurait sauté aux yeux.
            if params.ligne_a_retard:
                u = filtres.moyenne_ligne_a_retard(u)
                v = filtres.moyenne_ligne_a_retard(v)

    u = u * params.gain_saturation
    v = v * params.gain_saturation
    rgb = matrices.yuv_vers_rgb(np.stack([luma, u, v], axis=-1))

    return ImageDecodee(
        rgb_prime=rgb,
        luma=luma,
        chroma1=u,
        chroma2=v,
        composite_recu=s,
        chroma_extraite=chroma_extraite,
        norme=norme,
    )


# ---------------------------------------------------------------------------
# SECAM
# ---------------------------------------------------------------------------

def _decoder_secam(s, reference, params):
    """Décodage SECAM : anti-cloche, discriminateur de fréquence, mémoire de ligne."""
    norme = reference.norme
    f_e = norme.f_echantillonnage
    indices = reference.indices
    est_rouge = porteuse.secam_ligne_rouge(indices)[:, None]
    coupure = params.bande_chroma or norme.bande_c1

    if params.separateur == "parfait":
        luma = reference.ref_luma
        db, dr = reference.ref_c1, reference.ref_c2
        chroma = np.zeros_like(luma)
    else:
        basse, haute = canal.bande_chroma(norme)
        luma = filtres.coupe_bande(s, basse, haute, f_e)
        chroma = filtres.passe_bande(s, basse, haute, f_e)

        # 1. Anti-cloche : on annule la préaccentuation haute fréquence.
        #    Indispensable AVANT le limiteur, puisque c'est de l'information
        #    d'amplitude qu'on rétablit.
        chroma_plate = filtres.appliquer_reponse(
            chroma, filtres.reponse_anti_cloche, f_e
        )

        # 2. Discriminateur de fréquence à quadrature, calé sur la fréquence
        #    de repos de la ligne — que le récepteur connaît grâce aux
        #    signaux d'identification de trame.
        f_repos = np.where(est_rouge, F_SC_SECAM_R, F_SC_SECAM_B)
        deviation = np.where(est_rouge, SECAM_DEVIATION_R, SECAM_DEVIATION_B)
        ecart = porteuse.demoduler_frequence(
            chroma_plate, f_repos, f_e, filtres.passe_bas
        )

        # 3. Retour au signal de différence de couleur. La fenêtre du
        #    passe-bande borne physiquement ce que le discriminateur peut
        #    voir : au-delà, il décroche. C'est le décrochage qui produit les
        #    taches colorées vives du « feu » SECAM.
        composante = np.clip(ecart, -1.0e6, 1.0e6) / deviation

        # 4. Désaccentuation basse fréquence : on rabaisse les aigus relevés à
        #    l'émission, et avec eux le bruit que le canal y a déposé.
        composante = filtres.appliquer_reponse(
            composante, filtres.reponse_desaccentuation_bf, f_e
        )
        composante = filtres.passe_bas(composante, coupure, f_e)

        # 5. Mémoire de ligne. Chaque ligne n'apporte qu'une composante ;
        #    l'autre vient de la ligne précédente, conservée dans le retard de
        #    64 µs. Deux lignes consécutives partagent donc leur chrominance :
        #    la résolution chromatique verticale est divisée par deux, et cela
        #    ne se rattrape jamais.
        precedente = filtres._decaler_lignes(composante, 1)
        dr = np.where(est_rouge, composante, precedente)
        db = np.where(est_rouge, precedente, composante)

    dr = dr * params.gain_saturation
    db = db * params.gain_saturation
    rgb = matrices.ydrdb_vers_rgb(np.stack([luma, dr, db], axis=-1))

    return ImageDecodee(
        rgb_prime=rgb,
        luma=luma,
        chroma1=db,
        chroma2=dr,
        composite_recu=s,
        chroma_extraite=chroma,
        norme=norme,
    )
