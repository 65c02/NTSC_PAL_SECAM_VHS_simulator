"""
Filtrage : limitation de bande, séparation Y/C, préaccentuations SECAM.

Tous les signaux manipulés ici sont des tableaux 2-D de forme
`(n_lignes, n_échantillons)` : une ligne de balayage par rangée. Le filtrage
horizontal (dans le temps, le long d'une ligne) s'applique sur l'axe 1 ;
le filtrage vertical (les filtres en peigne, la ligne à retard) s'applique
sur l'axe 0.

C'est cette distinction qui structure toute la télévision couleur : la bande
passante est une ressource **horizontale**, la mémoire de ligne une ressource
**verticale**, et chaque norme arbitre différemment entre les deux.
"""

from __future__ import annotations

import numpy as np
from scipy import fft, ndimage, signal

from .constantes import (
    SECAM_CLOCHE_A,
    SECAM_CLOCHE_B,
    SECAM_F0,
    SECAM_F1,
)

# ---------------------------------------------------------------------------
# Rééchantillonnage horizontal
# ---------------------------------------------------------------------------

def reechantillonner(lignes: np.ndarray, n_sortie: int) -> np.ndarray:
    """Rééchantillonne chaque ligne à `n_sortie` points.

    Sert deux fois dans la chaîne : à l'aller pour passer de la largeur en
    pixels de l'image au nombre d'échantillons imposé par la fréquence
    d'échantillonnage du composite (4·f_sc), au retour pour revenir à la
    largeur d'affichage.

    Interpolation cubique, avec préfiltrage anti-repliement lorsqu'on
    décime — sans quoi on introduirait un aliasing qui n'a rien à voir avec
    les artefacts que l'on cherche à simuler.
    """
    lignes = np.atleast_2d(np.asarray(lignes, dtype=np.float64))
    n_lignes, n_entree = lignes.shape
    if n_entree == n_sortie:
        return lignes.copy()

    if n_sortie < n_entree:
        lignes = passe_bas_normalise(lignes, 0.5 * n_sortie / n_entree)

    # Alignement sur les centres d'échantillon : le point i de la sortie
    # correspond au temps (i + 0,5)/n_sortie de la ligne.
    x = (np.arange(n_sortie) + 0.5) * (n_entree / n_sortie) - 0.5
    colonnes = np.broadcast_to(x, (n_lignes, n_sortie))
    rangees = np.broadcast_to(np.arange(n_lignes)[:, None], (n_lignes, n_sortie))
    return ndimage.map_coordinates(
        lignes, [rangees, colonnes], order=3, mode="nearest"
    )


def reechantillonner_vertical(lignes: np.ndarray, n_sortie: int) -> np.ndarray:
    """Change le nombre de lignes (525 ↔ 625, ou image source → lignes actives)."""
    lignes = np.asarray(lignes, dtype=np.float64)
    n_entree = lignes.shape[0]
    if n_entree == n_sortie:
        return lignes.copy()
    facteur = n_sortie / n_entree
    zoom = [facteur] + [1.0] * (lignes.ndim - 1)
    sortie = ndimage.zoom(lignes, zoom, order=3, mode="nearest", grid_mode=True)
    # ndimage.zoom peut se tromper d'un échantillon sur les ratios irrationnels.
    if sortie.shape[0] != n_sortie:
        sortie = sortie[:n_sortie] if sortie.shape[0] > n_sortie else np.concatenate(
            [sortie, np.repeat(sortie[-1:], n_sortie - sortie.shape[0], axis=0)]
        )
    return sortie


# ---------------------------------------------------------------------------
# Filtres à réponse impulsionnelle finie, horizontaux
# ---------------------------------------------------------------------------

ORDRE_PAR_DEFAUT = 4
"""Ordre des filtres de limitation de bande.

Pourquoi un Butterworth et non un filtre à réponse impulsionnelle finie très
raide ? Parce qu'un téléviseur ne contient pas de FIR : il contient des
réseaux LC — bobines et condensateurs — dont la réponse est celle d'un filtre
récursif d'ordre modeste. Un FIR à coupure abrupte produirait, sur une
mire de barres, un rebond de Gibbs spectaculaire qu'aucun poste n'a jamais
affiché. On simulerait alors un artefact inventé, ce qui est précisément ce
qu'on veut éviter.

Ordre 4 appliqué en aller-retour (`sosfiltfilt`) : pente effective de
48 dB/octave, phase rigoureusement nulle, transitoire court.
"""


