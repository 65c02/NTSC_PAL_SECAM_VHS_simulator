"""
Le magnétoscope : ce qu'une cassette VHS fait au signal.

Un magnétoscope n'enregistre pas le signal composite tel qu'il le reçoit. Il ne
le pourrait pas : la bande magnétique et la tête tournante ne tiennent pas les
cinq mégahertz d'un signal de radiodiffusion. Il le **démonte**, enregistre les
morceaux séparément et le remonte à la lecture — et c'est ce démontage, bien
plus que le bruit de bande, qui donne au VHS son aspect si reconnaissable.

Le procédé s'appelle *color-under*, et il tient en trois idées :

1. **séparer** la luminance de la chrominance dès l'entrée, avec un séparateur
   qui n'a rien d'exceptionnel — le magnétoscope hérite donc de tous les
   défauts du chapitre 10, avant même d'avoir enregistré quoi que ce soit ;

2. **moduler la luminance en fréquence**, autour de 3,8 à 4,8 MHz en PAL. La
   modulation de fréquence est insensible aux variations de contact entre la
   tête et la bande, qui sont énormes ; une modulation d'amplitude aurait donné
   une image dont la luminosité fluctuerait au rythme du défilement ;

3. **transposer la chrominance SOUS la luminance**, autour de 627 kHz. D'où
   « color-under ». La place y est étroite — 400 kHz environ — et c'est de là
   que vient la caractéristique la plus voyante du format : **la couleur du VHS
   est huit fois moins fine que sa luminance.**

À quoi s'ajoutent les défauts d'une mécanique : la bande ne défile pas
régulièrement, les têtes se relaient en bas de l'image, et l'oxyde manque par
endroits.

Ce module s'insère entre le canal et le décodeur, exactement comme un
magnétoscope se branche entre l'antenne et le téléviseur.

Ce qui est simulé littéralement, et ce qui l'est par son effet
---------------------------------------------------------------

La transposition de la chrominance est faite **pour de bon** : on multiplie par
un oscillateur local, on filtre, on remultiplie. C'est important, parce que
c'est de là que naissent la perte de résolution chromatique et les erreurs de
phase, et qu'aucune de ces deux choses ne se peint honnêtement.

La modulation de fréquence de la luminance, elle, n'est pas synthétisée : sa
porteuse monte à 4,8 MHz et ses bandes latérales dépasseraient Nyquist sur la
grille du simulateur, si bien qu'on mesurerait surtout du repliement. On en
retient les trois effets réels et mesurables — la limitation de bande, la
préaccentuation avec son dépassement, et le bruit qu'elle façonne — en le
disant plutôt qu'en le masquant.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from . import filtres
from .constantes import Norme

# ---------------------------------------------------------------------------
# Constantes du format
# ---------------------------------------------------------------------------

SOUS_PORTEUSE_625 = 40.125 * 15_625.0
"""Porteuse de chrominance transposée, en 625 lignes : 626 953 Hz.

Le quart de multiple n'est pas une coquette : comme pour la sous-porteuse
couleur elle-même, un rapport non entier avec la fréquence ligne fait que le
motif résiduel s'inverse d'une ligne à l'autre au lieu de s'y superposer."""

SOUS_PORTEUSE_525 = 40.0 * 15_734.264
"""En 525 lignes : 629 371 Hz."""

BANDES = {
    #  vitesse : (bande luma, bande chroma), en hertz
    "SP": (3.0e6, 0.40e6),
    "LP": (2.6e6, 0.35e6),
    "EP": (2.0e6, 0.29e6),
}
"""Bandes passantes enregistrées selon la vitesse de défilement.

Ralentir la bande, c'est réduire la vitesse relative tête/bande, donc la
fréquence maximale enregistrable. Le mode EP triple la durée d'une cassette et
lui coûte un tiers de sa définition.

Les 3 MHz du mode SP donnent les fameuses « 240 lignes » de définition
horizontale du VHS, contre 5 MHz — soit 400 lignes — pour le signal reçu."""

RETARD_CHROMA = 0.6e-6
"""Retard de la chrominance sur la luminance, en secondes.

