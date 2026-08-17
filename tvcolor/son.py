"""
La voie son d'un téléviseur analogique, simulée porteuse comprise.

Le son ne voyage pas dans le signal vidéo. Il occupe sa propre porteuse,
quelques mégahertz plus haut dans le même canal, et c'est **le même bruit de
canal** qui frappe les deux. De là vient tout l'intérêt de le simuler : la
manière dont l'image et le son se dégradent ensemble — ou pas — est une des
signatures les plus reconnaissables de chaque système.

Le trajet, et rien de plus :

    audio (n'importe quel taux)
      └─ limitation à 15 kHz
         └─ préaccentuation 50 µs (Europe) ou 75 µs (Amérique)
            └─ limiteur d'excursion
               └─ MODULATION sur la porteuse son
                  · FM  : ±25 kHz en système M, ±50 kHz ailleurs
                  · AM  : système L seulement, taux 54 %
                  └─ CANAL : bruit blanc, de la même densité que celui de l'image
                     └─ filtre à fréquence intermédiaire (largeur de Carson)
                        └─ DÉMODULATION
                           · FM : discriminateur à quadrature
                           · AM : détecteur d'enveloppe
                           └─ désaccentuation
                              └─ limitation à 15 kHz
                                 └─ + ronflement intercarrier

Rien n'est peint. Le souffle, le seuil FM et ses claquements, la fragilité de
l'AM du système L, le ronflement de trame : tout tombe du calcul, exactement
comme les artefacts de l'image dans le reste de la bibliothèque.

**Le son de la télévision analogique est monophonique.** Les procédés stéréo
— NICAM, Zweiton — sont venus plus tard et ajoutent leurs propres porteuses ;
ils ne sont pas simulés. Une entrée stéréo est donc mélangée en mono, et c'est
une perte réelle, pas un raccourci d'implémentation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sig

from .constantes import Norme, VoieSon

# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------

MARGE_SPECTRALE = 4.0
"""Rapport entre la fréquence d'échantillonnage de travail et la largeur de
Carson de la porteuse.

Quatre, et pas deux. Shannon se contenterait de deux, mais la modulation de
fréquence produit des raies latérales **au-delà** de la largeur de Carson —
celle-ci n'en contient que 98 % de la puissance. Les replier dans la bande
utile fabriquerait une distorsion qui n'existe pas."""

EPAULE_PREACCENTUATION = 4.0
"""Position de l'épaule du réseau de préaccentuation, en multiples de la bande
audio.

Une préaccentuation idéale, en 1 + jωτ, monterait indéfiniment. Aucun réseau
réel ne le fait : une résistance en parallèle borne la remontée. On place donc
l'épaule à quatre fois la bande audio — 60 kHz pour 15 kHz — ce qui laisse la
courbe se confondre avec la théorie sur toute la bande utile (+13,4 dB à
15 kHz contre 13,7 pour l'idéale) tout en gardant un filtre stable.

Sans cette épaule, l'inverse numérique du réseau aurait un pôle exactement sur
le cercle unité, à Nyquist : la désaccentuation entrerait en résonance."""


@dataclass
class ParametresSon:
    """Ce que l'utilisateur règle sur la voie son."""

    actif: bool = True
    """À faux, l'audio traverse sans être touché. Utile pour comparer."""

    rapport_signal_bruit: float | None = None
    """Rapport signal/bruit **de l'image**, en décibels, ou None pour un canal
    parfait. C'est bien le réglage de l'image que l'on passe ici : les deux
    porteuses partagent le canal, et c'est tout l'intérêt de la chose. La
    conversion vers le rapport porteuse/bruit de la voie son est faite par
    `rapport_porteuse_bruit`, et elle est intégralement dérivée."""

    intercarrier: float = 0.0
    """Niveau du ronflement intercarrier, de 0 à 1."""

    niveau_video: float = 0.5
    """Niveau vidéo moyen, de 0 à 1. Le ronflement en dépend : c'est la
    modulation de la porteuse image qui le fabrique."""

    desaccord: float = 0.0
    """Désaccord de l'oscillateur local, en hertz."""

    gain_entree: float = 1.0
    """Gain appliqué avant modulation. Au-delà de 1, le limiteur écrête et la
    distorsion apparaît — comme sur un émetteur réellement surmodulé."""

    gain_sortie: float = 1.0
    """Gain de l'amplificateur du récepteur, en linéaire.

    Il s'applique **après** la démodulation, ce qui est sa place physique : le
    volume d'un téléviseur agit sur l'étage basse fréquence, pas sur ce qui
    arrive de l'antenne. Il amplifie donc le bruit autant que le signal, et ne
    rattrape aucune mauvaise réception — exactement comme le bouton d'un vrai
    poste.

    Deux raisons de vouloir le pousser, et aucune n'est un défaut de la
    simulation. La première est que beaucoup de fichiers sont gravés bas. La
    seconde tient à la norme elle-même : la porteuse ne transportait qu'une
    voie, et le mélange d'une source stéréo en monophonie coûte jusqu'à trois
    décibels — davantage encore quand les deux canaux sont en opposition."""