def _sos_passe_bas(fc_normalisee: float, ordre: int) -> np.ndarray:
    return signal.butter(ordre, 2.0 * fc_normalisee, btype="lowpass", output="sos")


def _marge_de_stabilisation(largeur_relative: float, n: int) -> int:
    """Longueur de prolongement nécessaire pour qu'un filtre s'établisse.

    Point technique qui a son importance : la marge par défaut de
    `sosfiltfilt` vaut 3·(2·nombre de sections + 1), soit 15 échantillons pour
    un Butterworth d'ordre 4. C'est une valeur pensée pour des filtres larges.
    Or nos filtres sont **étroits** — 1,3 MHz sur 17,7 MHz d'échantillonnage,
    soit une bande relative de 0,073 — et leur réponse impulsionnelle s'étend
    sur plus d'une centaine d'échantillons.

    Avec 15 échantillons de marge, le filtre démarre froid : les cent
    premières colonnes de chaque ligne portent un transitoire. Sur une image
    blanche décodée en SECAM, cela se traduit par une bande de couleur franche
    le long du bord gauche — un artefact entièrement numérique, qui n'a aucun
    équivalent dans un téléviseur.

    On dimensionne donc la marge sur l'inverse de la bande relative.
    """
    largeur_relative = max(float(largeur_relative), 1e-5)
    return int(min(n - 1, max(24, round(8.0 / largeur_relative))))


def _appliquer(lignes: np.ndarray, sos: np.ndarray, largeur_relative: float) -> np.ndarray:
    """Applique un filtre en sections du second ordre, aller-retour, sur l'axe 1."""
    lignes = np.atleast_2d(np.asarray(lignes, dtype=np.float64))
    marge = _marge_de_stabilisation(largeur_relative, lignes.shape[1])
    return signal.sosfiltfilt(sos, lignes, axis=1, padlen=marge)


def passe_bas_normalise(
    lignes: np.ndarray, f_coupure_normalisee: float, ordre: int = ORDRE_PAR_DEFAUT
) -> np.ndarray:
    """Passe-bas, fréquence de coupure exprimée en fraction de f_échantillonnage."""
    fc = float(f_coupure_normalisee)
    if fc >= 0.4999:
        return np.atleast_2d(np.asarray(lignes, dtype=np.float64)).copy()
    fc = max(fc, 1e-5)
    return _appliquer(lignes, _sos_passe_bas(fc, ordre), fc)


def passe_bas(
    lignes: np.ndarray, f_coupure: float, f_ech: float, ordre: int = ORDRE_PAR_DEFAUT
) -> np.ndarray:
    """Passe-bas horizontal, coupure en hertz.

    C'est l'outil qui matérialise les bandes passantes normatives : 4,2 MHz
    pour la luma NTSC, 1,3 MHz pour U et V, 0,4 MHz pour Q. Chaque limitation
    de bande est une perte de résolution horizontale, et une seule chose
    compte : le rapport entre la coupure et la fréquence d'échantillonnage.
    """
    return passe_bas_normalise(lignes, f_coupure / f_ech, ordre)


def _bornes_normalisees(f_basse, f_haute, f_ech):
    nyquist = 0.5 * f_ech
    f1 = float(np.clip(f_basse / nyquist, 1e-4, 0.998))
    f2 = float(np.clip(f_haute / nyquist, f1 + 1e-3, 0.999))
    return f1, f2


def passe_bande(
    lignes: np.ndarray, f_basse: float, f_haute: float, f_ech: float,
    ordre: int = ORDRE_PAR_DEFAUT,
) -> np.ndarray:
    """Passe-bande horizontal, bornes en hertz. Sert à extraire la chrominance."""
    f1, f2 = _bornes_normalisees(f_basse, f_haute, f_ech)
    sos = signal.butter(ordre, [f1, f2], btype="bandpass", output="sos")
    # La durée d'établissement d'un passe-bande est fixée par sa largeur,
    # pas par sa fréquence centrale.
    return _appliquer(lignes, sos, 0.5 * (f2 - f1))


