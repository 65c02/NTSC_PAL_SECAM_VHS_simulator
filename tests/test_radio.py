"""
Vérifie le simulateur radio : ses modulations, son canal, ses lois.

Le critère est le même que pour la télévision. Ce qui n'est pas un phénomène
simulé doit passer sans laisser de trace : sur un canal parfait, la chaîne rend
le son intact à la bande passante près. Et ce qui EST un phénomène doit suivre
sa loi, pas ressembler à son effet — le gain de démodulation FM, le seuil, le
battement de deux porteuses, le décalage d'une bande latérale unique désaccordée
sont tous mesurés contre leur formule.
"""

from __future__ import annotations

import numpy as np
import pytest

from radio import canal as canal_mod
from radio import modulation as mod
from radio.chaine import ChaineRadio, ParametresRadio, transmettre
from radio.services import F_AUDIO, SERVICES, obtenir_service

DUREE = 1.5
TEMPS = np.arange(int(DUREE * F_AUDIO)) / F_AUDIO


def _ton(frequence: float, amplitude: float = 0.5) -> np.ndarray:
    return amplitude * np.sin(2.0 * np.pi * frequence * TEMPS)


def _spectre(signal: np.ndarray):
    """(fréquences, module) d'un signal audio, fenêtré."""
    signal = np.asarray(signal, dtype=np.float64)
    fenetre = np.hanning(signal.size)
    return (
        np.fft.rfftfreq(signal.size, 1.0 / F_AUDIO),
        np.abs(np.fft.rfft(signal * fenetre)),
    )


def _snr_du_ton(sortie: np.ndarray, frequence: float = 1_000.0) -> float:
    """Rapport signal/bruit, en isolant la raie du ton du reste du spectre."""
    frequences, module = _spectre(sortie)
    k = int(np.argmin(np.abs(frequences - frequence)))
    raie = slice(max(0, k - 3), k + 4)
    signal = float(np.sum(module[raie] ** 2))
    total = float(np.sum(module**2))
    return 10.0 * np.log10(signal / max(total - signal, 1e-20))


# ---------------------------------------------------------------------------
# Les modulations, aller et retour
# ---------------------------------------------------------------------------

def test_am_est_exactement_reversible():
    """Détecteur d'enveloppe : le module rend l'audio au bit près.

    Sous le taux de modulation de 100 %, l'enveloppe reste positive et son
    module est donc l'enveloppe elle-même. Il n'y a rien à approcher.
    """
    audio = _ton(1_000.0, 0.8)
    lu = mod.demoduler_am(mod.moduler_am(audio, 0.85))
    assert np.abs((lu - 1.0) / 0.85 - audio).max() < 1e-12


def test_la_surmodulation_am_replie_l_enveloppe():
    """Au-delà de 100 %, le détecteur replie la partie négative.

    Ce n'est pas un défaut du simulateur mais la physique d'une diode : elle ne
    connaît que le module. C'est le son de la CB poussée à fond, et il vaut
    mieux l'entendre que l'interdire.
    """
    audio = _ton(1_000.0, 1.0)
    lu = mod.demoduler_am(mod.moduler_am(audio, 1.6))
    # Le repliement fabrique une harmonique deux qui n'existait pas.
    frequences, module = _spectre(lu - lu.mean())
    fondamentale = module[int(np.argmin(np.abs(frequences - 1_000.0)))]
    harmonique = module[int(np.argmin(np.abs(frequences - 2_000.0)))]
    assert harmonique > 0.1 * fondamentale


def test_fm_est_reversible_et_se_raccorde_entre_blocs():
    """Le discriminateur rend l'audio, et deux blocs se recollent exactement.

    Le raccord n'a rien d'accessoire : sans l'échantillon gardé d'un bloc à
    l'autre, il manquerait une différence de phase à chaque frontière et l'on
    entendrait un clic toutes les quelques millisecondes.
    """
    audio = _ton(700.0, 0.6)
    emission, reception = mod.EtatFM(), mod.EtatFM()
    milieu = audio.size // 2

    enveloppe = np.concatenate([
        mod.moduler_fm(audio[:milieu], 2_500.0, F_AUDIO, emission),
        mod.moduler_fm(audio[milieu:], 2_500.0, F_AUDIO, emission),
    ])
    lu = np.concatenate([
        mod.demoduler_fm(enveloppe[:milieu], 2_500.0, F_AUDIO, reception),
        mod.demoduler_fm(enveloppe[milieu:], 2_500.0, F_AUDIO, reception),
    ])
    assert np.abs(lu[1:] - audio[1:]).max() < 1e-9


