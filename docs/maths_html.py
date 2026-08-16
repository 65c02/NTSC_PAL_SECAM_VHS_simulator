"""
Rendu des formules LaTeX en HTML autonome.

Une page publiée en Artifact ne peut charger aucune ressource extérieure :
MathJax et KaTeX sont hors de portée. Plutôt que de renoncer aux formules ou
de les transformer en images, on les traduit en HTML et en Unicode.

Le sous-ensemble couvert est exactement celui qu'emploie `cours.md` :
fractions, matrices, alignements, racines, indices, exposants, lettres
grecques et les quelques macros d'espacement. Toute macro inconnue est
signalée plutôt que silencieusement ignorée — un `?` dans une formule se
remarque, une macro avalée en silence, non.
"""

from __future__ import annotations

import re

GRECQUES = {
    "alpha": "α", "beta": "β", "gamma": "γ", "Gamma": "Γ", "delta": "δ",
    "Delta": "Δ", "epsilon": "ε", "varepsilon": "ε", "theta": "θ",
    "Theta": "Θ", "lambda": "λ", "Lambda": "Λ", "mu": "μ", "nu": "ν",
    "pi": "π", "Pi": "Π", "rho": "ρ", "sigma": "σ", "Sigma": "Σ",
    "tau": "τ", "phi": "φ", "varphi": "φ", "Phi": "Φ", "psi": "ψ",
    "omega": "ω", "Omega": "Ω",
}

SYMBOLES = {
    "cdot": "·", "times": "×", "div": "÷", "pm": "±", "mp": "∓",
    "approx": "≈", "equiv": "≡", "neq": "≠", "leq": "≤", "geq": "≥",
    "to": "→", "rightarrow": "→", "longrightarrow": "⟶", "Rightarrow": "⟹",
    "leftarrow": "←", "longleftarrow": "⟵",
    "in": "∈", "infty": "∞", "propto": "∝", "ldots": "…", "dots": "…",
    "partial": "∂", "circ": "∘", "ast": "∗", "sim": "∼",
    # Délimiteurs « écrits en toutes lettres » de LaTeX. `\lvert` et `\rvert`
    # ne diffèrent de la barre verticale que par l'espacement typographique,
    # que l'on ne cherche pas à reproduire ; les crochets de partie entière,
    # eux, ont bien leurs propres caractères.
    "lvert": "|", "rvert": "|", "lVert": "‖", "rVert": "‖",
    "lceil": "⌈", "rceil": "⌉", "lfloor": "⌊", "rfloor": "⌋",
    "langle": "⟨", "rangle": "⟩",
}

OPERATEURS = {
    "sin": "sin", "cos": "cos", "tan": "tan", "log": "log", "ln": "ln",
    "exp": "exp", "max": "max", "min": "min", "sum": "Σ", "int": "∫",
    "arg": "arg", "det": "det", "lim": "lim",
    "sqrt": None,   # traité à part
}

ESPACES = {
    ",": "\u2009", ";": "\u2005", ":": "\u2005", "!": "", " ": " ",
    "quad": "\u2003", "qquad": "\u2003\u2003",
}

_INCONNUES: set[str] = set()

# Marqueurs de mise de cote, en zone a usage privee d'Unicode. Ils traversent
# la boucle d'echappement sans etre alteres et ne peuvent pas apparaitre dans
# une formule reelle.
_MARQUE_DEBUT = ""
_MARQUE_FIN = ""


def macros_inconnues() -> set[str]:
    """Macros rencontrées et non traduites, pour contrôle après conversion."""
    return set(_INCONNUES)


# ---------------------------------------------------------------------------
# Lecture d'un groupe { ... } en respectant l'imbrication
# ---------------------------------------------------------------------------

def _groupe(source: str, position: int) -> tuple[str, int]:
    """Lit le groupe accolé commençant à `position`. Retourne (contenu, suite)."""
    if position >= len(source):
        return "", position

    if source[position] == "\\":
        # Argument réduit à une macro, sans accolades : `x^\gamma`. Sans ce
        # cas, on ne prendrait que la barre oblique comme exposant et le nom
        # de la macro s'afficherait en toutes lettres dans le corps du texte.
        nom = re.match(r"\\[A-Za-z]+", source[position:])
        if nom:
            return nom.group(0), position + len(nom.group(0))

    if source[position] != "{":
        # Argument d'un seul caractère, comme x^2.
        return source[position], position + 1
    profondeur, debut = 0, position
    for i in range(position, len(source)):
        if source[i] == "{" and (i == 0 or source[i - 1] != "\\"):
            profondeur += 1
        elif source[i] == "}" and source[i - 1] != "\\":
            profondeur -= 1
            if profondeur == 0:
                return source[debut + 1 : i], i + 1
    return source[debut + 1 :], len(source)


