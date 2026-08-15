"""
Instruments de mesure — vectorscope, oscilloscope, analyseur de spectre, métriques.

Un simulateur qui se contente d'afficher « avant » et « après » ne prouve rien.
Ce module fournit les appareils qu'utilisait un ingénieur de la vidéo pour
mesurer ce qui se passe réellement, et les métriques qui chiffrent ce que la
chaîne a coûté à l'image.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import colorimetrie as col
from . import matrices as mx
from .constantes import Norme
from .mires import NOMS_BARRES, ORDRE_BARRES


# ---------------------------------------------------------------------------
# Vectorscope
# ---------------------------------------------------------------------------

def cibles_vectorscope(niveau: float = 0.75, gamma: float = 1.0) -> dict[str, tuple]:
    """Position des six couleurs de référence dans le plan (U, V).

    Ce sont les cases dans lesquelles doit tomber le nuage de points d'une
    mire de barres correctement codée. Un nuage tourné signale une erreur de
    teinte, un nuage rétréci une perte de saturation, un nuage étalé du bruit.

    `gamma` permet de tenir compte de la correction de gamma appliquée avant
    matriçage : à 1,0 on suppose que le niveau donné est déjà du R'G'B'.
    """
    cibles = {}
    for nom, rgb in zip(NOMS_BARRES, ORDRE_BARRES):
        if nom in ("blanc", "noir"):
            continue
        composante = np.array(rgb, dtype=float) * niveau
        if gamma != 1.0:
            composante = composante ** (1.0 / gamma)
        _, u, v = mx.rgb_vers_yuv(composante)
        cibles[nom] = (float(u), float(v))
    return cibles


def nuage_vectorscope(
    u: np.ndarray, v: np.ndarray, maximum: int = 40000, graine: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Sous-échantillonne (U, V) pour un affichage en nuage de points."""
    u = np.asarray(u).ravel()
    v = np.asarray(v).ravel()
    if u.size > maximum:
        rng = np.random.default_rng(graine)
        indices = rng.choice(u.size, maximum, replace=False)
        u, v = u[indices], v[indices]
    return u, v