def test_fm_a_une_amplitude_constante():
    """Toute l'immunité de la FM tient dans cette ligne."""
    enveloppe = mod.moduler_fm(_ton(1_000.0, 0.9), 5_000.0, F_AUDIO, mod.EtatFM())
    assert np.abs(np.abs(enveloppe) - 1.0).max() < 1e-12


def test_blu_est_reversible_au_retard_pres():
    audio = _ton(1_200.0, 0.7)
    emission, reception = mod.EtatBLU(), mod.EtatBLU()
    enveloppe = mod.moduler_blu(audio, True, emission)
    lu = mod.demoduler_blu(enveloppe, True, 0.0, F_AUDIO, reception)
    retard = mod.LONGUEUR_HILBERT // 2
    assert np.abs(lu[retard + 500 :] - audio[500 : -retard]).max() < 1e-9


def test_blu_desaccordee_decale_le_spectre():
    """Le canard de Donald, et sa mesure.

    Une erreur d'accord ne multiplie pas les fréquences, elle les DÉCALE : les
    harmoniques cessent d'être des multiples de la fondamentale, et la voix
    perd son timbre. C'est pour cela qu'un poste BLU a un bouton d'accord fin.
    """
    audio = _ton(1_000.0, 0.7)
    enveloppe = mod.moduler_blu(audio, True, mod.EtatBLU())
    for desaccord in (-120.0, 0.0, 250.0):
        lu = mod.demoduler_blu(
            enveloppe, True, desaccord, F_AUDIO, mod.EtatBLU()
        )
        frequences, module = _spectre(lu[1_000:])
        pic = frequences[int(np.argmax(module))]
        # Convention : `desaccord` est l'erreur d'accord du RÉCEPTEUR. Accordé
        # trop haut, il fait descendre l'audio d'autant — et réciproquement.
        assert abs(pic - (1_000.0 - desaccord)) < 15.0


# ---------------------------------------------------------------------------
# Le canal
# ---------------------------------------------------------------------------

def test_le_bruit_a_la_puissance_demandee():
    alea = np.random.default_rng(1)
    bruit = canal_mod.bruit_complexe(200_000, 0.5, alea)
    assert abs(float(np.mean(np.abs(bruit) ** 2)) - 0.25) < 0.01
    # Circulaire : les deux quadratures ont la même puissance, et sont décorrélées.
    assert abs(float(np.std(bruit.real) - np.std(bruit.imag))) < 0.01
    assert abs(float(np.mean(bruit.real * bruit.imag))) < 0.01


