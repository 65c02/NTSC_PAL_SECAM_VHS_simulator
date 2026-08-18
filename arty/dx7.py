"""
Une pile d'opérateurs à modulation de fréquence, dans l'esprit du DX7.

LE PRINCIPE, EN UNE LIGNE
-------------------------

Un opérateur est une sinusoïde dont la phase est modulée par la sortie d'un
autre :

    out_i(t) = A_i(t) · sin( 2π f_i t + φ_i + Σ_j M_ij · out_j(t) )

C'est tout. La richesse vient de l'agencement : qui module qui, dans quel
rapport de fréquence, et avec quelle enveloppe. Six opérateurs suffisent à faire
une cloche, un cuivre ou un piano électrique — et, ici, une géométrie.

POURQUOI LA MODULATION DE FRÉQUENCE PLUTÔT QU'UNE SOMME DE SINUS
----------------------------------------------------------------

Parce que le nombre d'harmoniques y est **réglable d'un seul bouton**. Une
sinusoïde de fréquence $f_p$ modulée en phase par une sinusoïde de fréquence
$f_m$ et d'indice $β$ contient les raies $f_p ± k f_m$, dont l'amplitude est la
fonction de Bessel $J_k(β)$ : au-delà de $k = β + 1$, elles s'effondrent. Monter
l'indice, c'est donc ouvrir l'éventail des harmoniques — et, sur l'image,
passer d'une barre franche à une texture fine.

CE QUI EST DU DX7, ET CE QUI NE L'EST PAS
------------------------------------------

Sont repris : six opérateurs, les rapports de fréquence entiers ou fractionnaires,
le mode à fréquence fixe, les enveloppes à quatre segments, et la rétroaction
d'un opérateur sur lui-même.

**N'est pas repris : la table des trente-deux algorithmes.** On lui préfère une
matrice de modulation 6 × 6 quelconque, qui les contient tous et bien d'autres.
Les agencements proposés dans `ALGORITHMES` sont donc nommés d'après ce qu'ils
font, et non d'après un numéro de la façade du DX7 — prétendre reproduire la
table exacte demanderait de la vérifier, et elle ne l'a pas été.

Ne sont pas repris non plus : la quantification à douze bits des tables de
sinus, le décalage de l'enveloppe en échelle logarithmique, et le retard d'un
échantillon de la boucle de rétroaction. Ce dernier point est remplacé par une
itération de point fixe, ce qui donne le même spectre à un déphasage près.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

N_OPERATEURS = 6
ITERATIONS_RETROACTION = 4
"""Passes de l'itération de point fixe qui remplace le retard d'un échantillon.

Quatre suffisent : au-delà, la sortie ne bouge plus que de 10⁻⁴ pour les indices
de rétroaction que le DX7 autorise."""


# ---------------------------------------------------------------------------
# Enveloppes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Enveloppe:
    """Enveloppe à quatre segments, comme celle du DX7.

    Le DX7 raisonne en *rates* et en *levels* : quatre paliers, et quatre
    vitesses pour aller de l'un à l'autre. On garde la forme, mais on exprime
    les vitesses en **durées**, ce qui est plus parlant quand l'axe du temps est
    la hauteur de l'image.

    Car c'est bien ce qui se passe ici : une trame dure vingt millisecondes en
    625 lignes, et l'enveloppe se lit donc **du haut vers le bas de l'image**.
    Une attaque de deux millisecondes, c'est le dixième supérieur de la trame.
    """

    niveaux: tuple[float, float, float, float] = (1.0, 0.8, 0.7, 0.0)
    durees: tuple[float, float, float, float] = (0.002, 0.004, 0.010, 0.004)

    depart: float = 0.0
    """Niveau AVANT le premier segment.

    Nul comme sur un DX7, où l'enveloppe part du silence. Mais une enveloppe
    « plate » doit valoir un partout, y compris au premier échantillon : sans ce
    champ, elle rampait de zéro à un sur le haut de l'image, et les motifs
    censés être immobiles ne l'étaient pas. Le test des barres verticales l'a
    trouvé avant qu'on ne le voie."""

    @staticmethod
    def plate() -> "Enveloppe":
        """Enveloppe constante — l'opérateur sonne pareil de haut en bas."""
        return Enveloppe(
            (1.0, 1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 0.0), depart=1.0
        )

    def evaluer(self, temps: np.ndarray) -> np.ndarray:
        """Amplitude de l'enveloppe aux instants donnés.

        Segments linéaires enchaînés, en partant de zéro. Après le dernier, on
        tient le dernier niveau : une trame plus longue que l'enveloppe ne
        redéclenche rien.
        """
        temps = np.asarray(temps, dtype=np.float64)
        sortie = np.full(temps.shape, self.niveaux[-1], dtype=np.float64)

        debut = 0.0
        depart = self.depart
        for niveau, duree in zip(self.niveaux, self.durees):
            duree = max(float(duree), 1e-9)
            fin = debut + duree
            dedans = (temps >= debut) & (temps < fin)
            if dedans.any():
                avance = (temps[dedans] - debut) / duree
                sortie[dedans] = depart + (niveau - depart) * avance
            debut, depart = fin, niveau
        sortie[temps < 0.0] = 0.0
        return sortie


