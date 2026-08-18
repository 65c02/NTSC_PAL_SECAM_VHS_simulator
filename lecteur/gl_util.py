"""
Outils OpenGL : compilation des programmes, cibles de rendu, quad plein écran.

Rien d'exotique — mais deux points méritent d'être signalés, parce qu'ils
coûtent des heures quand on les découvre à l'exécution.

**Filtrage au plus proche.** Les textures intermédiaires sont échantillonnées
en NEAREST, jamais en linéaire. Les boucles de filtrage visent des centres de
texel exacts : une interpolation bilinéaire, même « négligeable », mélangerait
des échantillons voisins et fausserait la démodulation de la sous-porteuse,
qui n'occupe que quatre échantillons par cycle.

**Précision flottante.** Le signal composite peut descendre à -1/3 et monter à
+4/3 : un format entier normalisé l'écrêterait des deux côtés. La somme
préfixe du SECAM, elle, exige 32 bits — en 16 bits la phase accumulée sur une
ligne dériverait de plusieurs degrés.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from OpenGL import GL

DOSSIER_SHADERS = Path(__file__).resolve().parent.parent / "shaders"


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def lire_source(nom: str) -> str:
    return (DOSSIER_SHADERS / nom).read_text(encoding="utf-8")


def assembler(fichier: str, defines: dict[str, object] | None = None) -> str:
    """Assemble un shader de norme : entête de version, défines, commun, corps.

    Les trois normes partagent `commun.glsl`, simplement concaténé. GLSL n'a
    pas de directive d'inclusion : c'est à l'application de le faire, et la
    concaténation textuelle est exactement ce que fait n'importe quel moteur.
    """
    lignes = ["#version 330 core"]
    for cle, valeur in (defines or {}).items():
        lignes.append(f"#define {cle} {valeur}" if valeur is not None else f"#define {cle}")
    lignes.append(lire_source("commun.glsl"))
    lignes.append(lire_source(fichier))
    return "\n".join(lignes)


def assembler_simple(fichier: str, defines: dict[str, object] | None = None) -> str:
    """Assemble un shader autonome : version et défines, mais pas `commun.glsl`.

    Sert aux passes qui ne touchent pas au codage couleur — le halo, la somme
    préfixe, la présentation. Leur imposer l'entête commun les obligerait à
    déclarer N_TAPS et N_NOTCH, dont elles n'ont que faire, et à recompiler à
    chaque changement de qualité.
    """
    lignes = ["#version 330 core"]
    for cle, valeur in (defines or {}).items():
        lignes.append(f"#define {cle} {valeur}" if valeur is not None else f"#define {cle}")
    lignes.append(lire_source(fichier))
    return "\n".join(lignes)


def _compiler(source: str, type_shader, etiquette: str) -> int:
    shader = GL.glCreateShader(type_shader)
    GL.glShaderSource(shader, source)
    GL.glCompileShader(shader)
    if not GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS):
        journal = GL.glGetShaderInfoLog(shader).decode("utf-8", "replace")
        numerotee = "\n".join(
            f"{n + 1:4d} | {ligne}" for n, ligne in enumerate(source.split("\n"))
        )
        GL.glDeleteShader(shader)
        raise RuntimeError(f"compilation de {etiquette} :\n{journal}\n\n{numerotee}")
    return shader


class Programme:
    """Un programme GLSL, avec cache des emplacements d'uniformes."""

    def __init__(self, source_sommet: str, source_fragment: str, etiquette: str = ""):
        self.etiquette = etiquette
        sommet = _compiler(source_sommet, GL.GL_VERTEX_SHADER, f"{etiquette}/sommet")
        fragment = _compiler(source_fragment, GL.GL_FRAGMENT_SHADER, f"{etiquette}/fragment")

        self.id = GL.glCreateProgram()
        GL.glAttachShader(self.id, sommet)
        GL.glAttachShader(self.id, fragment)
        GL.glLinkProgram(self.id)
        GL.glDeleteShader(sommet)
        GL.glDeleteShader(fragment)

        if not GL.glGetProgramiv(self.id, GL.GL_LINK_STATUS):
            journal = GL.glGetProgramInfoLog(self.id).decode("utf-8", "replace")
            raise RuntimeError(f"édition de liens de {etiquette} :\n{journal}")

        self._emplacements: dict[str, int] = {}

    def utiliser(self) -> None:
        GL.glUseProgram(self.id)

    def _ou(self, nom: str) -> int:
        if nom not in self._emplacements:
            self._emplacements[nom] = GL.glGetUniformLocation(self.id, nom)
        return self._emplacements[nom]

    def definir(self, nom: str, valeur) -> None:
        """Affecte un uniforme, en déduisant son type de la valeur Python.

        Un uniforme absent du programme — parce que le compilateur l'a éliminé,
        n'étant pas utilisé — reçoit l'emplacement -1 et est simplement ignoré.
        C'est le comportement voulu : les trois normes partagent un même jeu
        d'uniformes dont chacune n'emploie qu'une partie.
        """
        ou = self._ou(nom)
        if ou < 0:
            return

        if isinstance(valeur, np.ndarray) and valeur.ndim == 2:
            # Une matrice 3x3. `transpose=GL_TRUE` parce que numpy range par
            # lignes et GLSL par colonnes : sans cela on transmettrait la
            # transposée, ce qui pour une matrice de couleurs ne se voit pas
            # tout de suite mais fausse tout.
            if valeur.shape != (3, 3):
                raise TypeError(f"uniforme {nom} : matrice {valeur.shape} non gérée")
            GL.glUniformMatrix3fv(ou, 1, GL.GL_TRUE, valeur.astype(np.float32))
        elif isinstance(valeur, np.ndarray):
            GL.glUniform1fv(ou, valeur.size, valeur.astype(np.float32))
        elif isinstance(valeur, bool):
            GL.glUniform1i(ou, int(valeur))
        elif isinstance(valeur, int):
            GL.glUniform1i(ou, valeur)
        elif isinstance(valeur, float):
            GL.glUniform1f(ou, valeur)
        elif isinstance(valeur, (tuple, list)):
            if len(valeur) == 2:
                GL.glUniform2f(ou, float(valeur[0]), float(valeur[1]))
            elif len(valeur) == 3:
                GL.glUniform3f(ou, *(float(v) for v in valeur))
            elif len(valeur) == 4:
                GL.glUniform4f(ou, *(float(v) for v in valeur))
            else:
                raise TypeError(f"uniforme {nom} : longueur {len(valeur)} inattendue")
        else:
            raise TypeError(f"uniforme {nom} : type {type(valeur)!r} non géré")

    def definir_tous(self, uniformes: dict) -> None:
        for nom, valeur in uniformes.items():
            self.definir(nom, valeur)

    def supprimer(self) -> None:
        if getattr(self, "id", 0):
            GL.glDeleteProgram(self.id)
            self.id = 0