# ---------------------------------------------------------------------------
# Environnements
# ---------------------------------------------------------------------------

def _decouper_lignes(corps: str) -> list[str]:
    return [ligne.strip() for ligne in re.split(r"\\\\", corps) if ligne.strip()]


def _matrice(corps: str, ouvrant: str, fermant: str) -> str:
    lignes = _decouper_lignes(corps)
    colonnes = max(len(ligne.split("&")) for ligne in lignes)
    cellules = []
    for ligne in lignes:
        cases = [c.strip() for c in ligne.split("&")]
        cases += [""] * (colonnes - len(cases))
        cellules.extend(f'<span class="m-c">{convertir(c)}</span>' for c in cases)
    return (
        f'<span class="matrice"><span class="m-p">{ouvrant}</span>'
        f'<span class="m-g" style="--colonnes:{colonnes}">{"".join(cellules)}</span>'
        f'<span class="m-p">{fermant}</span></span>'
    )


def _aligne(corps: str) -> str:
    lignes = _decouper_lignes(corps)
    cellules = []
    for ligne in lignes:
        cases = ligne.split("&", 1)
        gauche = convertir(cases[0].strip())
        droite = convertir(cases[1].strip()) if len(cases) > 1 else ""
        cellules.append(f'<span class="a-g">{gauche}</span><span class="a-d">{droite}</span>')
    return f'<span class="aligne">{"".join(cellules)}</span>'


_ENVIRONNEMENTS = {
    "pmatrix": lambda corps: _matrice(corps, "(", ")"),
    "bmatrix": lambda corps: _matrice(corps, "[", "]"),
    "matrix": lambda corps: _matrice(corps, "", ""),
    "aligned": _aligne,
    "align": _aligne,
    "cases": lambda corps: _matrice(corps, "{", ""),
}


def _extraire_environnements(source: str, garder) -> str:
    """Traite \\begin{...}...\\end{...} en partant du plus imbriqué.

    Le HTML produit n'est pas réinjecté tel quel dans la chaîne : il est mis
    de côté et remplacé par un marqueur. Sinon la boucle de conversion qui
    suit, qui échappe consciencieusement `<` et `>`, transformerait le rendu
    en son propre code source affiché à l'écran.
    """
    motif = re.compile(r"\\begin\{(\w+)\}(.*?)\\end\{\1\}", re.DOTALL)
    while True:
        trouve = motif.search(source)
        if trouve is None:
            return source
        nom, corps = trouve.group(1), trouve.group(2)
        rendu = _ENVIRONNEMENTS.get(nom)
        if rendu is None:
            _INCONNUES.add(f"environnement {nom}")
            remplacement = convertir(corps)
        else:
            remplacement = rendu(corps)
        source = source[: trouve.start()] + garder(remplacement) + source[trouve.end() :]


# ---------------------------------------------------------------------------
# Conversion principale
# ---------------------------------------------------------------------------

def convertir(formule: str) -> str:
    """Traduit une formule LaTeX en HTML autonome."""
    reserves: list[str] = []

    def garder(rendu: str) -> str:
        reserves.append(rendu)
        # Marqueur en zone à usage privé d'Unicode : traversera la boucle
        # d'échappement sans être altéré, et ne peut pas apparaître dans une
        # formule réelle.
        return f"{_MARQUE_DEBUT}{len(reserves) - 1}{_MARQUE_FIN}"

    source = _extraire_environnements(formule.strip(), garder)
    sortie: list[str] = []
    i = 0
    n = len(source)

    while i < n:
        caractere = source[i]

        if caractere == "\\":
            i = _macro(source, i, sortie)
            continue

        if caractere == "^":
            contenu, i = _groupe(source, i + 1)
            sortie.append(f"<sup>{convertir(contenu)}</sup>")
            continue

        if caractere == "_":
            contenu, i = _groupe(source, i + 1)
            sortie.append(f"<sub>{convertir(contenu)}</sub>")
            continue

        if caractere == "{":
            contenu, i = _groupe(source, i)
            sortie.append(convertir(contenu))
            continue

        if caractere == "&":
            i += 1
            continue

        if caractere == "<":
            sortie.append("&lt;")
        elif caractere == ">":
            sortie.append("&gt;")
        else:
            sortie.append(caractere)
        i += 1

    resultat = "".join(sortie)
    for rang, rendu in enumerate(reserves):
        resultat = resultat.replace(f"{_MARQUE_DEBUT}{rang}{_MARQUE_FIN}", rendu)
    return resultat