# ---------------------------------------------------------------------------
# Opérateurs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Operateur:
    """Une sinusoïde, sa fréquence, son enveloppe, sa rétroaction."""

    rapport: float = 1.0
    """Multiple de la fondamentale. Le DX7 va de 0,50 à 31,00 ; les valeurs
    entières donnent un son harmonique, les autres une cloche ou un métal."""

    fixe: float = 0.0
    """Si non nul, fréquence **fixe** en hertz, qui ignore la fondamentale.
    C'est le mode que le DX7 réserve aux bruits de souffle et aux attaques."""

    niveau: float = 1.0
    """Amplitude. Sur un modulateur, c'est l'indice de modulation β — donc le
    nombre d'harmoniques ; sur une porteuse, c'est le volume."""

    detune: float = 0.0
    """Désaccord fin, en hertz. Deux opérateurs identiques désaccordés de
    quelques hertz battent — et sur l'image, le battement devient un lent
    glissement du motif d'une ligne à l'autre."""

    phase: float = 0.0
    """Phase initiale, en tours."""

    retroaction: float = 0.0
    """Auto-modulation. Portée au maximum, elle transforme la sinusoïde en dent
    de scie, puis en bruit : c'est ainsi que le DX7 fabrique ses percussions."""

    enveloppe: Enveloppe = field(default_factory=Enveloppe.plate)

    def frequence(self, fondamentale: float) -> float:
        return (self.fixe if self.fixe > 0.0 else self.rapport * fondamentale) + self.detune


# ---------------------------------------------------------------------------
# Agencements
# ---------------------------------------------------------------------------

def _matrice(paires) -> np.ndarray:
    """Matrice de modulation : `paires` liste des (modulé, modulateur)."""
    m = np.zeros((N_OPERATEURS, N_OPERATEURS))
    for cible, source in paires:
        m[cible, source] = 1.0
    return m


@dataclass(frozen=True)
class Algorithme:
    """Un agencement : qui module qui, et qui sort."""

    code: str
    nom: str
    matrice: np.ndarray
    porteuses: tuple[bool, ...]
    caractere: str = ""

    def rangs(self) -> list[int]:
        """Ordre d'évaluation : un opérateur après ceux qui le modulent.

        Tri topologique, la diagonale exclue — la rétroaction d'un opérateur sur
        lui-même n'impose pas d'ordre, elle se résout par itération.
        """
        restants = set(range(N_OPERATEURS))
        ordre: list[int] = []
        while restants:
            libres = [
                i for i in restants
                if not any(self.matrice[i, j] and j in restants and j != i
                           for j in range(N_OPERATEURS))
            ]
            if not libres:            # boucle entre opérateurs : on tranche
                libres = [min(restants)]
            ordre.extend(sorted(libres))
            restants -= set(libres)
        return ordre