def coupe_bande(
    lignes: np.ndarray, f_basse: float, f_haute: float, f_ech: float,
    ordre: int = ORDRE_PAR_DEFAUT,
) -> np.ndarray:
    """Réjecteur de bande — le fameux « filtre notch » des téléviseurs bon marché.

    Placé autour de la sous-porteuse, il retire la chrominance du signal
    composite pour obtenir la luma. Le prix à payer est immédiat et visible :
    tout le détail de luminance situé dans la bande rejetée disparaît aussi.
    Une chemise à fines rayures perd sa texture — et, en prime, ce qu'il en
    reste ressort en couleurs dans le canal chroma (le *cross-color*).
    """
    f1, f2 = _bornes_normalisees(f_basse, f_haute, f_ech)
    sos = signal.butter(ordre, [f1, f2], btype="bandstop", output="sos")
    return _appliquer(lignes, sos, 0.5 * (f2 - f1))


# ---------------------------------------------------------------------------
# Filtres verticaux : peignes et lignes à retard
# ---------------------------------------------------------------------------

def _decaler_lignes(x: np.ndarray, decalage: int) -> np.ndarray:
    """Décale le tableau selon l'axe des lignes, en répliquant les bords.

    Un vrai récepteur n'a pas de ligne « précédente » sur la première ligne
    de l'image : il sort ce que contient sa mémoire, c'est-à-dire n'importe
    quoi. Répliquer le bord est la convention la moins bruyante.
    """
    if decalage == 0:
        return x
    if decalage > 0:   # on remonte : la ligne n reçoit la ligne n - decalage
        return np.concatenate([np.repeat(x[:1], decalage, axis=0), x[:-decalage]], axis=0)
    k = -decalage      # on descend : la ligne n reçoit la ligne n + k
    return np.concatenate([x[k:], np.repeat(x[-1:], k, axis=0)], axis=0)


