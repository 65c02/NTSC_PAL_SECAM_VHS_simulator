"""
Construit la version HTML autonome du cours à partir de `cours.md`.

Le Markdown reste la source unique de vérité : cette page se régénère
entièrement à partir de lui. Les figures sont incorporées en data-URI, les
formules sont traduites en HTML par `maths_html`, et rien n'est chargé depuis
l'extérieur — la page fonctionne hors ligne et passe une politique de sécurité
stricte.

    python docs/construire_html.py [--sortie docs/cours.html]
"""

from __future__ import annotations

import argparse
import base64
import html
import mimetypes
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import maths_html  # noqa: E402

RACINE = Path(__file__).resolve().parent


# ===========================================================================
# Utilitaires
# ===========================================================================

def ancre(titre: str) -> str:
    """Identifiant de section, dans le même esprit que celui de GitHub."""
    texte = re.sub(r"[*`_\[\]()]", "", titre).strip().lower()
    texte = re.sub(r"[^\w\s\-·]", "", texte, flags=re.UNICODE)
    return re.sub(r"[\s·]+", "-", texte).strip("-")


def data_uri(chemin: Path) -> str:
    type_mime = mimetypes.guess_type(chemin.name)[0] or "image/png"
    donnees = base64.b64encode(chemin.read_bytes()).decode("ascii")
    return f"data:{type_mime};base64,{donnees}"


# ===========================================================================
# Conversion en ligne
# ===========================================================================

_JETON = "{}"


"""Marqueur de mise de côté, entouré de deux caractères de la zone à usage
privé d'Unicode (U+E000 et U+E001) — invisibles à la lecture de ce fichier.

Ils ne peuvent apparaître ni dans le Markdown source ni dans le HTML produit :
aucune collision n'est possible avec le texte réel, contrairement à ce qui
arriverait avec un marqueur composé de caractères ordinaires.
"""


def _en_ligne(texte: str, dossier: Path) -> str:
    """Gras, italique, code, liens, et formules insérées dans le texte."""
    reserves: list[str] = []

    def mettre_de_cote(rendu: str) -> str:
        reserves.append(rendu)
        return _JETON.format(len(reserves) - 1)

    # Le code et les formules sont mis à l'abri AVANT tout échappement, sinon
    # leurs caractères seraient interprétés comme du Markdown.
    texte = re.sub(
        r"`([^`]+)`",
        lambda m: mettre_de_cote(f"<code>{html.escape(m.group(1))}</code>"),
        texte,
    )
    texte = re.sub(
        r"(?<!\$)\$([^$\n]+?)\$(?!\$)",
        lambda m: mettre_de_cote(maths_html.en_ligne(m.group(1))),
        texte,
    )

    texte = html.escape(texte, quote=False)

    texte = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        texte,
    )
    texte = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", texte)
    texte = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", texte)

    # Le seul HTML brut toléré dans le Markdown : le saut de ligne, utile pour
    # aérer une cellule de tableau que Markdown ne sait pas découper.
    texte = texte.replace("&lt;br&gt;", "<br>").replace("&lt;br/&gt;", "<br>")

    for rang, rendu in enumerate(reserves):
        texte = texte.replace(_JETON.format(rang), rendu)
    return texte


# ===========================================================================
# Conversion des blocs
# ===========================================================================