ALGORITHMES: dict[str, Algorithme] = {
    a.code: a
    for a in (
        Algorithme(
            "additif", "Additif — six porteuses en parallèle",
            _matrice([]), (True,) * 6,
            "Aucune modulation : une simple somme de six sinusoïdes. Le spectre "
            "est exactement ce qu'on y met, et l'image montre la superposition "
            "de six trames de barres. C'est le cas de référence — celui où l'on "
            "sait à l'avance ce qu'on va voir.",
        ),
        Algorithme(
            "chaine", "Chaîne — 6 module 5, qui module 4…",
            _matrice([(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]),
            (True, False, False, False, False, False),
            "Une seule porteuse, modulée par une cascade de cinq. Les indices se "
            "composent, et le spectre s'ouvre très vite : c'est l'agencement qui "
            "donne le plus de texture pour le moins de réglages.",
        ),
        Algorithme(
            "deux-piles", "Deux piles — deux porteuses de trois",
            _matrice([(0, 1), (1, 2), (3, 4), (4, 5)]),
            (True, False, False, True, False, False),
            "Deux voix indépendantes qui s'additionnent. En donnant à chacune une "
            "fondamentale voisine, on obtient deux motifs qui glissent l'un sur "
            "l'autre — un moiré, au sens propre.",
        ),
        Algorithme(
            "eventail", "Éventail — un modulateur pour trois porteuses",
            _matrice([(0, 3), (1, 3), (2, 3)]),
            (True, True, True, False, False, False),
            "Un seul modulateur imprime sa signature sur trois porteuses de "
            "rapports différents. Les trois motifs partagent la même texture, ce "
            "qui donne une image étrangement cohérente.",
        ),
        Algorithme(
            "cloche", "Cloche — deux paires, rapports non entiers",
            _matrice([(0, 1), (2, 3)]),
            (True, False, True, False, False, False),
            "Deux paires porteuse/modulateur. Avec des rapports non entiers, le "
            "spectre devient inharmonique : sur l'image, les barres cessent d'être "
            "régulières et le motif ne se referme plus sur lui-même.",
        ),
    )
}


def obtenir_algorithme(code: str) -> Algorithme:
    try:
        return ALGORITHMES[code]
    except KeyError:
        connus = ", ".join(ALGORITHMES)
        raise KeyError(
            f"algorithme inconnu : {code!r}. Connus : {connus}"
        ) from None


# ---------------------------------------------------------------------------
# La voix
# ---------------------------------------------------------------------------

@dataclass
class Voix:
    """Six opérateurs, un agencement, une fondamentale."""

    fondamentale: float = 15_625.0
    """Fréquence de base, en hertz.

    La valeur par défaut n'est pas prise au hasard : c'est la fréquence ligne du
    625 lignes. Un opérateur de rapport entier tombe alors sur un multiple exact
    de la fréquence ligne, et son motif est **immobile d'une ligne à l'autre** —
    des barres verticales, franches. Décalez la fondamentale d'un demi-hertz et
    les barres se mettent à ramper."""

    algorithme: str = "chaine"
    operateurs: tuple[Operateur, ...] = field(
        default_factory=lambda: tuple(Operateur() for _ in range(N_OPERATEURS))
    )
    index: float = 1.0
    """Facteur global sur toute la matrice de modulation. C'est le bouton qui
    ouvre ou referme l'éventail des harmoniques."""

    def avec_operateur(self, rang: int, **changements) -> "Voix":
        ops = list(self.operateurs)
        ops[rang] = replace(ops[rang], **changements)
        return replace(self, operateurs=tuple(ops))

    def rendre(self, temps: np.ndarray) -> np.ndarray:
        """Sortie de la voix aux instants donnés, dans [−1, +1] environ.

        Les opérateurs sont évalués dans l'ordre topologique : un opérateur après
        ceux qui le modulent. La rétroaction, elle, se résout par itération de
        point fixe — le DX7 emploie un retard d'un échantillon, ce qui donne le
        même spectre à un déphasage près, mais imposerait ici une boucle
        séquentielle sur un demi-million de points.
        """
        temps = np.asarray(temps, dtype=np.float64)
        algo = obtenir_algorithme(self.algorithme)

        sorties = [np.zeros(temps.shape) for _ in range(N_OPERATEURS)]
        amplitudes = [
            op.niveau * op.enveloppe.evaluer(temps) for op in self.operateurs
        ]

        for rang in algo.rangs():
            op = self.operateurs[rang]
            omega = 2.0 * np.pi * op.frequence(self.fondamentale)
            base = omega * temps + 2.0 * np.pi * op.phase

            entree = np.zeros(temps.shape)
            for source in range(N_OPERATEURS):
                poids = algo.matrice[rang, source] * self.index
                if poids and source != rang:
                    entree = entree + poids * sorties[source]

            sortie = amplitudes[rang] * np.sin(base + entree)
            if op.retroaction > 0.0:
                for _ in range(ITERATIONS_RETROACTION):
                    sortie = amplitudes[rang] * np.sin(
                        base + entree + op.retroaction * sortie
                    )
            sorties[rang] = sortie

        somme = np.zeros(temps.shape)
        actives = 0
        for rang, porteuse in enumerate(algo.porteuses):
            if porteuse:
                somme = somme + sorties[rang]
                actives += 1
        return somme / max(actives, 1)
