"""
La chaîne complète : du fichier audio au haut-parleur du poste.

    audio ──[émetteur]──> modulateur ──> canal ──> récepteur ──> haut-parleur

L'émetteur limite la bande, comprime, préaccentue. Le modulateur fabrique
l'enveloppe complexe. Le canal y met du bruit, des voisins et de
l'évanouissement. Le récepteur filtre, démodule, désaccentue, ouvre ou ferme
son silencieux. Le haut-parleur, enfin, fait la moitié du caractère du poste.

TOUT EST EN FLUX. Chaque filtre garde son état d'un bloc au suivant, comme la
voie son de la télévision : deux blocs consécutifs se raccordent exactement, et
l'on peut donc écouter en direct pendant qu'on tourne les boutons.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sig

from tvcolor.son import reseaux_accentuation, saturer

from . import canal as canal_mod
from . import modulation as mod
from .services import F_AUDIO, HautParleur, Service, obtenir_service

LONGUEUR_REECHANTILLONNAGE = 96
"""Longueur des filtres de ré-échantillonnage. Un compromis mesuré : à 64 le
repliement remonte à −55 dB, à 128 le coût double sans rien gagner d'audible."""

LONGUEUR_FI = 129
"""Longueur du filtre de fréquence intermédiaire. Impair, pour un retard entier."""


# ---------------------------------------------------------------------------
# Ré-échantillonnage en flux
# ---------------------------------------------------------------------------

class Reechantillonneur:
    """Change la fréquence d'échantillonnage d'un facteur entier, en flux.

    Volontairement écrit de la façon la plus simple qui soit exacte : on insère
    des zéros et l'on filtre, ou l'on filtre et l'on décime. Une implémentation
    polyphase ne calculerait pas les produits par zéro et irait plus vite, mais
    la continuité d'un bloc à l'autre y devient une affaire de comptabilité fine,
    et c'est exactement le genre d'endroit où un simulateur se met à claquer une
    fois par bloc sans qu'on comprenne pourquoi.

    La seule contrainte est que la taille des blocs soit un multiple du facteur
    de décimation, ce que la chaîne garantit.
    """

    def __init__(self, facteur: int, monte: bool, complexe: bool = False):
        self.facteur = int(facteur)
        self.monte = monte
        if self.facteur <= 1:
            self.h = None
            return
        # Coupure à la moitié de la bande la plus étroite des deux, avec la
        # marge d'usage pour que la transition tienne.
        self.h = sig.firwin(
            LONGUEUR_REECHANTILLONNAGE, 0.9 / self.facteur, window=("kaiser", 8.0)
        )
        if monte:
            self.h = self.h * self.facteur
        self.zi = np.zeros(self.h.size - 1, dtype=np.complex128 if complexe else np.float64)

    def traiter(self, bloc: np.ndarray) -> np.ndarray:
        if self.h is None or bloc.size == 0:
            return bloc
        if self.monte:
            etale = np.zeros(bloc.size * self.facteur, dtype=bloc.dtype)
            etale[:: self.facteur] = bloc
            sortie, self.zi = sig.lfilter(self.h, [1.0], etale, zi=self.zi)
            return sortie
        filtre, self.zi = sig.lfilter(self.h, [1.0], bloc, zi=self.zi)
        return filtre[:: self.facteur]


# ---------------------------------------------------------------------------
# Compresseur et haut-parleur
# ---------------------------------------------------------------------------

@dataclass
class EtatCompresseur:
    gain: float = 1.0