def uv_de_image(image_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Extrait les composantes U et V d'une image R'G'B'."""
    yuv = mx.rgb_vers_yuv(image_rgb)
    return yuv[..., 1], yuv[..., 2]


# ---------------------------------------------------------------------------
# Oscilloscope de ligne et moniteur de forme d'onde
# ---------------------------------------------------------------------------

@dataclass
class TraceLigne:
    """Une ligne de signal composite, prête à être tracée."""

    temps_us: np.ndarray
    niveau_ire: np.ndarray
    luma_ire: np.ndarray
    norme: Norme
    numero_ligne: int


def tracer_ligne(
    composite: np.ndarray, norme: Norme, numero: int, luma: np.ndarray | None = None
) -> TraceLigne:
    """Prépare l'affichage oscilloscope d'une ligne du signal composite.

    C'est la vue la plus instructive de tout l'outil : on y voit d'un coup
    la marche d'escalier de la luminance, la sous-porteuse qui l'enfourche,
    son amplitude qui suit la saturation et sa phase qui suit la teinte.
    """
    numero = int(np.clip(numero, 0, composite.shape[0] - 1))
    ligne = composite[numero]
    t = np.linspace(0.0, norme.duree_ligne_active * 1e6, ligne.size)
    return TraceLigne(
        temps_us=t,
        niveau_ire=ligne * 100.0,
        luma_ire=(luma[numero] * 100.0 if luma is not None else np.zeros_like(ligne)),
        norme=norme,
        numero_ligne=numero,
    )


def forme_onde(luma: np.ndarray, colonnes: int = 512, lignes: int = 256) -> np.ndarray:
    """Moniteur de forme d'onde : densité des niveaux, colonne par colonne.

    Chaque colonne de l'image donne un histogramme vertical des niveaux
    rencontrés. C'est ainsi qu'on vérifie d'un coup d'œil qu'aucun niveau ne
    dépasse 100 IRE ni ne descend sous 0.
    """
    y = np.asarray(luma, dtype=np.float64)
    if y.ndim == 3:
        y = mx.luma(y)
    h, w = y.shape
    xs = (np.arange(w) * colonnes // w)
    valeurs = np.clip(y, -0.2, 1.2)
    ys = ((1.2 - valeurs) / 1.4 * (lignes - 1)).astype(int)
    image = np.zeros((lignes, colonnes))
    np.add.at(image, (ys.ravel(), np.broadcast_to(xs, y.shape).ravel()), 1.0)
    if image.max() > 0:
        image = np.log1p(image) / np.log1p(image.max())
    return image


# ---------------------------------------------------------------------------
# Analyse spectrale
# ---------------------------------------------------------------------------

def spectre_ligne(ligne: np.ndarray, f_ech: float) -> tuple[np.ndarray, np.ndarray]:
    """Spectre d'une seule ligne, en (hertz, décibels)."""
    x = np.asarray(ligne, dtype=np.float64)
    x = x - x.mean()
    fenetre = np.hanning(x.size)
    spectre = np.abs(np.fft.rfft(x * fenetre))
    freqs = np.fft.rfftfreq(x.size, d=1.0 / f_ech)
    reference = max(spectre.max(), 1e-12)
    return freqs, 20.0 * np.log10(np.maximum(spectre, 1e-12) / reference)


def raster_continu(composite: np.ndarray, norme: Norme) -> np.ndarray:
    """Reconstitue le signal en un flux continu, suppressions de ligne comprises.

    Indispensable pour voir l'**entrelacement spectral** : le peigne de raies
    espacées de f_H n'apparaît que si la période de ligne du signal analysé
    est la vraie période de ligne, blanking inclus. Analyser les seules
    parties actives mises bout à bout donnerait un peigne au mauvais pas.

    Le codeur produit déjà la ligne complète : il n'y a alors qu'à la dérouler.
    Si on ne lui passe que la partie active, on la recentre dans une ligne de
    la bonne durée.

    Les synchros ne sont pas synthétisées : elles n'apporteraient que des
    raies parasites sans rapport avec le codage de la couleur.

    Une réserve d'honnêteté : en PAL, une ligne compte 1135,0064 échantillons
    à 4·f_sc — pas un nombre entier, à cause du décalage de 25 Hz de la
    sous-porteuse. L'arrondi à 1135 introduit une dérive de quelques
    échantillons sur une image entière, qui élargit très légèrement les raies
    du spectre. En NTSC le compte est exact (910), et la démonstration de
    l'entrelacement spectral y est donc parfaitement nette.
    """
    n_lignes, n_colonnes = composite.shape
    n_total = norme.echantillons_ligne_totale
    if n_colonnes == n_total:
        return composite.ravel()
    flux = np.zeros((n_lignes, n_total))
    debut = max(0, (n_total - n_colonnes) // 2)
    flux[:, debut : debut + n_colonnes] = composite[:, : n_total - debut]
    return flux.ravel()


def spectre_raster(
    composite: np.ndarray, norme: Norme, f_max: float | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Spectre du signal complet, en (multiples de f_H, décibels).

    L'axe est gradué en multiples de la fréquence ligne, parce que c'est là
    que réside toute l'astuce : le spectre d'une image balayée se concentre
    sur les **harmoniques entiers** de f_H, laissant des creux entre eux.
    La sous-porteuse, placée sur un multiple demi-entier, va se loger dans
    ces creux — d'où la possibilité de faire cohabiter deux signaux dans la
    même bande.
    """
    flux = raster_continu(composite, norme)
    flux = flux - flux.mean()
    spectre = np.abs(np.fft.rfft(flux * np.hanning(flux.size)))
    freqs = np.fft.rfftfreq(flux.size, d=1.0 / norme.f_echantillonnage)
    if f_max is not None:
        garde = freqs <= f_max
        freqs, spectre = freqs[garde], spectre[garde]
    reference = max(spectre.max(), 1e-12)
    return freqs / norme.f_ligne, 20.0 * np.log10(np.maximum(spectre, 1e-12) / reference)


# ---------------------------------------------------------------------------
# Non-constant-luminance
# ---------------------------------------------------------------------------

def bilan_luminance(image_srgb: np.ndarray, gamma: float = 2.2) -> dict[str, np.ndarray]:
    """Quelle part de la luminance réelle la voie luma transporte-t-elle ?

    Le codeur calcule Y' à partir de composantes **déjà** gamma-corrigées.
    La luminance que porte réellement la voie Y n'est donc pas la luminance
    de la couleur, mais (Y')^γ. La différence part dans les signaux de
    chrominance — que l'on filtre ensuite à 1,3 MHz.

    Sur un bleu saturé, la voie luma ne transporte que 7 % de la luminance
    de la couleur : les 93 % restants voyagent dans un canal six fois moins
    large que celui de la luminance. C'est la **non-constant-luminance**, le
    défaut congénital de toute la télévision analogique couleur, et la raison
    pour laquelle les bleus et les rouges saturés y sont mous et baveux.
    """
    lineaire = col.srgb_vers_lineaire(np.asarray(image_srgb, dtype=np.float64))
    luminance_vraie = lineaire @ mx.COEFFS_LUMA

    rgb_prime = lineaire ** (1.0 / gamma)
    luma_prime = rgb_prime @ mx.COEFFS_LUMA
    luminance_portee = luma_prime**gamma

    with np.errstate(divide="ignore", invalid="ignore"):
        fraction = np.where(
            luminance_vraie > 1e-9, luminance_portee / luminance_vraie, 1.0
        )
    return {
        "luminance_vraie": luminance_vraie,
        "luminance_portee_par_la_luma": luminance_portee,
        "fraction_portee": fraction,
    }


# ---------------------------------------------------------------------------
# Résolution
# ---------------------------------------------------------------------------

def resolution_horizontale(bande: float, norme: Norme) -> dict[str, float]:
    """Traduit une bande passante en résolution horizontale concrète.

    Une bande de B hertz sur une ligne active de durée T porte B·T alternances.
    Il faut deux échantillons par alternance pour la représenter : la
    résolution utile est donc de 2·B·T « points » par ligne.
    """
    cycles = bande * norme.duree_ligne_active
    return {
        "bande_mhz": bande / 1e6,
        "cycles_par_ligne": cycles,
        "points_par_ligne": 2.0 * cycles,
    }


def resolution_verticale_chroma(norme: Norme, ligne_a_retard: bool = True) -> float:
    """Nombre de lignes de résolution chromatique verticale effectivement disponibles."""
    if norme.famille == "SECAM":
        return norme.lignes_actives / 2.0     # séquentiel : deux lignes par couple
    if norme.famille == "PAL" and ligne_a_retard:
        return norme.lignes_actives / 2.0     # la ligne à retard moyenne deux lignes
    return float(norme.lignes_actives)


# ---------------------------------------------------------------------------
# Métriques de comparaison
# ---------------------------------------------------------------------------

@dataclass
class Bilan:
    delta_e_moyen: float
    delta_e_median: float
    delta_e_p95: float
    delta_e_max: float
    erreur_teinte_moyenne: float
    erreur_teinte_max: float
    erreur_saturation_relative: float
    taux_ecretage: float
    resolution_chroma_h: float
    resolution_luma_h: float
    resolution_chroma_v: float
    carte_delta_e: np.ndarray

    def resume(self) -> str:
        return (
            f"ΔE moyen {self.delta_e_moyen:.2f} · médian {self.delta_e_median:.2f} · "
            f"95e centile {self.delta_e_p95:.2f} · max {self.delta_e_max:.2f}\n"
            f"teinte {self.erreur_teinte_moyenne:+.2f}° (max {self.erreur_teinte_max:.1f}°) · "
            f"saturation {self.erreur_saturation_relative:+.1%} · "
            f"écrêtage {self.taux_ecretage:.1%}\n"
            f"résolution : luma {self.resolution_luma_h:.0f} pts/ligne · "
            f"chroma {self.resolution_chroma_h:.0f} pts/ligne × "
            f"{self.resolution_chroma_v:.0f} lignes"
        )


def evaluer(resultat, seuil_saturation: float = 0.03) -> Bilan:
    """Chiffre ce que la chaîne a fait subir à l'image.

    Les erreurs de teinte et de saturation ne sont mesurées que sur les
    pixels effectivement colorés : la teinte d'un gris n'a pas de sens, et
    l'inclure dans la moyenne ne produirait que du bruit statistique.
    """
    source, finale = resultat.source, resultat.finale

    lab_src = col.srgb_vers_lab(source)
    lab_fin = col.srgb_vers_lab(finale)
    carte = col.delta_e_76(lab_src, lab_fin)

    u_src, v_src = uv_de_image(source)
    u_fin, v_fin = uv_de_image(finale)
    sat_src = np.hypot(u_src, v_src)
    sat_fin = np.hypot(u_fin, v_fin)

    colore = sat_src > seuil_saturation
    if np.any(colore):
        ecart = np.arctan2(v_fin, u_fin) - np.arctan2(v_src, u_src)
        ecart = np.rad2deg(np.mod(ecart + np.pi, 2 * np.pi) - np.pi)[colore]
        teinte_moyenne = float(np.mean(ecart))
        teinte_max = float(np.max(np.abs(ecart)))
        saturation = float(np.mean(sat_fin[colore] / sat_src[colore]) - 1.0)
    else:
        teinte_moyenne = teinte_max = saturation = 0.0

    norme = resultat.norme
    ligne_a_retard = getattr(resultat.parametres.decodage, "ligne_a_retard", True)
    enc = resultat.parametres.encodage

    return Bilan(
        delta_e_moyen=float(np.mean(carte)),
        delta_e_median=float(np.median(carte)),
        delta_e_p95=float(np.percentile(carte, 95)),
        delta_e_max=float(np.max(carte)),
        erreur_teinte_moyenne=teinte_moyenne,
        erreur_teinte_max=teinte_max,
        erreur_saturation_relative=saturation,
        taux_ecretage=resultat.taux_ecretage,
        resolution_chroma_h=resolution_horizontale(
            enc.bande_c1 or norme.bande_c1, norme
        )["points_par_ligne"],
        resolution_luma_h=resolution_horizontale(enc.bande_y or norme.bande_y, norme)[
            "points_par_ligne"
        ],
        resolution_chroma_v=resolution_verticale_chroma(norme, ligne_a_retard),
        carte_delta_e=carte,
    )


def carte_difference(source: np.ndarray, finale: np.ndarray, gain: float = 6.0):
    """Différence amplifiée, centrée sur le gris moyen — pour voir l'invisible."""
    return np.clip(0.5 + gain * (np.asarray(finale) - np.asarray(source)), 0.0, 1.0)