# ---------------------------------------------------------------------------
# Rapport porteuse/bruit
# ---------------------------------------------------------------------------

def largeur_carson(voie: VoieSon) -> float:
    """Largeur de bande occupée par la porteuse son, en hertz.

    Règle de Carson : B = 2 (Δf + W). En AM il n'y a pas d'excursion, et la
    largeur se réduit aux deux bandes latérales, soit 2 W.
    """
    return 2.0 * (voie.deviation + voie.bande_audio)


def rapport_porteuse_bruit(norme: Norme, rapport_image_db: float) -> float:
    """Rapport porteuse/bruit de la voie son, déduit de celui de l'image.

    Il n'y a **qu'un seul** bruit : celui du canal, de densité spectrale N₀.
    Ce que chaque voie en récolte ne dépend que de deux choses — la largeur de
    bande qu'elle occupe, et la puissance à laquelle elle est émise :

        C/N_son = S/B_image + 10 log₁₀(B_image / B_son) + niveau_porteuse

    Le premier terme est le réglage de l'image. Le deuxième est un **gain**, et
    un gain considérable : la voie son occupe 130 kHz là où l'image en occupe
    cinq millions, soit 16 dB de bruit en moins par simple étroitesse. Le
    troisième est une perte, la porteuse son étant émise 10 à 13 dB plus bas.

    Le solde est positif de deux à six décibels selon le système. Ajoutez-y le
    gain de démodulation de la FM — une vingtaine de décibels de plus — et l'on
    tient l'explication de ce que tout le monde a constaté sans se l'expliquer :
    **le son restait propre bien après que l'image eut commencé à neiger.**

    Le SECAM-L est l'exception, et c'est le seul système d'Europe occidentale
    à l'être : son démodulateur d'amplitude n'apporte aucun gain. Chez lui, le
    son se dégrade en même temps que l'image.
    """
    gain_bande = 10.0 * math.log10(norme.bande_y / largeur_carson(norme.son))
    return rapport_image_db + gain_bande + norme.son.niveau_porteuse_db


def gain_de_demodulation_db(voie: VoieSon) -> float:
    """Amélioration théorique apportée par la démodulation, en décibels.

    Pour la modulation de fréquence, avec β = Δf / W :

        G = 3 β² (β + 1)

    En PAL, β = 50/15 = 3,33 et G vaut 144, soit 21,6 dB. En NTSC, où
    l'excursion n'est que de ±25 kHz faute de place dans un canal de 6 MHz,
    β = 1,67 et G tombe à 22, soit 13,5 dB — huit décibels de moins, pour la
    seule raison que le canal américain était plus étroit.

    En AM, il n'y a rien à gagner : la valeur est zéro par définition.

    La fonction ne sert qu'à la documentation et aux mesures ; la simulation,
    elle, ne l'emploie jamais. Le gain qu'on observe dans la chaîne est celui
    que la démodulation produit réellement, pas celui que la formule annonce —
    et les deux se comparent dans les tests.
    """
    if voie.modulation != "FM":
        return 0.0
    beta = voie.deviation / voie.bande_audio
    return 10.0 * math.log10(3.0 * beta * beta * (beta + 1.0))


# ---------------------------------------------------------------------------
# Réseaux de préaccentuation
# ---------------------------------------------------------------------------