def comprimer(
    audio: np.ndarray, plage_db: float, f_ech: float, etat: EtatCompresseur
) -> np.ndarray:
    """Compresseur du modulateur : le « power mic » des postes de communication.

    Un émetteur de radiodiffusion en met quelques décibels pour tenir sa
    modulation ; un poste de communication en met quinze, parce que ce qui
    compte n'est pas la fidélité mais que le mot arrive. C'est ce qui donne aux
    talkies leur niveau constant, leur souffle de fond remonté entre les
    syllabes, et leur fatigue à l'écoute prolongée.

    Détecteur de crête à attaque rapide et retour lent, comme un vrai : trois
    millisecondes pour rattraper une syllabe, trois cents pour redescendre.
    """
    audio = np.asarray(audio, dtype=np.float64)
    if plage_db <= 0.0 or audio.size == 0:
        return audio

    attaque = float(np.exp(-1.0 / (0.003 * f_ech)))
    retour = float(np.exp(-1.0 / (0.300 * f_ech)))
    cible = 10.0 ** (plage_db / 20.0)

    # L'enveloppe se calcule à la volée, mais on peut la vectoriser par blocs :
    # la constante de temps est très longue devant un échantillon, et suivre
    # l'enveloppe du bloc suffit à un décibel près.
    enveloppe = np.abs(audio)
    lissee = sig.lfilter([1.0 - retour], [1.0, -retour], enveloppe,
                         zi=[etat.gain * (1.0 - retour)])[0]
    etat.gain = float(np.abs(audio[-1])) if audio.size else etat.gain

    gain = np.clip(1.0 / np.maximum(lissee, 1e-3), 1.0, cible)
    del attaque
    return audio * gain


def filtre_haut_parleur(hp: HautParleur, f_ech: float):
    """Sections du second ordre reproduisant la réponse d'un transducteur.

    Trois éléments, et chacun s'entend : un passe-haut du second ordre pour le
    volume d'air derrière la membrane, un passe-bas pour l'inertie de celle-ci,
    et une cloche à la résonance principale. C'est cette cloche qui fait le
    timbre nasillard d'un talkie-walkie, bien plus que sa bande passante.
    """
    sections = []
    nyquist = f_ech / 2.0
    if hp.coupure_basse > 0.0:
        sections.append(
            sig.butter(2, min(hp.coupure_basse / nyquist, 0.99), "high", output="sos")
        )
    if 0.0 < hp.coupure_haute < nyquist * 0.99:
        sections.append(
            sig.butter(2, hp.coupure_haute / nyquist, "low", output="sos")
        )
    if hp.pointe_db > 0.0 and hp.resonance > 0.0:
        gain = 10.0 ** (hp.pointe_db / 20.0)
        omega = 2.0 * np.pi * hp.resonance / f_ech
        alpha = np.sin(omega) / 2.0 * np.sqrt(2.0)
        cos = np.cos(omega)
        racine = np.sqrt(gain)
        b = [1 + alpha * racine, -2 * cos, 1 - alpha * racine]
        a = [1 + alpha / racine, -2 * cos, 1 - alpha / racine]
        sections.append(sig.tf2sos(np.array(b) / a[0], np.array(a) / a[0]))
    if not sections:
        return None
    return np.vstack(sections)


# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------

@dataclass
class ParametresRadio:
    """Tout ce qu'on peut tourner sur le poste, et tout ce que le canal fait."""

    service: str = "pmr446"

    cn_db: float | None = None
    """Rapport porteuse/bruit dans la bande du récepteur, en décibels. `None`
    donne un canal parfait — la référence qui doit rendre le son intact."""

    desaccord: float = 0.0
    """Erreur d'accord du poste, en hertz. Sans effet notable en AM et en FM,
    dévastatrice en bande latérale unique."""

    compression_db: float | None = None
    """Compression du modulateur. `None` prend celle du service."""

    niveau_entree: float | None = None
    """Niveau à l'entrée du modulateur. `None` prend celui du service. Le monter
    fait entendre la surmodulation, qui n'est pas un défaut à éviter mais le son
    ordinaire d'une bande encombrée."""

    squelch: float = 0.0
    """Seuil du silencieux, de 0 (ouvert en permanence) à 1."""

    evanouissement: float = 0.0
    vitesse_evanouissement: float = 1.0
    """Profondeur et fréquence Doppler de l'évanouissement."""

    parasites: float = 0.0
    """Niveau des parasites atmosphériques, de 0 à 1."""

    co_canal: float = 0.0
    ecart_co_canal: float = 1_000.0
    """Seconde station sur la même fréquence : niveau relatif et écart en hertz.
    C'est le sifflement de deux avions qui parlent ensemble."""

    adjacent: float = 0.0
    """Niveau de la station du canal voisin, avant le filtre du récepteur."""

    haut_parleur: bool = True
    volume: float = 1.0
    graine: int = 20_250_818

    def resolu(self) -> Service:
        return obtenir_service(self.service)


