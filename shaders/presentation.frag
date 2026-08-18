#version 330 core

// ===========================================================================
//  Passe de présentation : mise à l'échelle vers la fenêtre, plus le peu de
//  maquillage qui rend justice au résultat sur un écran plat.
//
//  Deux effets seulement, et tous deux issus de la géométrie d'un tube :
//
//    - les lignes de balayage, séparées par un intervalle sombre. Un tube
//      n'éclaire pas la totalité de la surface : le faisceau trace des lignes
//      qui ne se touchent pas tout à fait ;
//    - le masque du tube, qui découpe chaque triade de luminophores en bandes
//      rouge, verte et bleue.
//
//  Ils sont facultatifs et réglables. Tout le reste — le flou de la
//  chrominance, le fourmillement des points, les moirages — vient du codage
//  lui-même et n'a rien à faire ici.
// ===========================================================================

const float PI = 3.14159265358979;

uniform sampler2D u_image;
uniform vec2  u_taille_source;   // grille de la norme
uniform vec2  u_taille_ecran;
uniform vec2  u_echelle;         // cadrage : facteur puis décalage
uniform vec2  u_decalage;
uniform float u_lignes;          // intensité des lignes de balayage, 0 à 1
uniform float u_masque;          // intensité du masque de tube, 0 à 1
uniform float u_luminosite;
uniform float u_sigma_tube;      // spot du faisceau, en points de la grille
uniform sampler2D u_halo;
uniform float u_halo_intensite;  // fraction de lumière repartie en halo
uniform float u_gamma;           // gamma de l'écran, pour passer en lumière
uniform float u_rayon_dalle;     // rayon de la dalle, en demi-diagonales d'image
uniform float u_distance_oeil;   // distance d'observation, même unité
uniform float u_demi_largeur;    // demi-largeur de l'image, en demi-diagonales
uniform float u_demi_hauteur;
uniform float u_coins;           // arrondi des coins, exposant de la superellipse

// ------------------------------------------------------- volet de comparaison
//
// La vidéo telle qu'elle est entrée, avant tout traitement. Elle ne sert qu'au
// mode comparaison : à gauche du volet on l'affiche telle quelle, à droite on
// affiche le téléviseur.
//
// Les deux moitiés sont échantillonnées à la MÊME coordonnée d'image, courbure
// comprise. C'est ce qui rend la comparaison honnête : un point de la scène
// tombe au même endroit de la fenêtre des deux côtés du volet, et l'on ne
// compare donc que ce qui a changé — le signal, jamais la géométrie.
uniform sampler2D u_source_brute;
uniform float u_comparaison;     // 0 ou 1
uniform float u_volet;           // abscisse du volet, en fraction de fenêtre

// ---------------------------------------------------------------- courbure

// Position sur la dalle vue depuis l'œil, en demi-diagonales d'image.
//
// La dalle d'un tube n'est pas plate : c'est une calotte sphérique, et le
// balayage y peint l'image à longueur d'arc constante. Plutôt que d'appliquer
// la distorsion en barillet habituelle — qui n'a pas de sens physique et dont
// les coefficients se règlent au jugé — on fait la géométrie pour de bon :
//
//   1. un rayon part de l'œil et traverse le point d'écran considéré ;
//   2. on l'intersecte avec la sphère de la dalle, ce qui n'est qu'une
//      équation du second degré ;
//   3. on convertit le point obtenu en longueur d'arc depuis le sommet, ce
//      qui donne la coordonnée dans l'image.
//
// La projection azimutale équidistante ainsi obtenue conserve les distances
// radiales, ce qui est exactement la façon dont le faisceau balaie la dalle.
vec2 sur_la_dalle(vec2 p)
{
    float R = u_rayon_dalle;
    float D = u_distance_oeil;
    float u = dot(p, p);

    // t²(u + D²) − 2tD(R + D) + D(D + 2R) = 0
    float a = u + D * D;
    float b = -2.0 * D * (R + D);
    float c = D * (D + 2.0 * R);
    float discriminant = max(b * b - 4.0 * a * c, 0.0);
    float t = (-b - sqrt(discriminant)) / (2.0 * a);   // la plus proche

    float distance_axe = t * sqrt(u);
    if (distance_axe < 1e-6)
        return p * t;

    float arc = R * asin(clamp(distance_axe / R, -1.0, 1.0));
    return p * (arc / sqrt(u));
}

// Coordonnée d'image [-1,1] correspondant à un point d'écran [-1,1].
vec2 courber(vec2 n)
{
    if (u_rayon_dalle > 40.0)   // au-delà, la dalle est plate à l'œil
        return n;

    vec2 demi = vec2(u_demi_largeur, u_demi_hauteur);

    // Le facteur de normalisation est évalué au coin de l'image, de sorte que
    // le coin de la dalle tombe sur le coin du cadre : l'image tient tout
    // entière, et ce sont les bords qui se creusent — ce que montre un tube.
    float k = length(sur_la_dalle(demi));
    return sur_la_dalle(n * demi) / (k * demi);
}