def peigne_deux_lignes(composite: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Séparateur Y/C en peigne à deux lignes (NTSC).

    Fondement : en NTSC, la sous-porteuse tourne exactement de 180° d'une
    ligne à la suivante. La chrominance change donc de signe, tandis que la
    luminance, elle, reste presque identique entre deux lignes voisines.

        Y = (L[n] + L[n-1]) / 2      la chroma s'annule
        C = (L[n] - L[n-1]) / 2      la luma s'annule

    Cette identité est exacte partout sauf sur les transitions verticales,
    où l'hypothèse « la luma ne change pas d'une ligne à l'autre » s'écroule :
    la chroma résiduelle produit alors les points rampants (*dot crawl*) le
    long des contours horizontaux.
    """
    precedente = _decaler_lignes(composite, 1)
    return 0.5 * (composite + precedente), 0.5 * (composite - precedente)


def peigne_trois_lignes(composite: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Peigne à trois lignes, pondéré 1/4 – 1/2 – 1/4.

    En moyennant la ligne précédente et la suivante, on obtient un peigne
    symétrique : plus d'artefact de retard, et une réjection de chroma
    meilleure sur les images fixes. C'est ce que faisaient les téléviseurs
    haut de gamme des années 1980 dotés d'une ligne à retard numérique.
    """
    precedente = _decaler_lignes(composite, 1)
    suivante = _decaler_lignes(composite, -1)
    luma = 0.25 * precedente + 0.5 * composite + 0.25 * suivante
    return luma, composite - luma


def moyenne_ligne_a_retard(x: np.ndarray) -> np.ndarray:
    """Moyenne d'une ligne et de la précédente — la ligne à retard du PAL-D.

    C'est le cœur du PAL : en moyennant deux lignes dont la composante V a
    été inversée à l'émission, l'erreur de phase du canal se compense au
    lieu de se voir. On y perd la moitié de la résolution chroma verticale ;
    l'œil ne s'en aperçoit pas.
    """
    return 0.5 * (x + _decaler_lignes(x, 1))


# ---------------------------------------------------------------------------
# Filtrage dans le domaine fréquentiel (pour les réponses analytiques SECAM)
# ---------------------------------------------------------------------------

def prolonger(lignes: np.ndarray, marge: int, mode: str = "impair") -> np.ndarray:
    """Prolonge chaque ligne des deux côtés.

    * `impair` — symétrie par rapport au **point** extrême, et non à la droite
      verticale. Préserve la valeur *et* la pente à la jonction, là où une
      symétrie paire créerait un point anguleux que les filtres à fort gain
      haute fréquence transformeraient en explosion. À réserver aux signaux
      oscillants (une sous-porteuse modulée).
    * `repliquer` — maintien de la valeur extrême. Sans dépassement possible,
      donc sans risque de sortir de l'excursion autorisée. C'est le bon choix
      pour un signal de différence de couleur, qu'on va ensuite écrêter.
    """
    if marge <= 0:
        return np.atleast_2d(np.asarray(lignes, dtype=np.float64))
    lignes = np.atleast_2d(np.asarray(lignes, dtype=np.float64))
    marge = min(marge, lignes.shape[1] - 1)
    if mode == "repliquer":
        gauche = np.repeat(lignes[:, :1], marge, axis=1)
        droite = np.repeat(lignes[:, -1:], marge, axis=1)
    elif mode == "impair":
        gauche = 2.0 * lignes[:, :1] - lignes[:, marge:0:-1]
        droite = 2.0 * lignes[:, -1:] - lignes[:, -2 : -marge - 2 : -1]
    else:
        raise ValueError(f"mode de prolongement inconnu : {mode!r}")
    return np.concatenate([gauche, lignes, droite], axis=1)


def recadrer(lignes: np.ndarray, marge: int, largeur: int) -> np.ndarray:
    """Inverse de `prolonger` : ne garde que la partie active."""
    if marge <= 0:
        return lignes
    marge = min(marge, (lignes.shape[1] - largeur) // 2)
    return lignes[:, marge : marge + largeur]


def appliquer_reponse(lignes: np.ndarray, reponse, f_ech: float) -> np.ndarray:
    """Applique une réponse en fréquence complexe H(f) ligne par ligne.

    `reponse` est une fonction vectorisée f (Hz, ≥ 0) → H complexe.
    Les préaccentuations SECAM sont définies analytiquement par leur réponse
    en fréquence ; les appliquer directement par transformée de Fourier est
    plus fidèle que de les approcher par un filtre numérique équivalent.

    Les lignes sont prolongées avant la transformée pour éviter le repliement
    circulaire. Le **type** de prolongement compte énormément ici : une
    symétrie paire (miroir) crée un point anguleux à la jonction, et le filtre
    cloche, qui amplifie les hautes fréquences d'un facteur 12, transforme ce
    point anguleux en une explosion de plusieurs centaines de pour cent sur
    les premiers échantillons de chaque ligne.

    On utilise donc un prolongement **impair** — symétrie par rapport au point
    (x₀, y₀) plutôt que par rapport à la droite verticale — qui préserve à la
    fois la valeur et la dérivée à la jonction. C'est le même choix que fait
    `scipy.signal.filtfilt` avec son `padtype="odd"`, et pour la même raison.
    """
    lignes = np.atleast_2d(np.asarray(lignes, dtype=np.float64))
    n = lignes.shape[1]
    marge = min(n - 1, 256)

    gauche = 2.0 * lignes[:, :1] - lignes[:, marge:0:-1]
    droite = 2.0 * lignes[:, -1:] - lignes[:, -2 : -marge - 2 : -1]
    etendu = np.concatenate([gauche, lignes, droite], axis=1)

    m = fft.next_fast_len(etendu.shape[1])
    freqs = fft.rfftfreq(m, d=1.0 / f_ech)
    h = np.asarray(reponse(freqs), dtype=np.complex128)
    filtre = fft.irfft(fft.rfft(etendu, n=m, axis=1) * h, n=m, axis=1)
    return filtre[:, marge : marge + n]


def reponse_preaccentuation_bf(f: np.ndarray) -> np.ndarray:
    """Préaccentuation basse fréquence SECAM : A(f) = (1 + j f/f1)/(1 + j f/3f1).

    Elle relève les hautes fréquences du signal de différence de couleur
    **avant** la modulation, dans un rapport 3 au maximum (≈ 9,5 dB). Au
    décodage, la désaccentuation inverse rabaisse ces fréquences — et avec
    elles le bruit que le canal y a ajouté. C'est le même principe que le
    Dolby B sur une cassette audio.
    """
    f = np.asarray(f, dtype=np.float64)
    return (1.0 + 1j * f / SECAM_F1) / (1.0 + 1j * f / (3.0 * SECAM_F1))


def reponse_desaccentuation_bf(f: np.ndarray) -> np.ndarray:
    return 1.0 / reponse_preaccentuation_bf(f)


BANDE_CLOCHE = (3.2e6, 5.5e6)
TRANSITION_CLOCHE = 0.45e6
"""Bande dans laquelle le filtre cloche est réellement actif.

La formule normative de la cloche, G(F) = M₀(1+16jF)/(1+1,26jF), tend vers
12,7·M₀ quand f s'éloigne de f₀ — aussi bien vers zéro que vers l'infini.
Prise au pied de la lettre, elle amplifierait donc de 22 dB tout ce qui n'est
pas de la chrominance, y compris le continu.

Cela n'a évidemment aucun sens physique : dans un codeur SECAM, la cloche est
insérée dans la **voie chrominance**, qui est déjà bornée par un passe-bande
autour de 4,3 MHz. Elle ne voit jamais ces fréquences. On borne donc la
réponse à la bande réellement occupée, avec des flancs adoucis — sans quoi la
réponse impulsionnelle serait infiniment longue et le moindre effet de bord
se propagerait dans toute la ligne.
"""


def _fenetre_bande(f: np.ndarray, bornes=BANDE_CLOCHE, transition=TRANSITION_CLOCHE):
    """Gabarit passe-bande à flancs en cosinus surélevé, entre 0 et 1."""
    f = np.asarray(f, dtype=np.float64)
    basse, haute = bornes
    montee = np.clip((f - (basse - transition)) / transition, 0.0, 1.0)
    descente = np.clip(((haute + transition) - f) / transition, 0.0, 1.0)
    gabarit = np.minimum(montee, descente)
    return 0.5 - 0.5 * np.cos(np.pi * gabarit)


def reponse_cloche(f: np.ndarray, m0: float = 1.0) -> np.ndarray:
    """Préaccentuation haute fréquence SECAM, dite « filtre cloche ».

        G(F) = M0 (1 + j·16·F) / (1 + j·1,26·F),   F = f/f0 - f0/f

    avec f0 = 4,286 MHz, à mi-chemin entre les deux sous-porteuses.

    La courbe a la forme d'une cloche **inversée** : minimum à f0, remontée
    de part et d'autre. Conséquence : plus la couleur est proche du gris,
    plus la fréquence instantanée est proche du repos, et **plus la
    sous-porteuse est atténuée**. Sans ce filtre, un mur blanc afficherait un
    motif de sous-porteuse parfaitement visible, puisqu'en SECAM la porteuse
    est émise en permanence, saturée ou non.

    C'est l'astuce qui rend SECAM regardable — et c'est aussi la raison pour
    laquelle un signal SECAM ne peut pas être mélangé ou fondu : l'amplitude
    ne veut rien dire, seule la fréquence porte l'information.
    """
    f = np.asarray(f, dtype=np.float64)
    sans_zero = np.where(f <= 0.0, 1.0, f)
    grand_f = sans_zero / SECAM_F0 - SECAM_F0 / sans_zero
    h = m0 * (1.0 + 1j * SECAM_CLOCHE_A * grand_f) / (1.0 + 1j * SECAM_CLOCHE_B * grand_f)
    return np.where(f <= 0.0, 0.0, h * _fenetre_bande(f))


def reponse_anti_cloche(f: np.ndarray, m0: float = 1.0) -> np.ndarray:
    """Filtre « anti-cloche » du récepteur : l'inverse de la cloche dans sa bande.

    On inverse la formule **brute**, sans réappliquer le gabarit de bande.
    Deux raisons : d'une part le gabarit ne doit être appliqué qu'une seule
    fois dans la chaîne — le réappliquer au retour attenuerait deux fois les
    flancs et déformerait la modulation de fréquence, ce qui ferait
    réapparaître de la couleur sur les gris ; d'autre part 1/G reste borné
    partout (entre 1/12,7 et 1), ce qui en fait un filtre inoffensif.
    """
    f = np.asarray(f, dtype=np.float64)
    sans_zero = np.where(f <= 0.0, 1.0, f)
    grand_f = sans_zero / SECAM_F0 - SECAM_F0 / sans_zero
    brut = m0 * (1.0 + 1j * SECAM_CLOCHE_A * grand_f) / (
        1.0 + 1j * SECAM_CLOCHE_B * grand_f
    )
    return np.where(f <= 0.0, 0.0, 1.0 / brut)


def gain_cloche(f: np.ndarray, m0: float = 1.0) -> np.ndarray:
    """Module de la réponse cloche — utile pour pondérer une FM en amplitude."""
    return np.abs(reponse_cloche(f, m0))