def _macro(source: str, i: int, sortie: list[str]) -> int:
    """Traite une macro commençant au backslash d'indice `i`. Retourne la suite."""
    reste = source[i + 1 :]

    # Espacements et retours à la ligne, dont le nom n'est pas alphabétique.
    if reste[:2] == "\\\\" or reste[:1] == "\\":
        sortie.append("<br>")
        return i + 2
    if reste[:1] in ESPACES and not reste[:1].isalpha():
        sortie.append(ESPACES[reste[:1]])
        return i + 2

    trouve = re.match(r"[A-Za-z]+", reste)
    if trouve is None:
        sortie.append(reste[:1])
        return i + 2

    nom = trouve.group(0)
    suite = i + 1 + len(nom)

    if nom == "frac" or nom == "dfrac" or nom == "tfrac":
        numerateur, suite = _groupe(source, suite)
        denominateur, suite = _groupe(source, suite)
        sortie.append(
            f'<span class="frac"><span class="num">{convertir(numerateur)}</span>'
            f'<span class="den">{convertir(denominateur)}</span></span>'
        )
        return suite

    if nom == "sqrt":
        contenu, suite = _groupe(source, suite)
        sortie.append(f'<span class="rac">√<span class="sous-rac">{convertir(contenu)}</span></span>')
        return suite

    if nom == "boxed":
        contenu, suite = _groupe(source, suite)
        sortie.append(f'<span class="encadre">{convertir(contenu)}</span>')
        return suite

    if nom in ("bar", "overline"):
        contenu, suite = _groupe(source, suite)
        sortie.append(f'<span class="surligne">{convertir(contenu)}</span>')
        return suite

    if nom in ("mathbf", "boldsymbol", "textbf"):
        contenu, suite = _groupe(source, suite)
        sortie.append(f"<b>{convertir(contenu)}</b>")
        return suite

    if nom in ("text", "operatorname", "mathrm", "textrm", "mathit"):
        contenu, suite = _groupe(source, suite)
        sortie.append(f'<span class="mot">{convertir(contenu)}</span>')
        return suite

    if nom == "mathbb":
        contenu, suite = _groupe(source, suite)
        sortie.append(
            {"Z": "ℤ", "R": "ℝ", "N": "ℕ", "C": "ℂ"}.get(contenu.strip(), contenu)
        )
        return suite

    if nom == "underbrace":
        contenu, suite = _groupe(source, suite)
        etiquette = ""
        if suite < len(source) and source[suite] == "_":
            etiquette, suite = _groupe(source, suite + 1)
        sortie.append(
            f'<span class="accolade"><span class="acc-c">{convertir(contenu)}</span>'
            f'<span class="acc-e">{convertir(etiquette)}</span></span>'
        )
        return suite

    if nom in ("left", "right", "big", "Big", "bigl", "bigr", "Bigl", "Bigr"):
        # La délimitation est portée par le caractère qui suit ; on le laisse
        # passer tel quel, la taille étant gérée par la feuille de style.
        if suite < len(source) and source[suite] in "()[]{}|.":
            delimiteur = source[suite]
            if delimiteur != ".":
                sortie.append(f'<span class="delim">{delimiteur}</span>')
            return suite + 1
        if suite < len(source) and source[suite] == "\\":
            # Délimiteur nommé : `\Big\langle`, `\left\lvert`. Il faut
            # l'ÉMETTRE et non seulement l'avaler — sans quoi les crochets
            # disparaissent et la formule perd son sens. Le bogue était
            # silencieux : la moyenne ⟨·⟩ du chapitre 12 s'affichait sans ses
            # chevrons, et rien ne le signalait.
            macro, apres = _groupe(source, suite)
            symbole = SYMBOLES.get(macro.lstrip("\\"))
            if symbole:
                sortie.append(f'<span class="delim">{symbole}</span>')
            return apres
        return suite

    if nom in ESPACES:
        sortie.append(ESPACES[nom])
        return suite

    if nom in GRECQUES:
        sortie.append(f'<span class="grec">{GRECQUES[nom]}</span>')
        return suite

    if nom in SYMBOLES:
        sortie.append(f'<span class="sym">{SYMBOLES[nom]}</span>')
        return suite

    if nom in OPERATEURS and OPERATEURS[nom]:
        sortie.append(f'<span class="op">{OPERATEURS[nom]}</span>')
        return suite

    _INCONNUES.add(nom)
    sortie.append(f'<span class="macro-inconnue">\\{nom}</span>')
    return suite


def bloc(formule: str) -> str:
    """Formule affichée sur sa propre ligne."""
    return f'<div class="formule">{convertir(formule)}</div>'


def en_ligne(formule: str) -> str:
    """Formule insérée dans le fil du texte."""
    return f'<span class="formule-ligne">{convertir(formule)}</span>'
