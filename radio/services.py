"""
Les services radio simulés, et leurs constantes.

Même rôle que `tvcolor.constantes.NORMES` : une seule table, dont l'interface,
les tests et la documentation tirent tous leurs chiffres. Une valeur corrigée
ici se propage partout, et il n'y a jamais deux vérités.

CE QUI EST RÉGLEMENTAIRE ET CE QUI EST D'USAGE
----------------------------------------------

La distinction est faite service par service dans les docstrings, et elle
compte. Sont **réglementaires**, c'est-à-dire fixés par un texte :

- les bandes de fréquences et l'espacement des canaux ;
- l'excursion maximale en modulation de fréquence ;
- la puissance maximale ;
- le type de modulation.

Sont **d'usage** — mesurés sur du matériel, ou simplement la pratique
courante — la bande audio réelle des postes, le taux de compression des
modulateurs, la constante de temps de préaccentuation des services mobiles, et
la réponse du haut-parleur. Ce sont eux qui font qu'un talkie-walkie *sonne*
comme un talkie-walkie, et ils sont donc réglables.

POURQUOI L'AÉRONAUTIQUE EST EN AM
---------------------------------

C'est la question que tout le monde pose, et la réponse est une décision de
sécurité, pas un archaïsme. En modulation de fréquence, deux stations qui
émettent en même temps produisent l'**effet de capture** : la plus forte efface
complètement l'autre, et personne ne sait qu'il y a eu collision. En modulation
d'amplitude, les deux porteuses battent l'une contre l'autre et l'on entend un
sifflement caractéristique — le contrôleur *sait* que deux avions ont parlé
ensemble et redemande. Ce sifflement, le simulateur le produit par le calcul
(cf. `radio.canal.co_canal`) et non par un effet ajouté.
"""

from __future__ import annotations

from dataclasses import dataclass, field

F_AUDIO = 48_000
"""Fréquence d'échantillonnage de la chaîne audio, en hertz.

Quarante-huit kilohertz : de quoi porter les 15 kHz de la radiodiffusion FM
avec la marge qu'il faut pour les filtres, et un multiple commode de toutes les
fréquences de travail du module."""


@dataclass(frozen=True)
class HautParleur:
    """Réponse du transducteur, qui fait la moitié du caractère d'un poste.

    Un talkie-walkie ne sonne pas comme un talkie-walkie à cause de sa
    modulation — un fichier passe-bande à 300–3000 Hz n'y ressemble pas — mais à
    cause du petit transducteur de trente-six millimètres monté dans un boîtier
    plastique fermé. Il ne descend pas, il résonne, et il s'éteint vite.
    """

    coupure_basse: float
    """Fréquence de coupure du passe-haut acoustique, en hertz. C'est le volume
    d'air derrière la membrane qui la fixe : plus la boîte est petite, plus elle
    remonte."""

    coupure_haute: float
    """Où la membrane cesse de suivre."""

    resonance: float
    """Fréquence de la résonance principale, en hertz."""

    pointe_db: float
    """Hauteur de cette résonance, en décibels. C'est elle qui donne le timbre
    nasillard, et c'est le paramètre le plus audible de toute la table."""

    nom: str = ""


HP_TALKIE = HautParleur(450.0, 4_000.0, 1_100.0, 9.0, "transducteur 36 mm en boîtier")
HP_POSTE_MOBILE = HautParleur(300.0, 5_000.0, 800.0, 6.0, "haut-parleur 66 mm de tableau de bord")
HP_CASQUE_AVIATION = HautParleur(280.0, 4_500.0, 900.0, 4.0, "casque aviation, écouteur fermé")
HP_POSTE_A_LAMPES = HautParleur(120.0, 4_500.0, 300.0, 5.0, "haut-parleur 130 mm en coffret bois")
HP_TUNER = HautParleur(30.0, 20_000.0, 0.0, 0.0, "sortie de ligne, aucun transducteur")