# ---------------------------------------------------------------------------
# La chaîne
# ---------------------------------------------------------------------------

class ChaineRadio:
    """Émission, canal et réception, en flux.

    À utiliser bloc par bloc. La taille des blocs est libre, à ceci près qu'elle
    doit être un multiple du facteur de ré-échantillonnage du service — ce que
    `taille_de_bloc` calcule.
    """

    def __init__(self, parametres: ParametresRadio | None = None):
        self.parametres = parametres or ParametresRadio()
        self.service = self.parametres.resolu()
        self.reinitialiser()

    # -- mise en place ---------------------------------------------------

    def reinitialiser(self) -> None:
        p, s = self.parametres, self.service
        self._alea = np.random.default_rng(p.graine)

        # Émetteur : bande audio, accentuation.
        self._sos_emission = self._passe_bande(s.audio_basse, s.audio_haute, F_AUDIO)
        self._zi_emission = sig.sosfilt_zi(self._sos_emission) * 0.0
        (self._pre, self._des) = reseaux_accentuation(
            s.tau_accentuation, s.audio_haute, F_AUDIO
        )
        self._zi_pre = np.zeros(max(len(self._pre[0]), len(self._pre[1])) - 1)
        self._zi_des = np.zeros(max(len(self._des[0]), len(self._des[1])) - 1)
        self._compresseur = EtatCompresseur()

        # Ré-échantillonnage.
        self._monte = Reechantillonneur(s.facteur_travail, monte=True, complexe=False)
        self._descend = Reechantillonneur(s.facteur_travail, monte=False, complexe=False)

        # Modulation.
        self._fm_emission = mod.EtatFM()
        self._fm_reception = mod.EtatFM()
        self._blu_emission = mod.EtatBLU()
        self._blu_reception = mod.EtatBLU()
        self._decalage = mod.EtatDecalage()

        # Canal.
        self._fading = canal_mod.EtatEvanouissement()
        self._qrn = canal_mod.EtatAtmospherique()
        self._brouilleur = canal_mod.EtatBrouilleur()
        self._adjacent = canal_mod.EtatBrouilleur()

        # Récepteur : filtre de fréquence intermédiaire, complexe.
        coupure = min(
            0.5 * s.largeur_recepteur / (s.f_travail / 2.0) * 0.5, 0.49
        ) * 2.0
        self._noyau_fi = sig.firwin(
            LONGUEUR_FI, max(coupure, 1e-3), window=("kaiser", 8.0)
        ).astype(np.complex128)
        self._zi_fi = np.zeros(LONGUEUR_FI - 1, dtype=np.complex128)

        # Récepteur : audio.
        self._sos_reception = self._passe_bande(s.audio_basse, s.audio_haute, F_AUDIO)
        self._zi_reception = sig.sosfilt_zi(self._sos_reception) * 0.0

        # Silencieux à bruit : on écoute une bande AU-DESSUS de l'audio.
        self._sos_squelch = sig.butter(
            2, [5_000.0 / (F_AUDIO / 2), 7_000.0 / (F_AUDIO / 2)], "band", output="sos"
        )
        self._zi_squelch = sig.sosfilt_zi(self._sos_squelch) * 0.0
        self._niveau_bruit = 0.0
        self._ouverture = 0.0

        # Haut-parleur.
        self._sos_hp = filtre_haut_parleur(s.haut_parleur, F_AUDIO)
        self._zi_hp = (
            sig.sosfilt_zi(self._sos_hp) * 0.0 if self._sos_hp is not None else None
        )

    @staticmethod
    def _passe_bande(basse: float, haute: float, f_ech: float) -> np.ndarray:
        nyquist = f_ech / 2.0
        haute = min(haute, nyquist * 0.98)
        if basse <= 0.0:
            return sig.butter(4, haute / nyquist, "low", output="sos")
        return sig.butter(
            4, [basse / nyquist, haute / nyquist], "band", output="sos"
        )

    def taille_de_bloc(self, souhaitee: int = 4096) -> int:
        """Arrondit une taille de bloc à un multiple du facteur du service."""
        facteur = self.service.facteur_travail
        return max(facteur, int(round(souhaitee / facteur)) * facteur)

    # -- le trajet -------------------------------------------------------

    def traiter(self, audio: np.ndarray) -> np.ndarray:
        """Fait passer un bloc audio mono par toute la chaîne."""
        p, s = self.parametres, self.service
        audio = np.asarray(audio, dtype=np.float64).reshape(-1)
        if audio.size == 0:
            return audio

        module = self._emettre(audio)
        enveloppe = self._moduler(module)
        enveloppe = self._traverser(enveloppe)
        demodule = self._recevoir(enveloppe)
        return self._restituer(demodule)

    def _emettre(self, audio: np.ndarray) -> np.ndarray:
        p, s = self.parametres, self.service

        audio, self._zi_emission = sig.sosfilt(
            self._sos_emission, audio, zi=self._zi_emission
        )
        plage = s.compression_db if p.compression_db is None else p.compression_db
        audio = comprimer(audio, plage, F_AUDIO, self._compresseur)

        niveau = s.niveau_modulation if p.niveau_entree is None else p.niveau_entree
        audio = audio * niveau

        if s.tau_accentuation > 0.0:
            audio, self._zi_pre = sig.lfilter(
                self._pre[0], self._pre[1], audio, zi=self._zi_pre
            )
        # L'émetteur ne laisse jamais sortir plus que son excursion nominale :
        # c'est un limiteur, pas un vœu pieux.
        return saturer(audio)

    def _moduler(self, audio: np.ndarray) -> np.ndarray:
        s = self.service
        haut = self._monte.traiter(audio)
        if s.modulation == "FM":
            return mod.moduler_fm(haut, s.excursion, s.f_travail, self._fm_emission)
        if s.modulation == "BLU":
            return mod.moduler_blu(haut, True, self._blu_emission)
        return mod.moduler_am(haut, s.indice)

    def _traverser(self, enveloppe: np.ndarray) -> np.ndarray:
        p, s = self.parametres, self.service
        taille = enveloppe.size

        if p.evanouissement > 0.0:
            enveloppe = canal_mod.evanouissement(
                enveloppe, p.evanouissement, p.vitesse_evanouissement,
                s.f_travail, self._fading, self._alea,
            )
        if p.co_canal > 0.0:
            enveloppe = enveloppe + canal_mod.co_canal(
                taille, p.co_canal, p.ecart_co_canal, s.f_travail, self._brouilleur
            )
        if p.adjacent > 0.0:
            enveloppe = enveloppe + canal_mod.canal_adjacent(
                taille, p.adjacent, s.espacement, s.excursion or 3_000.0,
                s.f_travail, self._adjacent, s.modulation,
            )
        if p.parasites > 0.0:
            enveloppe = enveloppe + canal_mod.atmospherique(
                taille, 40.0 * p.parasites, 4.0 * p.parasites,
                s.f_travail, self._qrn, self._alea,
            )
        if p.cn_db is not None:
            sigma = canal_mod.sigma_bruit(
                p.cn_db, s.f_travail, s.largeur_recepteur
            )
            enveloppe = enveloppe + canal_mod.bruit_complexe(taille, sigma, self._alea)
        return enveloppe

    def _recevoir(self, enveloppe: np.ndarray) -> np.ndarray:
        p, s = self.parametres, self.service

        if p.desaccord != 0.0:
            enveloppe = mod.decaler(
                enveloppe, -p.desaccord, s.f_travail, self._decalage
            )

        enveloppe, self._zi_fi = sig.lfilter(
            self._noyau_fi, [1.0], enveloppe, zi=self._zi_fi
        )

        if s.modulation == "FM":
            # Le limiteur : la FM ne porte rien dans son amplitude, et l'ôter
            # supprime tout le bruit qui s'y trouvait. C'est la moitié de
            # l'avantage de la modulation de fréquence.
            module = np.abs(enveloppe)
            enveloppe = enveloppe / np.maximum(module, 1e-12)
            demodule = mod.demoduler_fm(
                enveloppe, s.excursion, s.f_travail, self._fm_reception
            )
        elif s.modulation == "BLU":
            demodule = mod.demoduler_blu(
                enveloppe, True, 0.0, s.f_travail, self._blu_reception
            )
        else:
            demodule = mod.demoduler_am(enveloppe)

        bas = self._descend.traiter(demodule)
        if s.modulation == "AM":
            # Le condensateur de découplage du détecteur : il ôte la porteuse,
            # qui est une composante continue, et rend l'audio seul.
            bas = bas - np.mean(bas) if bas.size else bas
            bas = bas / max(self.service.indice, 1e-3)
        return bas

    def _restituer(self, demodule: np.ndarray) -> np.ndarray:
        p = self.parametres

        ouvert = self._silencieux(demodule)

        audio, self._zi_reception = sig.sosfilt(
            self._sos_reception, demodule, zi=self._zi_reception
        )
        if self.service.tau_accentuation > 0.0:
            audio, self._zi_des = sig.lfilter(
                self._des[0], self._des[1], audio, zi=self._zi_des
            )

        audio = audio * ouvert
        if p.haut_parleur and self._sos_hp is not None:
            audio, self._zi_hp = sig.sosfilt(self._sos_hp, audio, zi=self._zi_hp)
        return audio * p.volume * self.service.gain_audio

    def _silencieux(self, demodule: np.ndarray) -> np.ndarray:
        """Silencieux à bruit : il écoute le souffle, pas la porteuse.

        C'est le vrai mécanisme, et il explique tout le reste. Un récepteur FM
        sans signal sort un souffle qui monte jusqu'au bout de sa bande ; avec un
        signal, la porteuse « capture » le discriminateur et ce souffle s'écroule.
        On mesure donc le bruit dans une bande **au-dessus de l'audio**, entre 5
        et 7 kilohertz : fort = pas de signal, faible = signal présent.

        Le fameux « pschit » de fin de transmission en découle sans qu'on ait
        rien à ajouter : quand l'émetteur relâche l'alternat, le souffle revient
        avant que le circuit n'ait eu le temps de refermer, et l'on entend un
        éclat de bruit.
        """
        p = self.parametres
        if p.squelch <= 0.0 or demodule.size == 0:
            return np.ones(max(demodule.size, 1))

        bande, self._zi_squelch = sig.sosfilt(
            self._sos_squelch, demodule, zi=self._zi_squelch
        )
        niveau = float(np.sqrt(np.mean(bande**2)))
        # Lissage : le silencieux ne doit pas hacher sur une syllabe.
        alpha = 0.3
        self._niveau_bruit = (1 - alpha) * self._niveau_bruit + alpha * niveau

        seuil = 0.02 + 0.30 * p.squelch
        cible = 1.0 if self._niveau_bruit < seuil else 0.0
        # Ouverture rapide, fermeture lente — comme un vrai.
        vitesse = 0.5 if cible > self._ouverture else 0.08
        depart = self._ouverture
        self._ouverture = depart + (cible - depart) * vitesse
        return np.linspace(depart, self._ouverture, demodule.size)


def transmettre(
    audio: np.ndarray, parametres: ParametresRadio | None = None,
    taille_bloc: int = 8192,
) -> np.ndarray:
    """Fait passer un signal entier par la chaîne, bloc par bloc.

    Commodité pour les tests et l'export : le résultat est identique à ce qu'on
    obtiendrait en écoutant en direct, puisque la chaîne est la même et qu'elle
    garde son état.
    """
    chaine = ChaineRadio(parametres)
    taille = chaine.taille_de_bloc(taille_bloc)
    audio = np.asarray(audio, dtype=np.float64).reshape(-1)
    morceaux = [
        chaine.traiter(audio[debut : debut + taille])
        for debut in range(0, audio.size, taille)
    ]
    return np.concatenate(morceaux) if morceaux else np.zeros(0)