def test_le_bruit_est_rapporte_a_la_bande_du_recepteur():
    """Le rapport porteuse/bruit se définit dans la bande du RÉCEPTEUR.

    C'est le point délicat de tout le module, et il faut le vérifier plutôt que
    l'espérer. Le bruit est injecté sur toute la largeur de la simulation, bien
    plus vaste que le canal ; sa densité est donc relevée dans le rapport des
    deux largeurs, pour qu'après le filtre de fréquence intermédiaire il reste
    exactement ce qui était demandé.

    La conséquence, qui déroute au premier abord : rétrécir le filtre
    n'améliore PAS le rapport annoncé, il le maintient. Ce qu'on gagne à
    rétrécir, c'est de la portée à densité de bruit donnée — et cela se lit sur
    la formule, qui est ce qu'on vérifie ici.
    """
    from radio.canal import sigma_bruit

    for largeur in (2_700.0, 8_000.0, 16_000.0, 180_000.0):
        for cn in (6.0, 20.0):
            sigma = sigma_bruit(cn, 288_000.0, largeur)
            # Puissance de bruit qui subsiste dans la bande du récepteur.
            restante = sigma**2 * largeur / 288_000.0
            assert abs(10.0 * np.log10(1.0 / restante) - cn) < 1e-9

    # Et à rapport annoncé égal, deux récepteurs de largeurs différentes
    # doivent rendre le même son : c'est la normalisation qui le garantit.
    import dataclasses

    from radio.services import SERVICES as table

    table["aero-large"] = dataclasses.replace(
        obtenir_service("aero-vhf"), code="aero-large", largeur_recepteur=16_000.0
    )
    try:
        mesures = [
            _snr_du_ton(transmettre(
                _ton(1_000.0), ParametresRadio(service=code, cn_db=15.0,
                                               haut_parleur=False, compression_db=0.0)
            )[F_AUDIO // 2 :])
            for code in ("aero-vhf", "aero-large")
        ]
    finally:
        del table["aero-large"]
    assert abs(mesures[0] - mesures[1]) < 4.0, mesures


def test_deux_porteuses_sifflent_a_leur_ecart():
    """Pourquoi l'aéronautique est restée en modulation d'amplitude.

    Deux avions qui parlent ensemble battent l'un contre l'autre, et le
    contrôleur ENTEND qu'il y a eu collision. Le sifflement n'est pas ajouté :
    c'est le module de la somme de deux nombres complexes, et sa fréquence est
    l'écart des deux émetteurs. On le vérifie à trois écarts différents.
    """
    for ecart in (400.0, 1_000.0, 1_800.0):
        sortie = transmettre(
            np.zeros(TEMPS.size),
            ParametresRadio(service="aero-vhf", cn_db=None, haut_parleur=False,
                            co_canal=0.5, ecart_co_canal=ecart),
        )[F_AUDIO // 2 :]
        frequences, module = _spectre(sortie)
        assert abs(frequences[int(np.argmax(module))] - ecart) < 20.0


# ---------------------------------------------------------------------------
# La chaîne complète
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", sorted(SERVICES))
def test_canal_parfait_rend_le_son(code):
    """Sans bruit, la chaîne doit rendre un son propre — c'est le contrôle.

    On ne peut pas exiger l'identité : chaque service limite la bande, comprime
    et accentue, et c'est bien ce qu'on lui demande. Mais la raie du ton doit
    ressortir très au-dessus de tout ce que la chaîne a pu fabriquer d'autre.
    """
    sortie = transmettre(
        _ton(1_000.0), ParametresRadio(service=code, cn_db=None,
                                       haut_parleur=False, compression_db=0.0)
    )[F_AUDIO // 2 :]
    assert _snr_du_ton(sortie) > 30.0
    assert np.isfinite(sortie).all()


@pytest.mark.parametrize("code", sorted(SERVICES))
def test_la_bande_audio_est_celle_du_service(code):
    """Un balayage entre et ressort : on lit la bande passante sur la sortie."""
    service = obtenir_service(code)
    balayage = 0.4 * np.sin(
        2.0 * np.pi * np.cumsum(np.linspace(50.0, 8_000.0, TEMPS.size)) / F_AUDIO
    )
    sortie = transmettre(
        balayage, ParametresRadio(service=code, cn_db=None, haut_parleur=False,
                                  compression_db=0.0)
    )
    frequences, module = _spectre(sortie[F_AUDIO // 4 :])
    energie = module**2

    def part(basse, haute):
        dedans = (frequences >= basse) & (frequences < haute)
        return float(np.sum(energie[dedans]) / max(np.sum(energie), 1e-20))

    # L'essentiel de l'énergie est dans la bande annoncée, et il ne reste
    # presque rien une octave au-dessus.
    assert part(service.audio_basse * 0.7, service.audio_haute * 1.3) > 0.80
    assert part(service.audio_haute * 2.0, F_AUDIO / 2) < 0.02


def test_l_am_suit_le_rapport_porteuse_bruit():
    """En amplitude, un décibel de porteuse rend un décibel de signal.

    C'est la loi de l'AM, et elle n'a rien de gratuit : la démodulation
    d'enveloppe ne gagne rien sur le bruit, contrairement à la FM. L'écart
    constant vient de la part de puissance qui va dans la porteuse plutôt que
    dans les bandes latérales.
    """
    mesures = {}
    for cn in (10.0, 20.0, 30.0, 40.0):
        sortie = transmettre(
            _ton(1_000.0), ParametresRadio(service="aero-vhf", cn_db=cn,
                                           haut_parleur=False, compression_db=0.0)
        )[F_AUDIO // 2 :]
        mesures[cn] = _snr_du_ton(sortie)

    pentes = [
        (mesures[b] - mesures[a]) / (b - a)
        for a, b in ((10.0, 20.0), (20.0, 30.0), (30.0, 40.0))
    ]
    assert all(0.9 < pente < 1.1 for pente in pentes), mesures


def test_la_fm_gagne_ce_que_sa_largeur_de_bande_lui_coute():
    """Le gain de démodulation FM, mesuré et comparé aux trois services.

    Plus l'excursion est grande devant la bande audio, plus la FM gagne — et
    plus elle occupe de canal. Les trois services simulés couvrent presque deux
    décades d'indice de modulation, et leurs gains doivent se classer dans le
    même ordre.
    """
    resultats = {}
    for code in ("pmr446", "marine-vhf", "fm-mono"):
        sortie = transmettre(
            _ton(1_000.0), ParametresRadio(service=code, cn_db=25.0,
                                           haut_parleur=False, compression_db=0.0)
        )[F_AUDIO // 2 :]
        resultats[code] = _snr_du_ton(sortie) - 25.0

    assert resultats["pmr446"] < resultats["marine-vhf"] < resultats["fm-mono"]
    # Et toutes trois font mieux que l'AM, qui perd cinq décibels.
    assert resultats["pmr446"] > 0.0


def test_le_seuil_fm_existe_et_est_brutal():
    """Sous le seuil, la FM ne se dégrade pas : elle s'effondre.

    C'est sa contrepartie. Tant que la porteuse domine, le bruit d'amplitude est
    éliminé par le limiteur ; quand le vecteur de bruit se met à faire le tour
    de l'origine, le discriminateur sort des impulsions et le rapport
    signal/bruit s'écroule bien plus vite qu'un décibel par décibel.
    """
    mesures = {
        cn: _snr_du_ton(transmettre(
            _ton(1_000.0), ParametresRadio(service="fm-mono", cn_db=cn,
                                           haut_parleur=False, compression_db=0.0)
        )[F_AUDIO // 2 :])
        for cn in (0.0, 5.0, 10.0, 25.0)
    }
    au_dessus = (mesures[25.0] - mesures[10.0]) / 15.0
    au_dessous = (mesures[5.0] - mesures[0.0]) / 5.0
    assert au_dessous > 1.5 * au_dessus, mesures


def test_le_silencieux_ferme_sur_le_bruit_et_ouvre_sur_le_signal():
    """Silencieux à bruit : il écoute le souffle au-dessus de l'audio.

    Sans porteuse, un discriminateur FM sort un souffle qui monte jusqu'au bout
    de sa bande ; avec une porteuse, ce souffle s'écroule. Le silencieux mesure
    donc entre 5 et 7 kHz, là où il n'y a jamais de parole.
    """
    silence = np.zeros(TEMPS.size)
    commun = dict(service="pmr446", haut_parleur=False, squelch=0.5)

    souffle = transmettre(silence, ParametresRadio(**commun, cn_db=-6.0))
    parole = transmettre(_ton(1_000.0), ParametresRadio(**commun, cn_db=30.0))

    niveau_souffle = float(np.sqrt(np.mean(souffle[F_AUDIO:] ** 2)))
    niveau_parole = float(np.sqrt(np.mean(parole[F_AUDIO:] ** 2)))
    assert niveau_parole > 20.0 * niveau_souffle


def test_le_haut_parleur_change_le_timbre():
    """La moitié du caractère d'un poste, et elle est mesurable."""
    commun = dict(service="pmr446", cn_db=None, compression_db=0.0)

    def raie(frequence):
        audio = 0.3 * np.sin(2.0 * np.pi * frequence * TEMPS)
        niveaux = []
        for hp in (False, True):
            sortie = transmettre(audio, ParametresRadio(**commun, haut_parleur=hp))
            frequences, module = _spectre(sortie[F_AUDIO // 2 :])
            niveaux.append(module[int(np.argmin(np.abs(frequences - frequence)))])
        return niveaux[1] / max(niveaux[0], 1e-12)

    # On mesure la RAIE et non la puissance totale : la cloche de résonance
    # relève tout le milieu de bande, y compris ce que la chaîne a fabriqué
    # ailleurs, et une mesure large conclurait à l'inverse de la vérité.
    assert raie(200.0) < 0.4       # un transducteur de 36 mm ne descend pas
    assert raie(1_100.0) > 1.5     # et il résonne là où il a été conçu pour


def test_la_chaine_se_decoupe_sans_clic():
    """Deux découpages différents du même signal donnent le même résultat.

    C'est le contrôle qui garantit qu'on peut écouter en direct : si un filtre
    oubliait son état d'un bloc à l'autre, la sortie dépendrait de la taille des
    blocs, et l'on entendrait un clic à chaque frontière.
    """
    audio = _ton(800.0, 0.5)
    commun = dict(service="marine-vhf", cn_db=None, haut_parleur=True)
    a = transmettre(audio, ParametresRadio(**commun), taille_bloc=1_024)
    b = transmettre(audio, ParametresRadio(**commun), taille_bloc=8_192)
    assert np.abs(a - b).max() < 1e-9


# ---------------------------------------------------------------------------
# La table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", sorted(SERVICES))
def test_la_fenetre_de_simulation_contient_le_canal(code):
    """L'enveloppe complexe doit être échantillonnée plus large que Carson.

    Sans quoi les bandes latérales se replieraient sur elles-mêmes, et l'on
    mesurerait du repliement en croyant mesurer de la distorsion.
    """
    service = SERVICES[code]
    assert service.f_travail >= service.largeur_carson
    assert service.f_travail % F_AUDIO == 0


def test_service_inconnu_le_dit():
    with pytest.raises(KeyError, match="service inconnu"):
        obtenir_service("bande-des-27-metres")