in  vec2 v_uv;
out vec4 sortie;

// sin(πw)/(πw), prolongé par continuité en zéro.
float sinus_cardinal(float w)
{
    float x = PI * w;
    return (abs(x) < 1e-4) ? 1.0 : sin(x) / x;
}

const int TAPS_TUBE = 9;

// Réponse du tube : le spot du faisceau et la bande passante de
// l'amplificateur vidéo, ramassés en une gaussienne.
//
// C'est la pièce qui manquait le plus à cette simulation. Un téléviseur
// d'appartement affichait 300 à 400 lignes de définition horizontale ; il
// restituait donc la sous-porteuse — qui tombe à 229 alternances par largeur
// d'image — à moins du quart de son amplitude. Un écran plat, lui, la rend
// intégralement, et le résidu que le piège a laissé passer devient bien plus
// voyant qu'il ne l'a jamais été sur un tube.
//
// Les échantillons sont pris à des positions proportionnelles à sigma, et non
// à des points entiers : le noyau couvre alors toujours ±3 sigma, que le spot
// mesure un demi-point ou dix, pour un coût constant.
vec3 reponse_du_tube(vec2 uv)
{
    if (u_sigma_tube < 0.01)
        return texture(u_image, uv).rgb;

    float pas = 3.0 * u_sigma_tube / float(TAPS_TUBE);
    vec3  somme = vec3(0.0);
    float total = 0.0;

    for (int k = -TAPS_TUBE; k <= TAPS_TUBE; ++k)
    {
        float d = float(k) * pas;
        float poids = exp(-0.5 * (d * d) / (u_sigma_tube * u_sigma_tube));
        somme += poids * texture(u_image, uv + vec2(d / u_taille_source.x, 0.0)).rgb;
        total += poids;
    }
    return somme / total;
}