@dataclass(frozen=True)
class Service:
    """Un service radio : sa modulation, son canal, et le poste qui le reçoit."""

    code: str
    nom: str
    famille: str
    """« radiodiffusion » ou « radiocommunication »."""

    modulation: str
    """« AM », « FM » ou « BLU »."""

    bande_mhz: tuple[float, float]
    """Bande de fréquences allouée, en mégahertz. Réglementaire."""

    espacement: float
    """Espacement des canaux, en hertz. Réglementaire."""

    largeur_recepteur: float
    """Bande passante du filtre de fréquence intermédiaire du récepteur, en
    hertz. C'est elle qui décide de ce que le poste laisse entrer — bruit
    compris — et non l'espacement des canaux."""

    audio_basse: float
    audio_haute: float
    """Bande audio du modulateur, en hertz."""

    excursion: float = 0.0
    """Excursion crête en modulation de fréquence, en hertz. Réglementaire."""

    indice: float = 0.85
    """Taux de modulation en amplitude, de 0 à 1. Au-delà de 1, le détecteur
    d'enveloppe décroche et la distorsion explose — ce que le simulateur montre
    plutôt que de l'interdire."""

    tau_accentuation: float = 0.0
    """Constante de temps de préaccentuation, en secondes. 50 µs en
    radiodiffusion FM européenne, 750 µs dans les services mobiles."""

    puissance: float = 1.0
    """Puissance d'émission typique, en watts. Sert à situer la portée, et à
    proposer un rapport porteuse/bruit par défaut."""

    compression_db: float = 0.0
    """Compression du modulateur, en décibels. Un émetteur de radiodiffusion en
    met peu ; un poste de communication en met beaucoup, parce que
    l'intelligibilité prime sur tout le reste."""

    niveau_modulation: float = 0.9
    """Niveau nominal à l'entrée du modulateur, de 0 à 1.

    C'est le potentiomètre d'entrée que tout émetteur possède, et il compte
    d'autant plus que la préaccentuation est forte : à 750 µs, un kilohertz
    ressort **treize décibels et demi plus haut** qu'il n'est entré. Régler
    l'entrée comme en radiodiffusion enverrait le limiteur dans ses butées à
    chaque syllabe.

    Mesuré, sur un ton à 1 kHz en PMR446 et canal parfait : 23 dB de rapport
    signal/bruit à niveau 0,70 — c'est de la distorsion pure — contre 48 dB à
    0,15. Le simulateur ne l'interdit pas : monter ce réglage fait entendre la
    surmodulation, qui est le son ordinaire d'une CB."""

    gain_audio: float = 1.0
    """Gain de l'amplificateur audio du récepteur.

    Purement cosmétique, et assumé comme tel : il n'existe que pour que les huit
    services sortent à peu près au même niveau, faute de quoi il faudrait
    retoucher le volume à chaque changement. Un poste réel a un bouton de
    volume, et c'est celui-là qu'on tourne."""

    haut_parleur: HautParleur = HP_TALKIE

    cn_defaut: float = 30.0
    """Rapport porteuse/bruit proposé par défaut, en décibels."""

    caractere: str = ""
    """Ce qui distingue ce service à l'oreille, en une phrase."""

    # Champs dérivés
    largeur_carson: float = field(init=False)
    facteur_travail: int = field(init=False)
    f_travail: int = field(init=False)

    def __post_init__(self) -> None:
        if self.modulation == "FM":
            # Règle de Carson : B = 2 (Δf + W). Ce n'est pas une approximation
            # commode mais la largeur qui contient 98 % de la puissance, et
            # c'est elle que les régulateurs ont retenue pour allouer les
            # canaux.
            largeur = 2.0 * (self.excursion + self.audio_haute)
        elif self.modulation == "BLU":
            largeur = self.audio_haute - self.audio_basse
        else:
            largeur = 2.0 * self.audio_haute
        object.__setattr__(self, "largeur_carson", largeur)

        # L'enveloppe complexe est échantillonnée à `f_travail` : la bande
        # qu'elle couvre vaut donc `f_travail` en entier, de -f/2 à +f/2, et
        # non la moitié comme pour un signal réel. On garde la moitié de cette
        # largeur en marge, pour que les flancs du filtre de fréquence
        # intermédiaire aient où s'établir sans replier.
        besoin = 1.5 * largeur
        facteur = 1
        while facteur * F_AUDIO < besoin:
            facteur += 1
        object.__setattr__(self, "facteur_travail", facteur)
        object.__setattr__(self, "f_travail", facteur * F_AUDIO)

    @property
    def indice_modulation_fm(self) -> float:
        """β = Δf / W, l'indice de modulation en fréquence."""
        if self.modulation != "FM" or self.audio_haute <= 0.0:
            return 0.0
        return self.excursion / self.audio_haute

    def gain_fm_db(self) -> float:
        """Gain de démodulation FM, en décibels : 10·log₁₀(3 β²(β+1)).

        C'est ce que la modulation de fréquence rend en rapport signal/bruit
        au-dessus du seuil, en échange de la largeur de bande qu'elle a prise.
        Nul en AM, où la démodulation ne gagne rien.
        """
        import numpy as np

        if self.modulation != "FM":
            return 0.0
        beta = self.indice_modulation_fm
        return float(10.0 * np.log10(3.0 * beta**2 * (beta + 1.0)))