def reseaux_accentuation(tau: float, bande_audio: float, f_ech: float):
    """Couple (préaccentuation, désaccentuation), numériques et exactement inverses.

    L'analogique est un simple réseau du premier ordre, avec son épaule :

        H(s) = (1 + sτ) / (1 + sτ/K),   K = 2π · épaule · τ

    On le transpose en numérique par transformation bilinéaire. La
    désaccentuation est obtenue en **échangeant numérateur et dénominateur du
    résultat**, et non en transposant séparément l'inverse analogique : la
    bilinéaire étant une simple substitution appliquée aux deux à l'identique,
    l'échange donne l'inverse numérique *exact*. La chaîne aller-retour rend
    donc le signal au bit près quand le canal est parfait, ce qu'un test
    vérifie.
    """
    if tau <= 0.0:
        plat = (np.array([1.0]), np.array([1.0]))
        return plat, plat
    k = 2.0 * np.pi * EPAULE_PREACCENTUATION * bande_audio * tau
    b, a = sig.bilinear([tau, 1.0], [tau / k, 1.0], fs=f_ech)
    return (b, a), (a, b)


SEUIL_SATURATION = 0.8
"""Niveau à partir duquel l'étage de sortie commence à saturer."""


def saturer(x: np.ndarray, seuil: float = SEUIL_SATURATION) -> np.ndarray:
    """Écrêtage doux, à la manière d'un étage de sortie poussé dans ses butées.

    Un `clip` franc serait le plus simple et le pire : il fabrique des angles
    droits, donc un spectre d'harmoniques impaires qui s'entend comme une
    déchirure. Aucun amplificateur ne fait cela — un transistor arrive dans ses
    butées progressivement.

    On laisse donc la courbe strictement linéaire sous le seuil, puis on
    comprime le dépassement par une tangente hyperbolique. Le raccord est lisse
    en valeur ET en pente — la dérivée de tanh en zéro vaut un — et la sortie
    tend vers l'unité sans jamais la franchir.
    """
    module = np.abs(x)
    marge = 1.0 - seuil
    exces = np.maximum(module - seuil, 0.0)
    comprime = seuil + marge * np.tanh(exces / marge)
    return np.sign(x) * np.where(module > seuil, comprime, module)


# ---------------------------------------------------------------------------
# La chaîne, en flux
# ---------------------------------------------------------------------------