void main()
{
    vec2 uv = (v_uv - u_decalage) / u_echelle;
    vec2 n = courber(uv * 2.0 - 1.0);

    // Trait du volet, large de deux pixels PHYSIQUES quelle que soit la taille
    // de la fenêtre — c'est un repère d'interface, pas un élément de l'image.
    float trait = 0.0;
    if (u_comparaison > 0.5)
    {
        float d = abs(v_uv.x - u_volet) * u_taille_ecran.x;
        trait = 1.0 - smoothstep(0.5, 1.5, d);
    }

    // Franchement au large : rien à calculer. La marge est volontairement
    // généreuse — les dérivées `dFdx`/`dFdy` se prennent sur des groupes de
    // quatre fragments, et un voisin sorti prématurément les rendrait fausses
    // tout le long du bord.
    if (max(abs(n.x), abs(n.y)) > 1.05)
    {
        // Le trait continue hors de la dalle : on doit pouvoir attraper le
        // volet même quand il sort de l'image, sur les bandes noires.
        sortie = vec4(vec3(trait), 1.0);
        return;
    }

    // Bord de la dalle. Les coins d'un tube ne sont pas des angles vifs mais
    // des arrondis, que décrit une superellipse |x|^p + |y|^p = 1 : plus p est
    // grand, plus le coin est franc.
    //
    // On mesure la couverture du pixel au lieu de trancher par oui ou non. Un
    // simple test binaire donnait un escalier de marches d'un pixel, et il se
    // voyait d'autant mieux que le bord était oblique — c'est-à-dire
    // précisément dans les coins d'une dalle bombée. `fwidth` de la fonction
    // implicite donne la largeur de la transition, ce qui adoucit le bord
    // exactement d'un pixel, ni plus ni moins.
    float bord = max(abs(n.x), abs(n.y)) - 1.0;
    if (u_coins > 0.0)
        bord = max(bord, pow(abs(n.x), u_coins) + pow(abs(n.y), u_coins) - 1.0);
    float epaisseur = max(fwidth(bord), 1e-5);
    float couverture = 1.0 - smoothstep(-0.5 * epaisseur, 0.5 * epaisseur, bord);

    uv = n * 0.5 + 0.5;

    // Retournement vertical, et il n'est pas cosmétique.
    //
    // OpenGL place l'origine de ses textures en bas à gauche, alors qu'une
    // image se lit de haut en bas : la première ligne du tableau devient donc
    // la ligne du bas. Tout le traitement en amont travaille dans le repère de
    // l'image — il le faut, puisque le numéro de ligne détermine la phase de
    // la sous-porteuse, l'alternance du PAL et la séquence du SECAM. On ne
    // rétablit donc le sens qu'ici, au tout dernier moment.
    uv.y = 1.0 - uv.y;

    vec3 rgb = reponse_du_tube(uv);

    if (u_halo_intensite > 0.0)
    {
        // Le halo s'AJOUTE en lumière, pas en valeurs affichées : deux
        // sources lumineuses s'additionnent, leurs racines gamma-ièmes non.
        // On repasse donc en lumière le temps de l'addition.
        vec3 lumiere = pow(max(rgb, 0.0), vec3(u_gamma));
        lumiere += u_halo_intensite * texture(u_halo, uv).rgb;
        rgb = pow(max(lumiere, 0.0), vec3(1.0 / u_gamma));
    }

    if (u_lignes > 0.0)
    {
        // Profil des lignes de balayage, INTÉGRÉ sur la surface du pixel.
        //
        // L'échantillonner ponctuellement serait une faute, et une faute
        // visible : une fenêtre de 760 pixels de haut ne donne que 1,3 pixel
        // par ligne pour 576 lignes, soit moins que les deux qu'exige
        // Shannon. Le motif bat alors avec la grille de pixels. À plat le
        // battement est uniforme et passe pour du grain ; sous courbure le pas
        // local varie, le battement balaie l'image, et l'on voit apparaître de
        // larges bandes qui n'ont aucune existence physique. Mesuré : le moiré
        // triplait entre une dalle plate et une dalle bombée.
        //
        // L'intégrale, elle, est analytique. Le profil vaut
        //     sin²(πy) = (1 − cos 2πy) / 2
        // et sa moyenne sur le carré du pixel se sépare exactement :
        //     ⟨cos 2π·ligne⟩ = cos(2π·ligne₀) · sinc(gx) · sinc(gy)
        // où gx et gy sont les dérivées du numéro de ligne selon les deux axes
        // de l'écran, et sinc(w) = sin(πw)/(πw).
        //
        // Les DEUX axes, et c'est là que se jouait le défaut. `fwidth` renvoie
        // |gx| + |gy| — une somme, donc une majoration. Tant que la dalle est
        // plate elle ne coûte rien, gx étant nul : les lignes du tube sont
        // parallèles aux lignes de l'écran. Dès qu'on bombe la dalle, elles
        // cessent de l'être — une ligne de balayage se courbe, elle traverse
        // les pixels en biais, et gx cesse d'être nul dans les coins.
        //
        // La somme y franchissait 1, valeur où le sinus cardinal s'annule, et
        // le motif de balayage DISPARAISSAIT purement et simplement dans les
        // quatre coins alors que rien ne le justifiait. Mesuré à courbure
        // maximale sur une fenêtre de 760 pixels : 0,041 d'atténuation au coin
        // là où l'intégrale exacte en donne 0,189, soit quatre fois et demie
        // trop sombre.
        float ligne = uv.y * u_taille_source.y;
        float gx = abs(dFdx(ligne));
        float gy = abs(dFdy(ligne));

        // Au-delà d'une ligne par pixel, le sinus cardinal devient négatif :
        // l'intégrale est juste, mais afficher des lignes en contraste inversé
        // serait un artefact de rendu, pas une caractéristique de tube. On
        // laisse simplement le motif s'éteindre.
        float attenuation = max(sinus_cardinal(gx) * sinus_cardinal(gy), 0.0);
        float profil = 0.5 - 0.5 * cos(2.0 * PI * ligne) * attenuation;
        rgb *= mix(1.0, profil, u_lignes);
    }

    if (u_masque > 0.0)
    {
        // Une bande de luminophore sur trois, en fonction de la colonne
        // physique de l'écran — donc lié à la fenêtre, pas à la norme.
        int bande = int(mod(gl_FragCoord.x, 3.0));
        vec3 triade = (bande == 0) ? vec3(1.0, 0.7, 0.7)
                    : (bande == 1) ? vec3(0.7, 1.0, 0.7)
                                   : vec3(0.7, 0.7, 1.0);
        rgb *= mix(vec3(1.0), triade, u_masque);
    }

    // Les deux effets assombrissent l'image ; on rend la lumière perdue.
    vec3 finale = rgb * u_luminosite;

    // À gauche du volet : la vidéo, telle qu'elle est entrée dans la chaîne.
    //
    // Le choix se fait ICI, et non par un retour anticipé plus haut, alors
    // qu'un retour serait moins coûteux. La raison est la même que pour la
    // marge du bord : `dFdx` et `dFdy` se calculent sur des groupes de quatre
    // fragments, et le GLSL ne les définit que si tout le groupe suit le même
    // chemin. Sortir dès qu'on est à gauche du volet rendrait donc fausses,
    // sur la colonne de pixels qui le borde, les dérivées dont dépendent
    // l'intégrale des lignes de balayage et l'adoucissement du bord de dalle.
    //
    // Ni réponse du tube, ni halo, ni lignes, ni masque de ce côté-ci — et pas
    // de luminosité non plus : ce réglage existe pour rendre la lumière que
    // les lignes et le masque ont prise, et il n'y a rien à rendre ici.
    if (u_comparaison > 0.5 && v_uv.x < u_volet)
        finale = texture(u_source_brute, uv).rgb;

    finale = clamp(finale * couverture, 0.0, 1.0);
    sortie = vec4(mix(finale, vec3(1.0), trait), 1.0);
}