SERVICES: dict[str, Service] = {
    s.code: s
    for s in (
        Service(
            code="am-om", nom="Radiodiffusion AM — ondes moyennes",
            famille="radiodiffusion", modulation="AM",
            bande_mhz=(0.5265, 1.6065), espacement=9_000.0,
            largeur_recepteur=8_000.0,
            audio_basse=60.0, audio_haute=4_500.0,
            indice=0.85, puissance=100_000.0, compression_db=6.0,
            niveau_modulation=0.90,
            gain_audio=0.90,
            haut_parleur=HP_POSTE_A_LAMPES, cn_defaut=26.0,
            caractere=(
                "Le poste à lampes du salon. Quatre kilohertz et demi de bande "
                "audio — les cymbales n'existent pas — un souffle permanent, et "
                "le sifflement de la station voisine à neuf kilohertz."
            ),
        ),
        Service(
            code="fm-mono", nom="Radiodiffusion FM — mono",
            famille="radiodiffusion", modulation="FM",
            bande_mhz=(87.5, 108.0), espacement=100_000.0,
            largeur_recepteur=180_000.0,
            audio_basse=20.0, audio_haute=15_000.0,
            excursion=75_000.0, tau_accentuation=50e-6,
            puissance=10_000.0, compression_db=4.0,
            niveau_modulation=0.70,
            gain_audio=1.16,
            haut_parleur=HP_TUNER, cn_defaut=40.0,
            caractere=(
                "Quinze kilohertz de bande, et un rapport signal/bruit que la "
                "modulation de fréquence paie en largeur de canal : dix-huit "
                "fois celle d'une station AM."
            ),
        ),
        Service(
            code="cb-am", nom="CB 27 MHz — AM",
            famille="radiocommunication", modulation="AM",
            bande_mhz=(26.965, 27.405), espacement=10_000.0,
            largeur_recepteur=8_000.0,
            audio_basse=300.0, audio_haute=3_000.0,
            indice=0.95, puissance=4.0, compression_db=12.0,
            niveau_modulation=0.95,
            gain_audio=0.85,
            haut_parleur=HP_POSTE_MOBILE, cn_defaut=18.0,
            caractere=(
                "Quatre watts, un micro à compression poussé au maximum, et une "
                "bande où tout le monde s'entend. La surmodulation y est la "
                "règle plutôt que l'exception."
            ),
        ),
        Service(
            code="cb-blu", nom="CB 27 MHz — bande latérale unique",
            famille="radiocommunication", modulation="BLU",
            bande_mhz=(26.965, 27.405), espacement=10_000.0,
            largeur_recepteur=2_700.0,
            audio_basse=300.0, audio_haute=3_000.0,
            puissance=12.0, compression_db=14.0,
            niveau_modulation=0.90,
            gain_audio=1.06,
            haut_parleur=HP_POSTE_MOBILE, cn_defaut=14.0,
            caractere=(
                "Ni porteuse ni bande latérale inutile : toute la puissance dans "
                "la parole, et douze watts crête au lieu de quatre. En échange, "
                "il faut accorder le poste au hertz près — sans quoi les voix "
                "prennent le timbre de Donald."
            ),
        ),
        Service(
            code="pmr446", nom="Talkie-walkie PMR446",
            famille="radiocommunication", modulation="FM",
            bande_mhz=(446.0, 446.2), espacement=12_500.0,
            largeur_recepteur=12_500.0,
            audio_basse=300.0, audio_haute=3_000.0,
            excursion=2_500.0, tau_accentuation=750e-6,
            puissance=0.5, compression_db=15.0,
            niveau_modulation=0.22,
            gain_audio=3.67,
            haut_parleur=HP_TALKIE, cn_defaut=22.0,
            caractere=(
                "Un demi-watt, un canal de douze kilohertz et demi, une "
                "excursion de deux kilohertz et demi. Le squelch coupe le souffle "
                "entre les phrases et le rend d'un coup à la retombée de la "
                "porteuse : c'est le petit « pschit » qu'on reconnaît entre mille."
            ),
        ),
        Service(
            code="marine-vhf", nom="VHF marine",
            famille="radiocommunication", modulation="FM",
            bande_mhz=(156.0, 162.025), espacement=25_000.0,
            largeur_recepteur=16_000.0,
            audio_basse=300.0, audio_haute=3_000.0,
            excursion=5_000.0, tau_accentuation=750e-6,
            puissance=25.0, compression_db=12.0,
            niveau_modulation=0.30,
            gain_audio=2.76,
            haut_parleur=HP_POSTE_MOBILE, cn_defaut=26.0,
            caractere=(
                "Le grand frère du talkie : deux fois l'excursion, deux fois le "
                "canal, vingt-cinq watts. Plus clair, plus posé, et sans le "
                "souffle du PMR446."
            ),
        ),
        Service(
            code="aero-vhf", nom="VHF aéronautique",
            famille="radiocommunication", modulation="AM",
            bande_mhz=(118.0, 136.975), espacement=25_000.0,
            largeur_recepteur=8_000.0,
            audio_basse=300.0, audio_haute=2_700.0,
            indice=0.85, puissance=10.0, compression_db=14.0,
            niveau_modulation=0.90,
            gain_audio=0.90,
            haut_parleur=HP_CASQUE_AVIATION, cn_defaut=24.0,
            caractere=(
                "En amplitude, et c'est délibéré : deux avions qui parlent "
                "ensemble battent l'un contre l'autre et sifflent, au lieu que "
                "le plus fort efface l'autre en silence. Le contrôleur SAIT "
                "qu'il y a eu collision."
            ),
        ),
    )
}


def obtenir_service(code: str) -> Service:
    """Retourne le service correspondant au code."""
    try:
        return SERVICES[code]
    except KeyError:
        connus = ", ".join(SERVICES)
        raise KeyError(f"service inconnu : {code!r}. Services connus : {connus}") from None