class Convertisseur:
    def __init__(self, dossier: Path):
        self.dossier = dossier
        self.sections: list[tuple[int, str, str]] = []   # (niveau, titre, ancre)
        self.figures = 0

    # -- blocs ------------------------------------------------------------

    def convertir(self, markdown: str) -> str:
        lignes = markdown.replace("\r\n", "\n").split("\n")
        sortie: list[str] = []
        i = 0
        n = len(lignes)

        while i < n:
            ligne = lignes[i]
            depouillee = ligne.strip()

            if not depouillee:
                i += 1
                continue

            if depouillee.startswith("```"):
                i = self._code(lignes, i, sortie)
                continue

            if depouillee.startswith("$$"):
                i = self._formule(lignes, i, sortie)
                continue

            if re.fullmatch(r"-{3,}|_{3,}|\*{3,}", depouillee):
                sortie.append('<hr class="separateur">')
                i += 1
                continue

            if depouillee.startswith("#"):
                i = self._titre(lignes, i, sortie)
                continue

            if depouillee.startswith("|") and i + 1 < n and re.match(
                r"^\s*\|[\s:|-]+\|\s*$", lignes[i + 1]
            ):
                i = self._tableau(lignes, i, sortie)
                continue

            if depouillee.startswith(">"):
                i = self._citation(lignes, i, sortie)
                continue

            if re.match(r"^\s*[-*+]\s+", ligne):
                i = self._liste(lignes, i, sortie, ordonnee=False)
                continue

            if re.match(r"^\s*\d+\.\s+", ligne):
                i = self._liste(lignes, i, sortie, ordonnee=True)
                continue

            if re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", depouillee):
                i = self._figure(depouillee, i, sortie)
                continue

            i = self._paragraphe(lignes, i, sortie)

        return "\n".join(sortie)

    # -- éléments ---------------------------------------------------------

    def _titre(self, lignes, i, sortie):
        trouve = re.match(r"^(#{1,6})\s+(.*)$", lignes[i].strip())
        niveau, texte = len(trouve.group(1)), trouve.group(2).strip()
        identifiant = ancre(texte)
        if niveau <= 3:
            self.sections.append((niveau, texte, identifiant))
        sortie.append(
            f'<h{niveau} id="{identifiant}">{_en_ligne(texte, self.dossier)}</h{niveau}>'
        )
        return i + 1

    def _paragraphe(self, lignes, i, sortie):
        bloc = []
        while i < len(lignes) and lignes[i].strip() and not re.match(
            r"^\s*(#|>|```|\$\$|\||[-*+]\s|\d+\.\s|-{3,}$)", lignes[i]
        ):
            bloc.append(lignes[i].strip())
            i += 1
        if bloc:
            sortie.append(f"<p>{_en_ligne(' '.join(bloc), self.dossier)}</p>")
        return i

    def _code(self, lignes, i, sortie):
        langue = lignes[i].strip()[3:].strip()
        i += 1
        corps = []
        while i < len(lignes) and not lignes[i].strip().startswith("```"):
            corps.append(lignes[i])
            i += 1
        classe = f' class="langue-{langue}"' if langue else ""
        sortie.append(
            f'<pre class="bloc-code"><code{classe}>'
            f"{html.escape(chr(10).join(corps))}</code></pre>"
        )
        return i + 1

    def _formule(self, lignes, i, sortie):
        premiere = lignes[i].strip()
        if premiere.endswith("$$") and len(premiere) > 4:
            sortie.append(maths_html.bloc(premiere[2:-2]))
            return i + 1

        corps = []
        # Ce qui suit le `$$` ouvrant appartient à la formule. L'oublier
        # faisait disparaître la PREMIÈRE LIGNE de toute formule écrite sur
        # plusieurs lignes — huit d'entre elles dans ce cours, dont le membre
        # de gauche de la séparation Y/C au chapitre 10. Le Markdown restait
        # juste, seule la page HTML mentait, et rien ne le signalait.
        debut = premiere[2:].strip()
        if debut:
            corps.append(debut)
        i += 1
        while i < len(lignes) and not lignes[i].strip().endswith("$$"):
            corps.append(lignes[i])
            i += 1
        if i < len(lignes):
            derniere = lignes[i].strip()[:-2]
            if derniere:
                corps.append(derniere)
        sortie.append(maths_html.bloc("\n".join(corps)))
        return i + 1

    def _tableau(self, lignes, i, sortie):
        def cellules(ligne):
            return [c.strip() for c in ligne.strip().strip("|").split("|")]

        entete = cellules(lignes[i])
        i += 2
        corps = []
        while i < len(lignes) and lignes[i].strip().startswith("|"):
            corps.append(cellules(lignes[i]))
            i += 1

        html_entete = "".join(
            f"<th>{_en_ligne(c, self.dossier)}</th>" for c in entete
        )
        html_corps = "".join(
            "<tr>"
            + "".join(f"<td>{_en_ligne(c, self.dossier)}</td>" for c in rang)
            + "</tr>"
            for rang in corps
        )
        sortie.append(
            f'<div class="cadre-tableau"><table><thead><tr>{html_entete}</tr></thead>'
            f"<tbody>{html_corps}</tbody></table></div>"
        )
        return i

    def _citation(self, lignes, i, sortie):
        corps = []
        while i < len(lignes) and lignes[i].strip().startswith(">"):
            corps.append(re.sub(r"^\s*>\s?", "", lignes[i]))
            i += 1
        interieur = self.convertir("\n".join(corps))

        # Deux encarts ont un sens particulier dans ce cours et méritent leur
        # propre traitement : celui qui renvoie au code, et celui qui nomme le
        # test qui vérifie l'affirmation.
        texte = "\n".join(corps)
        if re.match(r"\s*\*\*Dans le code\*\*", texte):
            classe, etiquette = "encart-code", "Dans le code"
        elif re.match(r"\s*\*\*Vérifié par\*\*", texte):
            classe, etiquette = "encart-test", "Vérifié par"
        else:
            classe, etiquette = "encart-note", None

        if etiquette:
            interieur = interieur.replace(
                f"<strong>{etiquette}</strong> — ", "", 1
            )
            entete = f'<span class="encart-titre">{etiquette}</span>'
        else:
            entete = ""
        sortie.append(f'<aside class="{classe}">{entete}{interieur}</aside>')
        return i

    def _liste(self, lignes, i, sortie, ordonnee):
        motif = r"^\s*\d+\.\s+" if ordonnee else r"^\s*[-*+]\s+"
        elements = []
        while i < len(lignes):
            if re.match(motif, lignes[i]):
                elements.append(re.sub(motif, "", lignes[i]).strip())
                i += 1
            elif lignes[i].strip() and lignes[i].startswith(("  ", "\t")) and elements:
                elements[-1] += " " + lignes[i].strip()
                i += 1
            else:
                break
        balise = "ol" if ordonnee else "ul"
        contenu = "".join(
            f"<li>{_en_ligne(element, self.dossier)}</li>" for element in elements
        )
        sortie.append(f"<{balise}>{contenu}</{balise}>")
        return i

    def _figure(self, ligne, i, sortie):
        trouve = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", ligne)
        legende, source = trouve.group(1), trouve.group(2)
        chemin = (self.dossier / source).resolve()
        if not chemin.exists():
            sortie.append(f'<p class="manquant">Figure absente : {html.escape(source)}</p>')
            return i + 1
        self.figures += 1
        sortie.append(
            f'<figure><img src="{data_uri(chemin)}" alt="{html.escape(legende, quote=True)}">'
            f"<figcaption>{_en_ligne(legende, self.dossier)}</figcaption></figure>"
        )
        return i + 1