class ChaineSon:
    """Transmission d'un flux audio par la porteuse son d'une norme.

    La classe est **à état** : elle traite le son par blocs en conservant
    l'état de tous ses filtres, la phase du modulateur et celle du ronflement.
    C'est indispensable au lecteur vidéo — traiter chaque bloc indépendamment
    ferait claquer les jonctions à chaque paquet — et sans conséquence pour le
    banc de mesure, qui appelle `transmettre` une fois pour tout le fichier.
    """

    def __init__(self, norme: Norme, taux: int, parametres: ParametresSon | None = None):
        self.norme = norme
        self.taux = int(taux)
        self.parametres = parametres or ParametresSon()

        voie = norme.son
        self.voie = voie

        # Facteur de suréchantillonnage : la grille de travail doit contenir la
        # porteuse et ses bandes latérales sans repliement.
        besoin = MARGE_SPECTRALE * largeur_carson(voie)
        self.facteur = int(min(16, max(4, math.ceil(besoin / self.taux))))
        self.f_travail = self.taux * self.facteur

        self._construire_filtres()
        self._reinitialiser_etats()

    # -- construction ---------------------------------------------------

    def _construire_filtres(self) -> None:
        voie, fe = self.voie, self.f_travail

        # Interpolation et décimation. Le gabarit est le même dans les deux
        # sens — la moitié du taux audio — et le gain de `facteur` compense
        # l'énergie perdue par l'insertion des zéros.
        coupure = 0.45 * self.taux
        self._noyau_reech = sig.firwin(
            8 * self.facteur + 1, coupure, fs=fe
        ) * self.facteur

        self._sos_audio = sig.butter(
            6, min(voie.bande_audio, 0.45 * fe), btype="low", fs=fe, output="sos"
        )
        (self._pre, self._des) = reseaux_accentuation(
            voie.preaccentuation, voie.bande_audio, fe
        )

        # Filtre à fréquence intermédiaire. On travaille en bande de base
        # complexe : le filtre passe-bande centré sur la porteuse devient un
        # passe-bas de demi-largeur, appliqué séparément aux deux composantes.
        demi = min(0.5 * largeur_carson(voie), 0.45 * fe)
        self._sos_fi = sig.butter(4, demi, btype="low", fs=fe, output="sos")

    def _reinitialiser_etats(self) -> None:
        n = len(self._noyau_reech) - 1
        self._etat_interp = np.zeros(n)
        self._etat_decim = np.zeros(n)
        self._etat_audio_avant = np.zeros((self._sos_audio.shape[0], 2))
        self._etat_audio_apres = np.zeros((self._sos_audio.shape[0], 2))
        self._etat_pre = np.zeros(max(len(self._pre[0]), len(self._pre[1])) - 1)
        self._etat_des = np.zeros(max(len(self._des[0]), len(self._des[1])) - 1)
        self._etat_fi_re = np.zeros((self._sos_fi.shape[0], 2))
        self._etat_fi_im = np.zeros((self._sos_fi.shape[0], 2))
        self._phase = 0.0
        self._precedent = complex(1.0, 0.0)
        self._phase_ligne = 0.0
        self._phase_trame = 0.0
        self._alea = np.random.default_rng(20250817)

    def reinitialiser(self) -> None:
        """Vide les états. À appeler sur un déplacement dans le fichier."""
        self._reinitialiser_etats()

    # -- accès ----------------------------------------------------------

    @property
    def rapport_porteuse_bruit(self) -> float | None:
        p = self.parametres
        if p.rapport_signal_bruit is None:
            return None
        return rapport_porteuse_bruit(self.norme, p.rapport_signal_bruit)

    def description(self) -> str:
        voie = self.voie
        detail = (
            f"±{voie.deviation / 1e3:.0f} kHz"
            if voie.modulation == "FM"
            else f"taux {voie.taux_am:.0%}"
        )
        texte = (
            f"porteuse à +{voie.decalage / 1e6:.1f} MHz, {voie.modulation} {detail}, "
            f"travail à {self.f_travail / 1e3:.0f} kHz"
        )
        cn = self.rapport_porteuse_bruit
        if cn is not None:
            texte += f", C/N {cn:.1f} dB"
        return texte

    # -- traitement -----------------------------------------------------

    def traiter(self, bloc: np.ndarray) -> np.ndarray:
        """Transmet un bloc audio. Entrée (n,) ou (n, canaux), sortie (n,).

        La sortie est monophonique : c'est ce que transportait la porteuse.
        """
        entree = np.asarray(bloc, dtype=np.float64)
        if entree.ndim == 2:
            entree = entree.mean(axis=1)
        if entree.size == 0:
            return entree

        if not self.parametres.actif:
            # Le gain de sortie s'applique quand même : c'est le bouton de
            # volume du poste, il ne dépend pas de ce qui arrive avant lui.
            return self._amplifier(entree)

        haut = self._interpoler(entree * self.parametres.gain_entree)
        haut = self._filtrer_sos(haut, self._sos_audio, "_etat_audio_avant")
        haut = self._accentuer(haut, self._pre, "_etat_pre")

        # Limiteur. Tout émetteur en a un : sans lui, un dépassement se
        # traduirait par une excursion hors canal et brouillerait le voisin.
        haut = np.clip(haut, -1.0, 1.0)

        porteuse = self._moduler(haut)
        porteuse = self._bruiter(porteuse)
        porteuse = self._filtrer_fi(porteuse)
        haut = self._demoduler(porteuse)

        # Le ronflement entre ICI, à la sortie du démodulateur, et non sur le
        # son fini. La place n'est pas une commodité : c'est là qu'il entre
        # réellement, et il doit donc subir la désaccentuation et le filtre
        # audio comme le reste.
        #
        # Le mesurer a d'ailleurs révélé la faute. Ajouté après le filtre, le
        # train d'impulsions gardait toutes ses harmoniques — celles au-delà de
        # 24 kHz se repliaient dans la bande audible et fabriquaient un timbre
        # métallique qu'aucun téléviseur n'a produit. Mesuré sur un export :
        # 5 % de l'énergie au-dessus de 16 kHz, contre 0,01 % pour la source.
        if self.parametres.intercarrier > 0.0:
            haut = haut + self._ronflement(haut.size, self.f_travail)

        haut = self._accentuer(haut, self._des, "_etat_des")
        haut = self._filtrer_sos(haut, self._sos_audio, "_etat_audio_apres")
        sortie = self._decimer(haut)

        return self._amplifier(sortie)

    def _amplifier(self, x: np.ndarray) -> np.ndarray:
        gain = float(self.parametres.gain_sortie)
        return saturer(x * gain if gain != 1.0 else x).astype(np.float32)

    # -- étages ---------------------------------------------------------

    def _interpoler(self, x: np.ndarray) -> np.ndarray:
        etendu = np.zeros(x.size * self.facteur)
        etendu[:: self.facteur] = x
        sortie, self._etat_interp = sig.lfilter(
            self._noyau_reech, [1.0], etendu, zi=self._etat_interp
        )
        return sortie

    def _decimer(self, x: np.ndarray) -> np.ndarray:
        filtre, self._etat_decim = sig.lfilter(
            self._noyau_reech / self.facteur, [1.0], x, zi=self._etat_decim
        )
        return filtre[:: self.facteur]

    def _filtrer_sos(self, x, sos, nom_etat):
        etat = getattr(self, nom_etat)
        sortie, etat = sig.sosfilt(sos, x, zi=etat)
        setattr(self, nom_etat, etat)
        return sortie

    def _accentuer(self, x, reseau, nom_etat):
        b, a = reseau
        if b.size == 1 and a.size == 1:
            return x
        etat = getattr(self, nom_etat)
        sortie, etat = sig.lfilter(b, a, x, zi=etat)
        setattr(self, nom_etat, etat)
        return sortie

    def _moduler(self, x: np.ndarray) -> np.ndarray:
        """Porte le signal sur la porteuse, en bande de base complexe.

        On ne synthétise pas la porteuse à sa fréquence réelle : à 5,5 MHz il
        faudrait échantillonner à plus de onze mégahertz pour transporter un
        signal de quinze kilohertz. On travaille donc **en bande de base
        complexe**, c'est-à-dire dans le repère qui tourne avec la porteuse.
        Rien n'est perdu : la fréquence porteuse ne joue aucun rôle dans ce qui
        suit, seules comptent l'excursion, la largeur de bande et la puissance.
        """
        voie = self.voie
        if voie.modulation == "AM":
            return (1.0 + voie.taux_am * x).astype(np.complex128)

        # FM : la phase est l'intégrale de l'écart de fréquence. On accumule en
        # cycles réduits modulo un, pour la même raison qu'au chapitre 12 du
        # cours — la phase absolue d'un long fichier dépasserait vite la
        # précision utile.
        pas = voie.deviation * x / self.f_travail
        cycles = self._phase + np.cumsum(pas)
        self._phase = float(cycles[-1] % 1.0)
        return np.exp(2j * np.pi * cycles)

    def _bruiter(self, z: np.ndarray) -> np.ndarray:
        """Ajoute le bruit du canal, à la densité déduite du réglage de l'image.

        La puissance à répartir se calcule sur la bande de travail entière,
        puisque c'est le filtre à fréquence intermédiaire — l'étage suivant —
        qui décidera de ce qui en reste. Régler le bruit après le filtre serait
        commode et faux : le filtre ne verrait plus rien à couper.
        """
        cn_db = self.rapport_porteuse_bruit
        if cn_db is None:
            return z
        cn = 10.0 ** (cn_db / 10.0)
        variance = self.f_travail / (largeur_carson(self.voie) * cn)
        sigma = math.sqrt(variance / 2.0)
        bruit = self._alea.normal(0.0, sigma, z.size) + 1j * self._alea.normal(
            0.0, sigma, z.size
        )
        return z + bruit

    def _filtrer_fi(self, z: np.ndarray) -> np.ndarray:
        reel, self._etat_fi_re = sig.sosfilt(self._sos_fi, z.real, zi=self._etat_fi_re)
        imag, self._etat_fi_im = sig.sosfilt(self._sos_fi, z.imag, zi=self._etat_fi_im)
        return reel + 1j * imag

    def _demoduler(self, z: np.ndarray) -> np.ndarray:
        voie = self.voie
        if voie.modulation == "AM":
            # Détecteur d'enveloppe. Il ne connaît pas la phase, donc il ne
            # profite d'aucun gain de traitement — et il rectifie le bruit au
            # lieu de le moyenner, d'où le seuil bien plus haut que celui de
            # la FM. C'est toute la fragilité du système L, et elle sort d'ici.
            enveloppe = np.abs(z)
            return (enveloppe - 1.0) / max(voie.taux_am, 1e-6)

        # Discriminateur à quadrature : l'avance d'argument d'un échantillon au
        # suivant EST l'écart de fréquence. Le même principe que le décodeur
        # de chrominance SECAM, à ceci près qu'on lui donne ici sa vraie
        # fonction historique.
        precedent = np.empty_like(z)
        precedent[0] = self._precedent
        precedent[1:] = z[:-1]
        self._precedent = complex(z[-1])

        avance = np.angle(z * np.conj(precedent))
        if self.parametres.desaccord:
            avance -= 2.0 * np.pi * self.parametres.desaccord / self.f_travail
        return avance * self.f_travail / (2.0 * np.pi * voie.deviation)

    def _ronflement(self, n: int, taux: float) -> np.ndarray:
        """Ronflement intercarrier : ligne et trame, tels que la norme les taille.

        On ne synthétise pas un bourdonnement « qui sonne juste » : on
        fabrique les deux **trains d'impulsions de suppression** que le signal
        vidéo contient réellement, avec leurs rapports cycliques normatifs, et
        on laisse les harmoniques tomber où elles tombent. C'est ce qui fait la
        différence entre un ronflement et un simple bourdon : la suppression
        trame dure 8 % du temps, celle de ligne 19 %, et ces rapports décident
        de tout le timbre.

        Le niveau suit le niveau vidéo moyen, parce que c'est la modulation de
        la porteuse image qui fabrique le défaut : une image noire ronfle peu,
        une image claire ronfle fort. Sur un poste mal réglé, on entendait le
        ronflement monter quand un générique blanc apparaissait.
        """
        norme = self.norme
        p = self.parametres

        pas_ligne = norme.f_ligne / taux
        pas_trame = norme.f_trame / taux
        indices = np.arange(n)

        phases_l = (self._phase_ligne + pas_ligne * indices) % 1.0
        phases_t = (self._phase_trame + pas_trame * indices) % 1.0
        self._phase_ligne = float((self._phase_ligne + pas_ligne * n) % 1.0)
        self._phase_trame = float((self._phase_trame + pas_trame * n) % 1.0)

        # Rapports cycliques réels des deux suppressions.
        duree_supp_ligne = 1.0 - norme.duree_ligne_active * norme.f_ligne
        lignes_supp = norme.lignes_totales - norme.lignes_actives
        duree_supp_trame = lignes_supp / norme.lignes_totales

        creneau_l = np.where(phases_l < duree_supp_ligne, 1.0, 0.0)
        creneau_t = np.where(phases_t < duree_supp_trame, 1.0, 0.0)

        # Moyenne retirée : un ronflement n'a pas de composante continue, et la
        # laisser passer ferait dériver le zéro du haut-parleur.
        creneau_l -= duree_supp_ligne
        creneau_t -= duree_supp_trame

        niveau = 0.25 * p.intercarrier * np.clip(p.niveau_video, 0.0, 1.0)
        return niveau * (0.7 * creneau_t + 0.3 * creneau_l)