# ---------------------------------------------------------------------------
# Cibles de rendu
# ---------------------------------------------------------------------------

class Cible:
    """Un tampon d'image hors écran, avec sa texture attachée."""

    def __init__(
        self, largeur: int, hauteur: int, format_interne=GL.GL_R16F, filtrage=None,
        mipmaps: bool = False,
    ):
        self.largeur, self.hauteur = largeur, hauteur
        self.format_interne = format_interne
        self.mipmaps = mipmaps
        if mipmaps:
            # Une pyramide de mipmaps EST un flou séparable déjà calculé par la
            # carte, et c'est le bon outil pour une tache de diffusion large.
            # L'échantillonner coûte une lecture ; l'approcher par une couronne
            # de huit points en coûte huit et laisse huit satellites — mesuré,
            # 973 % d'ondulation sur un cercle au rayon du voile.
            filtrage = GL.GL_LINEAR
        # Au plus proche par défaut : les boucles de filtrage visent des
        # centres de texel exacts. Les tampons de halo, eux, sont flous par
        # nature et agrandis à l'affichage : ils veulent du bilinéaire.
        filtrage = GL.GL_NEAREST if filtrage is None else filtrage

        self.texture = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        canal, type_donnees = _description(format_interne)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, format_interne, largeur, hauteur, 0,
            canal, type_donnees, None,
        )
        for parametre, valeur in (
            (GL.GL_TEXTURE_MIN_FILTER,
             GL.GL_LINEAR_MIPMAP_LINEAR if mipmaps else filtrage),
            (GL.GL_TEXTURE_MAG_FILTER, filtrage),
            (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE),
            (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE),
        ):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, parametre, valeur)

        self.fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glFramebufferTexture2D(
            GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, self.texture, 0
        )
        etat = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        if etat != GL.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError(f"tampon d'image incomplet : 0x{etat:x}")

    def activer(self) -> None:
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glViewport(0, 0, self.largeur, self.hauteur)

    def generer_mipmaps(self) -> None:
        """Reconstruit la pyramide après avoir écrit dans la cible."""
        if not self.mipmaps:
            return
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)

    def effacer(self) -> None:
        """Met la cible à zéro.

        `glTexImage2D` avec un pointeur nul ALLOUE la texture sans la définir :
        son contenu est ce que la carte avait laissé là. Sans importance pour
        une cible qu'on écrit entièrement à chaque image — sauf pour la charge
        du tube analyseur, qui se lit avant d'être écrite.
        """
        self.activer()
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

    def lier(self, unite: int) -> None:
        GL.glActiveTexture(GL.GL_TEXTURE0 + unite)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)

    def supprimer(self) -> None:
        if getattr(self, "fbo", 0):
            GL.glDeleteFramebuffers(1, [self.fbo])
            GL.glDeleteTextures(1, [self.texture])
            self.fbo = 0