# ===========================================================================
# Feuille de style
# ===========================================================================

STYLE = """
/* ------------------------------------------------------------------
   Palette. Le fond clair est un papier légèrement biaisé vers le cyan
   du phosphore ; le fond sombre est l'écran d'un instrument de mesure.
   L'accent est la couleur d'une trace d'oscilloscope, l'alerte l'ambre
   des mires de réglage.
   ------------------------------------------------------------------ */
:root {
  --fond:        #F1F4F4;
  --surface:     #FFFFFF;
  --surface-2:   #E7ECEC;
  --encre:       #101719;
  --encre-douce: #4C5D61;
  --trait:       #CBD6D6;
  --trait-fin:   #DFE7E7;
  --accent:      #0C737B;
  --accent-vif:  #0A5D64;
  --accent-fond: #E2F0F1;
  --alerte:      #9C4B18;
  --alerte-fond: #F7EBE1;

  --barre-blanc:   #BFBFBF;
  --barre-jaune:   #BFBF00;
  --barre-cyan:    #00BFBF;
  --barre-vert:    #00BF00;
  --barre-magenta: #BF00BF;
  --barre-rouge:   #BF0000;
  --barre-bleu:    #0000BF;

  --titre: "Franklin Gothic Medium", "Franklin Gothic", "Liberation Sans Narrow",
           "Helvetica Neue", Arial, sans-serif;
  --texte: Cambria, "Palatino Linotype", "Book Antiqua", Palatino, Georgia, serif;
  --machine: Consolas, "SFMono-Regular", "DejaVu Sans Mono", Menlo, monospace;

  --colonne: 63ch;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --fond:        #0A0E10;
    --surface:     #121A1D;
    --surface-2:   #192327;
    --encre:       #DBE6E7;
    --encre-douce: #8AA0A5;
    --trait:       #253238;
    --trait-fin:   #1B262A;
    --accent:      #3ED2C2;
    --accent-vif:  #6BE6D9;
    --accent-fond: #0F2E32;
    --alerte:      #E0993F;
    --alerte-fond: #2C2113;
  }
}

:root[data-theme="dark"] {
  --fond:        #0A0E10;
  --surface:     #121A1D;
  --surface-2:   #192327;
  --encre:       #DBE6E7;
  --encre-douce: #8AA0A5;
  --trait:       #253238;
  --trait-fin:   #1B262A;
  --accent:      #3ED2C2;
  --accent-vif:  #6BE6D9;
  --accent-fond: #0F2E32;
  --alerte:      #E0993F;
  --alerte-fond: #2C2113;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--fond);
  color: var(--encre);
  font-family: var(--texte);
  font-size: 17px;
  line-height: 1.62;
  -webkit-font-smoothing: antialiased;
}

/* ---------------------------------------------------------------- hero */

.bandeau {
  position: relative;
  overflow: hidden;
  background: var(--surface);
  border-bottom: 1px solid var(--trait);
}

/* Trame de balayage : une ligne sur deux, très légèrement plus sombre.
   C'est le motif du sujet lui-même. */
.bandeau::before {
  content: "";
  position: absolute;
  inset: 0;
  /* Un rgba littéral plutôt qu'un color-mix : la trame doit apparaître
     partout, y compris dans les moteurs de rendu un peu anciens, et un noir
     à 4 % fonctionne aussi bien sur fond clair que sur fond sombre. */
  background: repeating-linear-gradient(
    to bottom,
    rgba(0, 0, 0, 0.045) 0 1px,
    transparent 1px 4px
  );
  pointer-events: none;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .bandeau::before {
    background: repeating-linear-gradient(
      to bottom,
      rgba(255, 255, 255, 0.035) 0 1px,
      transparent 1px 4px
    );
  }
}
:root[data-theme="dark"] .bandeau::before {
  background: repeating-linear-gradient(
    to bottom,
    rgba(255, 255, 255, 0.035) 0 1px,
    transparent 1px 4px
  );
}

.bandeau-interieur {
  position: relative;
  max-width: 1160px;
  margin: 0 auto;
  padding: 4.5rem 1.5rem 0;
}

.eyebrow {
  font-family: var(--titre);
  font-size: 0.78rem;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--accent);
  margin: 0 0 1.1rem;
}

h1 {
  font-family: var(--titre);
  font-size: clamp(2.6rem, 6.5vw, 4.6rem);
  line-height: 0.98;
  letter-spacing: -0.015em;
  margin: 0;
  text-wrap: balance;
}

.sous-titre {
  font-size: clamp(1.05rem, 2.2vw, 1.32rem);
  color: var(--encre-douce);
  max-width: 46ch;
  margin: 1.1rem 0 2.2rem;
  font-style: italic;
}

.mire {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  height: 26px;
  max-width: 640px;
  margin-bottom: 2.4rem;
}
.mire span { display: block; }

.chiffres {
  display: flex;
  flex-wrap: wrap;
  padding-bottom: 3rem;
  font-family: var(--machine);
  font-size: 0.76rem;
  line-height: 1.45;
  color: var(--encre-douce);
  font-variant-numeric: tabular-nums;
}
.chiffres div {
  /* Une largeur plancher, sans quoi chaque bloc se dimensionne sur son
     nombre et les légendes, plus longues, se chevauchent. */
  min-width: 12rem;
  flex: 0 1 auto;
  border-top: 2px solid var(--accent);
  padding-top: 0.6rem;
  margin: 0 3rem 1.4rem 0;
}
.chiffres b {
  display: block;
  font-family: var(--titre);
  font-size: 1.55rem;
  color: var(--encre);
  font-weight: 500;
  letter-spacing: -0.01em;
  margin-bottom: 0.15rem;
}

/* ------------------------------------------------------------- ossature */

.page {
  max-width: 1160px;
  margin: 0 auto;
  padding: 0 1.5rem 6rem;
  display: grid;
  grid-template-columns: 230px minmax(0, 1fr);
  gap: 3.5rem;
  align-items: start;
}

.sommaire {
  position: sticky;
  top: 1.5rem;
  padding-top: 3rem;
  max-height: calc(100vh - 3rem);
  overflow-y: auto;
  font-family: var(--titre);
  font-size: 0.84rem;
  line-height: 1.42;
}
.sommaire h2 {
  font-size: 0.72rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--encre-douce);
  margin: 0 0 1rem;
  border: 0;
  padding: 0;
}
.sommaire ol { list-style: none; margin: 0; padding: 0; counter-reset: chapitre; }
.sommaire li { margin: 0 0 0.55rem; }
/* On espace à la marge plutôt qu'avec `gap` : le `gap` sur conteneur flex
   n'est pas universellement disponible, et une espace manquante entre le
   numéro et le titre saute aux yeux. */
.sommaire a {
  color: var(--encre-douce);
  text-decoration: none;
  display: flex;
  border-left: 2px solid transparent;
  padding-left: 0.7rem;
  margin-left: -0.7rem;
}
.sommaire a:hover { color: var(--accent); border-left-color: var(--accent); }
.sommaire .num {
  font-variant-numeric: tabular-nums;
  color: var(--accent);
  opacity: 0.8;
  min-width: 1.7em;
  flex: 0 0 auto;
  text-align: right;
  padding-right: 0.62rem;
}

.contenu {
  display: grid;
  grid-template-columns:
    [large-g] minmax(0, 1fr)
    [texte-g] min(var(--colonne), 100%) [texte-d]
    minmax(0, 1fr) [large-d];
  padding-top: 3rem;
}
.contenu > * { grid-column: texte-g / texte-d; min-width: 0; }
.contenu > figure,
.contenu > .cadre-tableau { grid-column: large-g / large-d; }

/* ------------------------------------------------------------ typographie */

h2, h3, h4 {
  font-family: var(--titre);
  line-height: 1.14;
  letter-spacing: -0.01em;
  text-wrap: balance;
}
h2 {
  font-size: 1.92rem;
  margin: 4.4rem 0 1.2rem;
  padding-top: 1.5rem;
  border-top: 3px solid var(--encre);
}
h3 { font-size: 1.24rem; margin: 2.9rem 0 0.7rem; }
h4 { font-size: 1.02rem; margin: 2rem 0 0.5rem; color: var(--encre-douce); }

p { margin: 0 0 1.15rem; }
strong { font-weight: 700; }
a { color: var(--accent-vif); text-decoration-thickness: 1px; text-underline-offset: 2px; }
a:focus-visible, .sommaire a:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
}

ul, ol { margin: 0 0 1.3rem; padding-left: 1.35rem; }
li { margin-bottom: 0.42rem; }
li::marker { color: var(--accent); }

hr.separateur {
  grid-column: large-g / large-d;
  border: 0;
  height: 1px;
  background: var(--trait);
  margin: 3.4rem 0;
}

code {
  font-family: var(--machine);
  font-size: 0.85em;
  background: var(--surface-2);
  padding: 0.1em 0.36em;
  border-radius: 3px;
}

.bloc-code {
  grid-column: texte-g / texte-d;
  background: var(--surface);
  border: 1px solid var(--trait);
  border-left: 3px solid var(--accent);
  padding: 1rem 1.15rem;
  overflow-x: auto;
  font-size: 0.82rem;
  line-height: 1.55;
  margin: 0 0 1.6rem;
}
.bloc-code code { background: none; padding: 0; font-size: inherit; }

/* ---------------------------------------------------------------- encarts */

aside {
  margin: 1.6rem 0 1.8rem;
  padding: 0.95rem 1.15rem;
  font-size: 0.93rem;
  border-radius: 2px;
}
aside p:last-child { margin-bottom: 0; }
aside p { margin-bottom: 0.6rem; }

.encart-note {
  background: var(--surface);
  border-left: 3px solid var(--encre-douce);
  font-style: italic;
}
.encart-code { background: var(--accent-fond); border-left: 3px solid var(--accent); }
.encart-test { background: var(--alerte-fond); border-left: 3px solid var(--alerte); }

.encart-titre {
  display: block;
  font-family: var(--titre);
  font-size: 0.7rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  margin-bottom: 0.4rem;
}
.encart-code .encart-titre { color: var(--accent); }
.encart-test .encart-titre { color: var(--alerte); }

.encart-code code, .encart-test code { background: transparent; padding: 0; }

/* ---------------------------------------------------------------- figures */

figure {
  margin: 2.6rem 0 2.8rem;
  background: var(--surface);
  border: 1px solid var(--trait);
  padding: 0.85rem;
}
figure img {
  display: block;
  width: 100%;
  height: auto;
  background: #fff;
}
figcaption {
  font-family: var(--titre);
  font-size: 0.8rem;
  line-height: 1.4;
  color: var(--encre-douce);
  padding-top: 0.75rem;
  border-top: 1px solid var(--trait-fin);
  margin-top: 0.75rem;
}

/* --------------------------------------------------------------- tableaux */

.cadre-tableau { overflow-x: auto; margin: 1.8rem 0 2.2rem; }
table {
  border-collapse: collapse;
  width: 100%;
  font-size: 0.87rem;
  font-variant-numeric: tabular-nums;
  font-family: var(--titre);
}
th, td {
  text-align: left;
  padding: 0.5rem 0.85rem;
  border-bottom: 1px solid var(--trait-fin);
  vertical-align: top;
}
thead th {
  border-bottom: 2px solid var(--encre);
  font-size: 0.73rem;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  color: var(--encre-douce);
}
/* Une formule n'a pas de casse : passer γ en majuscules le change en Γ,
   c'est-à-dire en une autre grandeur. */
thead th .formule-ligne, thead th code { text-transform: none; letter-spacing: 0; }
tbody tr:hover { background: var(--surface); }
td code { font-size: 0.9em; }

/* --------------------------------------------------------------- formules */

.formule {
  grid-column: texte-g / texte-d;
  margin: 1.7rem 0;
  padding: 1.1rem 1.2rem;
  background: var(--surface);
  border: 1px solid var(--trait);
  border-left: 3px solid var(--accent);
  overflow-x: auto;
  text-align: center;
  font-family: var(--machine);
  font-size: 1.02rem;
  line-height: 2.1;
}
.formule-ligne {
  font-family: var(--machine);
  font-size: 0.94em;
  white-space: nowrap;
}
.grec, .sym, .op { font-family: var(--texte); font-style: normal; }
.mot { font-family: var(--titre); font-size: 0.88em; padding: 0 0.15em; }
.delim { font-size: 1.15em; }

.frac {
  display: inline-flex;
  flex-direction: column;
  vertical-align: middle;
  text-align: center;
  margin: 0 0.28em;
  line-height: 1.25;
  font-size: 0.94em;
}
.frac .num { border-bottom: 1px solid currentColor; padding: 0 0.35em 0.1em; }
.frac .den { padding: 0.1em 0.35em 0; }

.rac { white-space: nowrap; }
.rac .sous-rac { border-top: 1px solid currentColor; padding: 0 0.15em; }
.surligne { border-top: 1px solid currentColor; padding-top: 0.05em; }

.encadre {
  display: inline-block;
  border: 2px solid var(--accent);
  padding: 0.35em 0.75em;
  border-radius: 2px;
}

.matrice { display: inline-flex; align-items: stretch; vertical-align: middle; margin: 0 0.2em; }
.matrice .m-p {
  font-size: 2.4em;
  line-height: 1;
  display: flex;
  align-items: center;
  font-family: var(--texte);
  color: var(--encre-douce);
}
.matrice .m-g {
  display: grid;
  grid-template-columns: repeat(var(--colonnes), auto);
  gap: 0.15em 1.05em;
  padding: 0.35em 0.4em;
  line-height: 1.45;
}
.matrice .m-c { text-align: right; }

.aligne {
  display: inline-grid;
  grid-template-columns: auto auto;
  gap: 0.25em 0.45em;
  text-align: left;
  line-height: 1.75;
}
.aligne .a-g { text-align: right; }
.aligne .a-d { text-align: left; }

.accolade { display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; }
.accolade .acc-c { border-bottom: 1px solid var(--encre-douce); padding-bottom: 0.1em; }
.accolade .acc-e { font-size: 0.75em; color: var(--encre-douce); }

.macro-inconnue { color: var(--alerte); font-weight: bold; }
.manquant { color: var(--alerte); font-family: var(--machine); font-size: 0.85rem; }

/* -------------------------------------------------------------- pied bas */

.pied {
  border-top: 1px solid var(--trait);
  margin-top: 5rem;
  padding: 2rem 1.5rem 3rem;
  max-width: 1160px;
  margin-inline: auto;
  font-family: var(--titre);
  font-size: 0.8rem;
  color: var(--encre-douce);
  display: flex;
  flex-wrap: wrap;
}
.pied span { margin: 0 2.5rem 0.8rem 0; }

/* ------------------------------------------------------------- adaptatif */

@media (max-width: 950px) {
  .page { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .sommaire {
    position: static;
    max-height: none;
    padding: 2.4rem 0 0;
    border-bottom: 1px solid var(--trait);
    padding-bottom: 1.6rem;
  }
  .sommaire ol { columns: 2; column-gap: 1.6rem; }
  .contenu { padding-top: 2rem; }
  h2 { margin-top: 3.2rem; }
}

@media (max-width: 600px) {
  body { font-size: 16px; }
  .bandeau-interieur { padding-top: 3rem; }
  .sommaire ol { columns: 1; }
  .chiffres { gap: 0 1.6rem; }
  .formule { font-size: 0.92rem; padding: 0.9rem; }
}

@media print {
  .sommaire, .pied { display: none; }
  .page { display: block; }
  figure, .formule, aside { break-inside: avoid; }
}

@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
"""