Les deux voies ne traversent pas les mêmes filtres, et celle de chrominance est
la plus étroite, donc la plus lente. Le résultat se voit à l'œil nu sur un
contour vertical franc : la couleur déborde **à droite** du trait, jamais à
gauche."""


@dataclass
class ParametresVHS:
    """Réglages du magnétoscope."""

    actif: bool = False

    vitesse: str = "SP"
    """« SP », « LP » ou « EP »."""

    generation: int = 1
    """Nombre de passages sur bande. Une copie de copie repasse par toute la
    chaîne, et les pertes s'accumulent — c'est ce qui rendait les cassettes
    échangées entre amis si reconnaissables."""

    usure: float = 0.15
    """État de la bande, de 0 (neuve) à 1 (fatiguée). Commande le bruit, les
    abandons de signal et la gigue."""

    gigue: float = 0.35
    """Irrégularité du défilement, de 0 à 1. C'est l'artefact le plus
    caractéristique du VHS : les lignes ne commencent pas toutes au même
    endroit, et les verticales ondulent."""

    abandons: float = 0.25
    """Fréquence des pertes de signal, de 0 à 1."""

    commutation_tetes: bool = True
    """Perturbation des dernières lignes, là où les deux têtes se relaient."""

    bruit_luma: float = 1.0
    bruit_chroma: float = 1.0
    """Multiplicateurs du bruit, pour pouvoir isoler chaque contribution."""

    depassement: float = 0.8
    """Ampleur du dépassement de la préaccentuation, de 0 à 2. C'est le liseré
    clair qui borde les contours sombres — la signature de tout enregistreur à
    modulation de fréquence."""

    graine: int = 20250817

    def bandes(self) -> tuple[float, float]:
        """Bandes luma et chroma effectives, usure et générations comprises."""
        luma, chroma = BANDES.get(self.vitesse, BANDES["SP"])
        # Chaque génération refait tout le trajet : les deux filtres se
        # composent, et la bande se resserre. Une racine par génération rend
        # compte de la mise en cascade sans l'effondrer dès la seconde copie.
        facteur = 0.93 ** max(0, self.generation - 1)
        facteur *= 1.0 - 0.12 * float(np.clip(self.usure, 0.0, 1.0))
        return luma * facteur, chroma * facteur


# ---------------------------------------------------------------------------
# Sous-porteuse transposée
# ---------------------------------------------------------------------------

def sous_porteuse_transposee(norme: Norme) -> float:
    """Fréquence sous laquelle la chrominance est enregistrée."""
    return SOUS_PORTEUSE_625 if norme.lignes_totales == 625 else SOUS_PORTEUSE_525


def resolution_chroma_lignes(norme: Norme, params: ParametresVHS) -> float:
    """Définition chromatique horizontale, en lignes de télévision.

    La convention est celle des constructeurs : N lignes signifient N/2
    alternances sur une largeur égale à la HAUTEUR de l'image, soit en 4:3
    (N/2)·(4/3) alternances par largeur.
    """
    _, chroma = params.bandes()
    alternances = chroma * norme.duree_ligne_active
    return 2.0 * alternances * 3.0 / 4.0


# ---------------------------------------------------------------------------
# La chaîne
# ---------------------------------------------------------------------------

def enregistrer_et_relire(
    composite: np.ndarray, norme: Norme, params: ParametresVHS | None = None
) -> np.ndarray:
    """Fait passer un signal composite par une cassette.

    Entrée et sortie ont la même forme (lignes, échantillons) : le
    magnétoscope rend un signal composite, c'est tout l'intérêt du procédé —
    on rebranche la prise antenne et le téléviseur n'y voit que du feu.
    """
    params = params or ParametresVHS()
    if not params.actif:
        return composite

    signal = np.asarray(composite, dtype=np.float64)
    alea = np.random.default_rng(params.graine)

    for _ in range(max(1, params.generation)):
        signal = _un_passage(signal, norme, params, alea)
    return signal


def _un_passage(signal, norme, params, alea):
    # La fréquence d'échantillonnage vient de la NORME, jamais de la largeur du
    # tableau : le composite porte la ligne entière, suppression comprise —
    # 1135 points en PAL et non 921. La déduire de la seule durée active
    # donnait 21,8 MHz au lieu de 17,7, et toutes les fréquences se trouvaient
    # décalées d'un quart. La chrominance se transposait alors à côté de sa
    # porteuse et le filtre la jetait : l'image ressortait en noir et blanc.
    f_e = norme.f_echantillonnage
    bande_luma, bande_chroma = params.bandes()

    # La gigue est tirée d'abord, puis remise aux DEUX voies. L'appliquer sur
    # le composite reconstitué serait un contresens : à f_sc = f_e/4, décaler
    # de deux points fait tourner la sous-porteuse d'un demi-tour, et le
    # magenta ressort vert. Un magnétoscope ne fait pas cela — sa porteuse de
    # relecture est régénérée à partir du signal lu, donc décalée d'autant, et
    # l'erreur s'annule dans la démodulation. Ce qui reste est ce qu'on voit :
    # l'image ondule, la couleur ne bouge pas.
    decalages = _decalages_gigue(signal.shape[0], params, f_e, alea)

    luma, chroma = _separer(signal, norme, f_e)
    luma = _voie_luminance(luma, norme, params, f_e, bande_luma, alea)
    luma = _decaler(luma, decalages)
    chroma = _voie_chrominance(
        chroma, norme, params, f_e, bande_chroma, alea, decalages
    )

    signal = luma + chroma
    signal = _abandons(signal, norme, params, alea)
    if params.commutation_tetes:
        signal = _commutation(signal, norme, params, alea)
    return signal


# ---------------------------------------------------------------------------
# Séparation d'entrée
# ---------------------------------------------------------------------------

def _separer(signal, norme, f_e):
    """Sépare luminance et chrominance à l'entrée du magnétoscope.

    Un magnétoscope grand public n'avait pas de filtre en peigne : un simple
    réjecteur, et large. Il hérite donc de tous les défauts du chapitre 10 —
    fourmillement des points inclus — **avant** d'avoir enregistré quoi que ce
    soit. C'est une des raisons pour lesquelles une cassette paraît plus molle
    qu'un direct : la moitié de la perte est déjà faite à l'entrée.
    """
    if norme.famille == "SECAM":
        basse = min(norme.f_sc, norme.f_sc_secondaire or norme.f_sc) - 0.9e6
        haute = max(norme.f_sc, norme.f_sc_secondaire or norme.f_sc) + 0.9e6
    else:
        basse, haute = norme.f_sc - 1.1e6, norme.f_sc + 1.1e6

    chroma = filtres.passe_bande(signal, basse, haute, f_e)
    return signal - chroma, chroma


# ---------------------------------------------------------------------------
# Voie luminance
# ---------------------------------------------------------------------------

def _voie_luminance(luma, norme, params, f_e, bande, alea):
    """Enregistrement et lecture de la luminance.

    La préaccentuation est le point intéressant. Tout enregistreur à modulation
    de fréquence relève fortement les hautes fréquences avant d'écrire, et les
    rabaisse en lisant : le bruit d'un discriminateur croissant avec la
    fréquence, on l'attaque là où il est fort.

    Mais l'accentuation est violente — une dizaine de décibels — et le
    limiteur qui suit écrête les crêtes qu'elle fabrique sur les contours
    francs. La désaccentuation restitue alors un signal dont les dépassements
    ne se compensent plus : il reste un **liseré clair au bord des zones
    sombres**, et c'est la signature visuelle de tout enregistrement
    magnétique à modulation de fréquence. Sur une cassette, on le voit sur
    n'importe quel générique blanc sur noir.
    """
    accentue = _accentuer(luma, f_e, +1.0)
    # Le limiteur de l'enregistreur, qui rogne ce que l'accentuation a créé.
    crete = 1.35
    accentue = np.clip(accentue, -crete, crete)

    accentue = filtres.passe_bas(accentue, bande, f_e)

    # Bruit de la voie luminance. Il est façonné par la désaccentuation qui
    # suit — c'est bien pourquoi on l'ajoute AVANT elle, et non sur l'image
    # finie : ajouté après, il serait blanc, et le grain d'une cassette ne
    # l'est pas.
    if params.bruit_luma > 0.0:
        sigma = 0.003 * params.bruit_luma * (0.4 + float(np.clip(params.usure, 0, 1)))
        accentue = accentue + alea.normal(0.0, sigma, accentue.shape)

    sortie = _accentuer(accentue, f_e, -1.0)

    # Ce que le limiteur a rogné ne revient pas : la désaccentuation rend un
    # signal qui dépasse là où l'accentuation avait été écrêtée.
    if params.depassement > 0.0:
        surplus = sortie - filtres.passe_bas(sortie, bande * 0.45, f_e)
        sortie = sortie + 0.20 * params.depassement * surplus
    return sortie


def _accentuer(x, f_e, sens):
    """Préaccentuation (sens=+1) ou désaccentuation (sens=-1) de la luminance.

    Réseau du premier ordre à épaule, de constante de temps 1,6 µs et de
    remontée bornée à 12 dB — l'ordre de grandeur des enregistreurs de la
    norme. On l'applique dans le domaine des fréquences : la réponse et son
    inverse sont alors exactement réciproques, ce qui garantit qu'une chaîne
    sans limiteur ni bruit rende le signal intact.
    """
    tau = 1.6e-6
    plafond = 10.0 ** (12.0 / 20.0)

    def reponse(f):
        h = (1.0 + 2j * np.pi * f * tau) / (1.0 + 2j * np.pi * f * tau / plafond)
        return h if sens > 0 else 1.0 / h

    return filtres.appliquer_reponse(x, reponse, f_e)


# ---------------------------------------------------------------------------
# Voie chrominance
# ---------------------------------------------------------------------------

def _voie_chrominance(chroma, norme, params, f_e, bande, alea, decalages=None):
    """La transposition sous la luminance, faite pour de bon.

    Le trajet est celui de la machine : on ramène la chrominance en bande de
    base, on la remonte à 627 kHz — sa porteuse d'enregistrement —, la bande
    limite ce qu'elle sait écrire, et la lecture refait le chemin en sens
    inverse.

    Tout le caractère du VHS est là. La chrominance ne dispose plus que de
    400 kHz — contre 1,3 MHz à l'antenne — et sa définition horizontale tombe
    aux alentours de **trente lignes**, là où la luminance en garde deux cent
    quarante. Un aplat rouge sur fond blanc ne bave pas un peu : il bave sur
    un huitième de la largeur utile.

    Le retard de la couleur porte sur l'ENVELOPPE, et non sur la
    sous-porteuse modulée. La nuance décide de tout : retarder la porteuse de
    0,6 µs la ferait tourner de 238° à 4,43 MHz, et le magenta ressortirait
    vert. C'est ce qui s'est produit, et c'est un contresens physique — un
    magnétoscope régénère sa sous-porteuse à partir du burst, il ne la
    transporte pas telle quelle. Le retard décale la couleur dans l'image ;
    il ne la change pas.
    """
    lignes, n = chroma.shape
    t = np.arange(n) / f_e
    f_sous = sous_porteuse_transposee(norme)

    # -- ramener en bande de base
    enveloppe = chroma * np.exp(-2j * np.pi * norme.f_sc * t)[None, :]

    # Retard de la couleur et gigue de défilement s'ajoutent : ce sont deux
    # décalages de la même enveloppe, l'un constant et l'autre ligne à ligne.
    retard = np.full(lignes, RETARD_CHROMA * f_e)
    if decalages is not None:
        retard = retard + decalages
    if np.abs(retard).max() >= 0.05:
        enveloppe = _decaler(enveloppe.real, retard) + 1j * _decaler(
            enveloppe.imag, retard
        )

    # -- remonter à la porteuse d'enregistrement : c'est ce que la tête écrit
    enregistre = enveloppe * np.exp(+2j * np.pi * f_sous * t)[None, :]

    # -- ce que la bande sait écrire, et rien de plus. Passe-bande, et non
    #    passe-bas : le signal n'est pas en bande de base, il est à 627 kHz.
    basse = max(0.05e6, f_sous - bande)
    haute = min(0.45 * f_e, f_sous + bande)
    reel = filtres.passe_bande(enregistre.real, basse, haute, f_e)
    imag = filtres.passe_bande(enregistre.imag, basse, haute, f_e)

    if params.bruit_chroma > 0.0:
        sigma = 0.005 * params.bruit_chroma * (0.4 + float(np.clip(params.usure, 0, 1)))
        reel = reel + alea.normal(0.0, sigma, reel.shape)
        imag = imag + alea.normal(0.0, sigma, imag.shape)

    # -- lecture. L'asservissement qui régénère la porteuse n'est pas parfait,
    #    et son erreur se lit directement en teinte. C'est elle qui fait
    #    « respirer » la couleur d'une cassette NTSC fatiguée — le PAL et le
    #    SECAM l'ignorent, chacun pour ses raisons (chapitres 8 et 9).
    erreur = alea.normal(0.0, 0.25 * float(np.clip(params.usure, 0.0, 1.0)), lignes)
    lu = (reel + 1j * imag) * np.exp(1j * erreur)[:, None]

    # -- retour à la sous-porteuse couleur. Le facteur deux rétablit ce que la
    #    représentation analytique avait laissé dans les fréquences négatives.
    remontee = np.exp(+2j * np.pi * (norme.f_sc - f_sous) * t)[None, :]
    return 2.0 * np.real(lu * remontee)


# ---------------------------------------------------------------------------
# La mécanique
# ---------------------------------------------------------------------------

def _decalages_gigue(lignes, params, f_e, alea):
    """Erreur de base de temps : de combien chaque ligne commence trop tôt ou tard.

    C'est l'artefact le plus reconnaissable du VHS, et le plus difficile à
    confondre avec autre chose. La bande ne défile pas d'un mouvement parfait ;
    le début de chaque ligne se décale donc de quelques dixièmes de
    microseconde, et **les verticales ondulent**.

    Le décalage n'est pas tiré indépendamment ligne à ligne : il est LISSÉ
    verticalement. Un tirage indépendant donnerait un tremblement de haute
    fréquence — du bruit — alors qu'une mécanique a de l'inertie et produit une
    ondulation lente, qui se voit comme une déformation du bord de l'image et
    non comme un grésillement.
    """
    niveau = float(np.clip(params.gigue, 0.0, 1.0))
    if niveau <= 0.0:
        return np.zeros(lignes)

    brut = alea.normal(0.0, 1.0, lignes)
    lisse = ndimage.gaussian_filter1d(brut, sigma=2.5, mode="nearest")
    lisse /= max(float(np.std(lisse)), 1e-9)

    amplitude = 0.30e-6 * niveau * (0.4 + 0.6 * float(np.clip(params.usure, 0.0, 1.0)))

    # Le haut de l'image bouge bien plus que le reste : c'est le « drapeau »,
    # la signature la plus reconnaissable du format. Les deux têtes du tambour
    # se relaient juste avant la fin de la trame ; au début de la suivante,
    # l'asservissement n'est pas encore stabilisé et les premières lignes sont
    # franchement décalées. Le reste de l'image, lui, reste très calme — comme
    # l'était un magnétoscope correct.
    transitoire = 1.0 + 3.0 * np.exp(-np.arange(lisse.size) / 10.0)
    return lisse * transitoire * amplitude * f_e


def _decaler(x, decalages):
    """Décale chaque ligne horizontalement, d'une quantité qui lui est propre."""
    decalages = np.asarray(decalages, dtype=np.float64)
    if not np.any(np.abs(decalages) > 1e-6):
        return x
    colonnes = np.arange(x.shape[1], dtype=np.float64)
    sortie = np.empty_like(x)
    for i in range(x.shape[0]):
        sortie[i] = np.interp(
            colonnes + decalages[i % decalages.size], colonnes, x[i],
            left=x[i, 0], right=x[i, -1],
        )
    return sortie