def _description(format_interne):
    return {
        GL.GL_R16F: (GL.GL_RED, GL.GL_FLOAT),
        GL.GL_R32F: (GL.GL_RED, GL.GL_FLOAT),
        GL.GL_RG32F: (GL.GL_RG, GL.GL_FLOAT),
        GL.GL_RGBA16F: (GL.GL_RGBA, GL.GL_FLOAT),
        GL.GL_RGBA32F: (GL.GL_RGBA, GL.GL_FLOAT),
        GL.GL_RGBA8: (GL.GL_RGBA, GL.GL_UNSIGNED_BYTE),
    }[format_interne]


# ---------------------------------------------------------------------------
# Texture de source vidéo
# ---------------------------------------------------------------------------

class TextureImage:
    """Texture RGB alimentée image par image depuis un tableau numpy."""

    def __init__(self):
        self.id = GL.glGenTextures(1)
        self.largeur = self.hauteur = 0
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.id)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER,
                           GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)

    def televerser(self, image: np.ndarray) -> None:
        """Envoie une image (H, W, 3) en octets RGB.

        Les mipmaps sont indispensables : une vidéo 1080p échantillonnée sur
        une grille de 920 points sans réduction préalable produirait un
        crénelage qui n'a rien à voir avec la télévision analogique. Comme la
        boucle de filtrage garde un pas constant entre fragments voisins, le
        niveau de détail choisi automatiquement par le GPU est le bon.
        """
        hauteur, largeur = image.shape[:2]
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.id)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)

        if (largeur, hauteur) != (self.largeur, self.hauteur):
            GL.glTexImage2D(
                GL.GL_TEXTURE_2D, 0, GL.GL_RGB8, largeur, hauteur, 0,
                GL.GL_RGB, GL.GL_UNSIGNED_BYTE, image,
            )
            self.largeur, self.hauteur = largeur, hauteur
        else:
            GL.glTexSubImage2D(
                GL.GL_TEXTURE_2D, 0, 0, 0, largeur, hauteur,
                GL.GL_RGB, GL.GL_UNSIGNED_BYTE, image,
            )
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)

    def lier(self, unite: int) -> None:
        GL.glActiveTexture(GL.GL_TEXTURE0 + unite)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.id)

    def supprimer(self) -> None:
        if getattr(self, "id", 0):
            GL.glDeleteTextures(1, [self.id])
            self.id = 0


# ---------------------------------------------------------------------------
# Dessin
# ---------------------------------------------------------------------------

class Quad:
    """Le triangle plein écran. Aucun sommet transféré, mais un VAO obligatoire.

    Le profil « core » d'OpenGL refuse de dessiner sans objet de tableau de
    sommets lié, même quand le shader n'utilise aucun attribut et déduit tout
    de `gl_VertexID`. Ce VAO est donc vide, et ne sert qu'à satisfaire cette
    exigence.
    """

    def __init__(self):
        self.vao = GL.glGenVertexArrays(1)

    def dessiner(self) -> None:
        GL.glBindVertexArray(self.vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        GL.glBindVertexArray(0)

    def supprimer(self) -> None:
        if getattr(self, "vao", 0):
            GL.glDeleteVertexArrays(1, [self.vao])
            self.vao = 0