# ===========================================================================
# Assemblage
# ===========================================================================

BARRES = [
    "--barre-blanc", "--barre-jaune", "--barre-cyan", "--barre-vert",
    "--barre-magenta", "--barre-rouge", "--barre-bleu",
]


def sommaire_html(sections) -> str:
    elements = []
    for niveau, titre, identifiant in sections:
        if niveau != 2:
            continue
        trouve = re.match(r"^(\d+)\.\s*(.*)$", titre)
        if trouve:
            numero, libelle = trouve.group(1), trouve.group(2)
        elif titre.startswith("Annexes") or titre.startswith("Le simulateur"):
            numero, libelle = "", titre
        else:
            numero, libelle = "", titre
        elements.append(
            f'<li><a href="#{identifiant}">'
            f'<span class="num">{numero}</span><span>{html.escape(libelle)}</span>'
            f"</a></li>"
        )
    return "<ol>" + "".join(elements) + "</ol>"


def construire(chemin_markdown: Path, sortie: Path) -> Path:
    markdown = chemin_markdown.read_text(encoding="utf-8")

    # On retire le titre, le chapeau et la table des matières du Markdown :
    # la page HTML leur donne son propre traitement.
    corps = markdown
    marque = "\n---\n"
    debut = corps.find("## 1. Le problème de 1953")
    if debut > 0:
        corps = corps[debut:]

    convertisseur = Convertisseur(chemin_markdown.parent)
    contenu = convertisseur.convertir(corps)

    inconnues = maths_html.macros_inconnues()
    if inconnues:
        print("  [!] macros LaTeX non traduites :", ", ".join(sorted(inconnues)))

    barres = "".join(
        f'<span style="background:var({nom})"></span>' for nom in BARRES
    )

    page = f"""<title>NTSC · PAL · SECAM</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{STYLE}</style>

<header class="bandeau">
  <div class="bandeau-interieur">
    <p class="eyebrow">Cours · télévision analogique</p>
    <h1>Le codage couleur<br>de la télévision analogique</h1>
    <p class="sous-titre">La théorie, les mathématiques, et ce que tout cela fait
    à vos pixels. Toutes les figures sont des sorties réelles du simulateur qui
    accompagne ce cours&nbsp;: aucune n'a été dessinée à la main.</p>
    <div class="mire" role="img" aria-label="Mire de barres de couleur">{barres}</div>
    <div class="chiffres">
      <div><b>3,579&nbsp;545</b>MHz · sous-porteuse NTSC</div>
      <div><b>4,433&nbsp;619</b>MHz · sous-porteuse PAL</div>
      <div><b>4,250 / 4,406</b>MHz · sous-porteuses SECAM</div>
      <div><b>58</b>propriétés vérifiées par test</div>
    </div>
  </div>
</header>

<div class="page">
  <nav class="sommaire" aria-label="Sommaire">
    <h2>Sommaire</h2>
    {sommaire_html(convertisseur.sections)}
  </nav>
  <article class="contenu">
{contenu}
  </article>
</div>

<footer class="pied">
  <span>Simulateur et cours — NTSC · PAL · SECAM</span>
  <span>{convertisseur.figures} figures produites par la simulation</span>
  <span>Sources&nbsp;: UIT-R BT.470-6, BT.601-7, SMPTE 170M, EBU Tech. 3213</span>
</footer>
"""
    sortie.write_text(page, encoding="utf-8")
    return sortie


def principal(argv=None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--source", default=str(RACINE / "cours.md"))
    analyseur.add_argument("--sortie", default=str(RACINE / "cours.html"))
    arguments = analyseur.parse_args(argv)

    chemin = construire(Path(arguments.source), Path(arguments.sortie))
    taille = chemin.stat().st_size / 1e6
    print(f"  écrit : {chemin}  ({taille:.2f} Mo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