def _abandons(signal, norme, params, alea):
    """Pertes de signal : l'oxyde manque, la tête ne lit rien.

    Le magnétoscope les comble avec la ligne précédente — c'est le rôle du
    *dropout compensator* — mais l'escamotage se voit : un segment de ligne
    répété, souvent souligné d'un trait clair là où le circuit bascule.
    """
    taux = float(np.clip(params.abandons, 0.0, 1.0))
    if taux <= 0.0:
        return signal

    lignes, n = signal.shape
    # Échelle quadratique, calée sur la réalité et non réglée à la main : une
    # perte toutes les deux secondes au réglage par défaut, trois par image
    # quand tout est poussé à fond. La spécification d'une bande VHS neuve est
    # de dix à vingt pertes par MINUTE.
    esperance = 3.0 * taux**2 * (0.2 + 0.8 * float(np.clip(params.usure, 0.0, 1.0)))
    combien = int(alea.poisson(max(esperance, 0.0)))
    if combien <= 0:
        return signal

    sortie = signal.copy()
    for _ in range(combien):
        ligne = int(alea.integers(1, lignes))
        debut = int(alea.integers(0, max(1, n - 20)))
        longueur = int(alea.integers(n // 60, n // 8))
        fin = min(n, debut + longueur)
        # Compensation par la ligne précédente, comme le fait le circuit.
        sortie[ligne, debut:fin] = signal[ligne - 1, debut:fin]
        # Le basculement lui-même laisse une marque brève.
        marque = min(fin, debut + max(2, longueur // 20))
        sortie[ligne, debut:marque] += 0.25
    return sortie


def _commutation(signal, norme, params, alea):
    """Commutation des têtes, en bas de l'image.

    Les deux têtes d'un tambour se relaient une fois par trame. Le relais a
    lieu quelques lignes avant la fin de l'image active, et il n'est pas
    instantané : ces lignes-là sont désynchronisées, franchement décalées et
    bruitées. C'est la bande de désordre que tout le monde a vue au bas d'une
    cassette — et que les téléviseurs masquaient en surbalayant.
    """
    lignes, n = signal.shape
    combien = 6
    sortie = signal.copy()
    for k in range(combien):
        ligne = lignes - 1 - k
        if ligne < 1:
            break
        # Décalage croissant à mesure qu'on approche du bas.
        force = (combien - k) / combien
        decalage = int(force * 0.06 * n)
        sortie[ligne] = np.roll(signal[ligne], decalage)
        sortie[ligne] += alea.normal(0.0, 0.05 * force, n)
    return sortie