# ---------------------------------------------------------------------------
# Enveloppe d'un seul appel
# ---------------------------------------------------------------------------

def transmettre(
    audio: np.ndarray,
    taux: int,
    norme: Norme,
    parametres: ParametresSon | None = None,
) -> np.ndarray:
    """Fait passer un signal audio entier par la voie son d'une norme."""
    return ChaineSon(norme, taux, parametres).traiter(audio)


# ---------------------------------------------------------------------------
# Mesures
# ---------------------------------------------------------------------------

@dataclass
class BilanSon:
    """Ce qu'on peut dire, chiffres à l'appui, d'une transmission."""

    rapport_signal_bruit: float
    """Rapport signal/bruit mesuré en sortie, en décibels."""

    distorsion: float
    """Taux de distorsion harmonique, en pour-cent."""

    reponse_db: np.ndarray = field(default_factory=lambda: np.zeros(0))
    frequences: np.ndarray = field(default_factory=lambda: np.zeros(0))

    porteuse_bruit: float | None = None
    """Rapport porteuse/bruit à l'entrée du démodulateur."""


def evaluer(norme: Norme, taux: int, parametres: ParametresSon | None = None,
            frequence: float = 1000.0, duree: float = 0.5,
            amplitude: float = 0.5) -> BilanSon:
    """Mesure la voie son sur une sinusoïde, comme on le ferait au laboratoire.

    Le rapport signal/bruit est obtenu en retirant du résultat la composante
    à la fréquence d'essai : ce qui reste est, par définition, tout ce que la
    chaîne a ajouté — bruit, distorsion et ronflement compris.

    L'amplitude d'essai compte, et par deux fois. À mi-échelle, la valeur par
    défaut, on mesure la chaîne dans ses conditions normales. Mais dès qu'on
    pousse le gain de sortie, cette même mi-échelle fait saturer l'étage final
    et la mesure décrit alors la saturation plutôt que le canal — c'est juste,
    et ce n'est pas ce qu'on cherchait. Baisser l'amplitude rend la marge.
    """
    n = int(taux * duree)
    t = np.arange(n) / taux
    essai = amplitude * np.sin(2.0 * np.pi * frequence * t)

    chaine = ChaineSon(norme, taux, parametres)
    sortie = np.asarray(chaine.traiter(essai), dtype=np.float64)

    # On écarte le début : les filtres n'y sont pas encore établis.
    garde = min(n // 4, int(0.05 * taux))
    x, y = essai[garde:], sortie[garde:]

    # Amplitude et phase de la composante utile, par projection.
    base = np.exp(-2j * np.pi * frequence * np.arange(x.size) / taux)
    coefficient = 2.0 * np.vdot(base.conj(), y) / y.size
    utile = np.real(coefficient * np.exp(2j * np.pi * frequence
                                         * np.arange(y.size) / taux))
    residu = y - utile

    puissance = float(np.mean(utile**2))
    parasite = float(np.mean(residu**2))
    snr = 10.0 * math.log10(max(puissance, 1e-30) / max(parasite, 1e-30))

    # Distorsion : harmoniques deux à cinq, rapportées au fondamental.
    spectre = np.abs(np.fft.rfft(y * np.hanning(y.size)))
    freqs = np.fft.rfftfreq(y.size, 1.0 / taux)

    def raie(f):
        if f >= freqs[-1]:
            return 0.0
        return float(spectre[np.argmin(np.abs(freqs - f))])

    fondamental = raie(frequence)
    harmoniques = math.sqrt(sum(raie(k * frequence) ** 2 for k in (2, 3, 4, 5)))
    distorsion = 100.0 * harmoniques / max(fondamental, 1e-12)

    return BilanSon(
        rapport_signal_bruit=snr,
        distorsion=distorsion,
        porteuse_bruit=chaine.rapport_porteuse_bruit,
    )


def reponse_en_frequence(
    norme: Norme, taux: int, parametres: ParametresSon | None = None,
    points: int = 24, duree: float = 0.25,
) -> tuple[np.ndarray, np.ndarray]:
    """Réponse de la voie son, mesurée fréquence par fréquence.

    On mesure au lieu de calculer : la chaîne contient un limiteur, une
    modulation et une démodulation, et rien ne garantit *a priori* que
    l'ensemble se comporte comme le produit de ses filtres.
    """
    frequences = np.geomspace(30.0, min(0.45 * taux, 20e3), points)
    gains = np.zeros(points)

    for i, f in enumerate(frequences):
        n = int(taux * duree)
        t = np.arange(n) / taux
        essai = 0.25 * np.sin(2.0 * np.pi * f * t)
        sortie = np.asarray(
            ChaineSon(norme, taux, parametres).traiter(essai), dtype=np.float64
        )
        garde = min(n // 4, int(0.05 * taux))
        y = sortie[garde:]
        base = np.exp(-2j * np.pi * f * np.arange(y.size) / taux)
        amplitude = abs(2.0 * np.vdot(base.conj(), y) / y.size)
        gains[i] = 20.0 * math.log10(max(amplitude / 0.25, 1e-9))

    return frequences, gains
