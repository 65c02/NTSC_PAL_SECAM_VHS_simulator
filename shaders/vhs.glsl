// ===========================================================================
//  Le magnétoscope, en une passe.
//
//  Lit le signal composite, le fait passer par une cassette, rend un signal
//  composite. Le décodeur qui suit n'y voit que du feu — c'est exactement ce
//  que fait un magnétoscope branché sur la prise antenne.
//
//  Le procédé simulé est le *color-under* :
//
//    - la luminance est limitée à 3 MHz. Ce seul filtre suffit à la séparer de
//      la chrominance, qui vit à 4,43 MHz : inutile de séparer d'abord pour
//      filtrer ensuite, le passe-bas fait les deux ;
//    - la chrominance est ramenée en bande de base par un oscillateur local à
//      la sous-porteuse, limitée à 400 kHz, puis remontée. C'est de là que
//      vient la caractéristique du format : sa couleur est huit fois moins
//      fine que sa luminance ;
//    - le tout est décalé ligne à ligne par la gigue de défilement.
//
//  Le point délicat, et il a coûté deux fautes dans la version de référence :
//  **le décalage porte sur l'ENVELOPPE, jamais sur la porteuse.** Décaler le
//  composite de deux échantillons, là où la sous-porteuse tombe au quart de la
//  fréquence d'échantillonnage, c'est la tourner d'un demi-tour — le magenta
//  ressort vert. Un magnétoscope ne fait pas cela : sa porteuse de relecture
//  est régénérée à partir du signal lu, donc décalée d'autant, et l'erreur
//  s'annule dans la démodulation. On lit donc l'entrée à la position décalée,
//  et l'on remodule à la phase de la position d'ARRIVÉE.
// ===========================================================================

uniform sampler2D u_vhs_entree;

// Les noyaux du magnétoscope ont leur propre longueur, bien plus grande que
// celle des autres passes. La raison tient en un rapport : l'enveloppe de
// chrominance d'une cassette tient dans 400 kHz sur une grille à 17,7 MHz,
// soit une coupure à 2,3 % de la fréquence d'échantillonnage. Vingt et un
// coefficients ne savent pas former un flanc aussi raide, et la luminance fuit
// dans la couleur.
uniform float u_vhs_noyau_luma[N_VHS];     // limitation de bande de la luminance
uniform float u_vhs_noyau_douce[N_VHS];    // version plus molle, pour le liseré
uniform float u_vhs_noyau_chroma[N_VHS];   // limitation de l'enveloppe de couleur

uniform float u_vhs_retard;        // retard de la couleur, en échantillons entiers
uniform float u_vhs_gigue;         // amplitude de la gigue, en échantillons
uniform float u_vhs_depassement;
uniform float u_vhs_bruit_luma;
uniform float u_vhs_bruit_chroma;
uniform float u_vhs_abandons;      // NOMBRE de pertes attendu par image
uniform float u_vhs_commutation;   // nombre de lignes perturbées en bas
uniform float u_vhs_graine;
// Change à chaque image, et il le faut : une bande défile. Le morceau de ruban
// qui passe sous la tête n'est jamais le même, donc ni la gigue ni les pertes
// de signal ne se répètent.
//
// La première version s'appuyait sur `u_phase_image` pour varier — la phase de
// sous-porteuse d'une image à l'autre. Mauvaise idée : cette grandeur ne prend
// que deux valeurs en NTSC, quatre en PAL, et **une seule en SECAM**, où la
// sous-porteuse est un multiple entier de la fréquence ligne. Les défauts de
// la cassette restaient donc figés d'un bout à l'autre du film.

// --------------------------------------------------------------------------

// Générateur pseudo-aléatoire, sans sinus et sans grand nombre.
//
// Le classique `fract(sin(x) * 43758.0)` ne convient pas ici, et pour une
// raison qu'il faut avoir mesurée pour y croire. Ce n'est pas le sinus qui est
// en cause, c'est la `fract` : la partie fractionnaire d'un flottant de
// l'ordre de 43 000 ne se représente que par pas de 0,0026. La valeur rendue
// ne descend donc JAMAIS sous ce plancher, sauf à valoir exactement zéro.
//
// Or les pertes de signal se testent contre un seuil de quelques millionièmes
// — une bande VHS neuve en spécifie dix à vingt par MINUTE. Comparer 4·10⁻⁶ à
// un tirage qui ne sait produire que des multiples de 0,0026 ne sélectionne
// plus une probabilité : le nombre de pertes cessait d'obéir au réglage, et
// l'image en était criblée.
//
// Ici, toutes les `fract` portent sur des nombres de l'ordre de l'unité : la
// résolution reste celle du flottant, jusqu'au dix-millionième.
float hachage(float x)
{
    vec3 p = fract(vec3(x * 0.1031, x * 0.1030, x * 0.0973) + u_vhs_graine);
    p += dot(p, p.yzx + 33.33);
    return fract((p.x + p.y) * p.z);
}

const int CANDIDATS = 4;
const float SEGMENTS = 24.0;

// Pertes de signal : on TIRE LEURS POSITIONS, on ne teste pas chaque position.
//
// La différence est de méthode, et l'arithmétique l'impose. Tester chaque
// segment de chaque ligne fait 13 824 tirages par image ; pour obtenir les
// 0,06 perte qu'une bande correcte produit, il faudrait comparer contre une
// probabilité de 4·10⁻⁶.
//
// Aucun générateur en flottants ne sait descendre là — voir la remarque sur
// `hachage` ci-dessus. Comparer 4·10⁻⁶ à un tirage dont la résolution plafonne
// à 6·10⁻⁴ ne sélectionne plus une probabilité : c'est ainsi que l'image se
// retrouvait criblée de six cents fois trop de pertes, sans obéir au réglage.
//
// On renverse donc la question. Plutôt que « ce segment est-il perdu ? », on
// demande « où sont les pertes de cette image ? » : quatre candidats, chacun
// tiré avec une probabilité de l'ordre du dixième, et dont on tire ensuite la
// ligne et le segment. Tous les seuils restent alors dans la plage où les
// flottants sont fiables, et le compte obéit exactement au réglage.
bool perte(float ligne, float segment)
{
    if (u_vhs_abandons <= 0.0)
        return false;

    float part = min(u_vhs_abandons / float(CANDIDATS), 1.0);
    for (int i = 0; i < CANDIDATS; ++i)
    {
        float g = float(i) * 137.0;
        if (hachage(g + 1.0) >= part)
            continue;
        if (floor(hachage(g + 2.0) * u_taille.y) != ligne)
            continue;
        if (floor(hachage(g + 3.0) * SEGMENTS) == segment)
            return true;
    }
    return false;
}

// Bruit de valeur d'une période donnée, lisse par construction.
float palier(float ligne, float periode, float sel)
{
    float u = ligne / periode;
    float base = floor(u);
    float t = u - base;
    t = t * t * (3.0 - 2.0 * t);      // lissage de Hermite
    float a = hachage(base + sel) - 0.5;
    float b = hachage(base + 1.0 + sel) - 0.5;
    return 2.0 * mix(a, b, t);
}

// Gigue de défilement : lente, et il le faut absolument.
//
// Une bande a de l'inertie. L'erreur de base de temps est dominée par la
// rotation du tambour et l'élasticité du ruban, c'est-à-dire par des périodes
// de plusieurs dizaines de lignes — pas par un tremblement d'une ligne à
// l'autre.
//
// La nuance n'est pas cosmétique, et elle a coûté une image en lambeaux.
// Le décodeur qui suit est un filtre en peigne : il compare la ligne n à la
// ligne n-2. Une ondulation de période quatre décalait ces deux lignes-là de
// quantités DIFFÉRENTES, la soustraction du peigne ne compensait plus rien, et
// l'image se déchirait en bandes horizontales. Avec vingt-quatre lignes de
// période, deux lignes voisines sont décalées de presque autant et le peigne
// retrouve son office.
//
// On ajoute une seconde octave, quatre fois plus rapide et quatre fois plus
// faible : une mécanique n'est pas une sinusoïde pure.
float ondulation(float ligne)
{
    return 0.8 * palier(ligne, 24.0, 0.0) + 0.2 * palier(ligne, 6.0, 91.0);
}

void main()
{
    vec2  dh    = pas_h();
    float ligne = floor(v_uv.y * u_taille.y);
    int   demi  = N_VHS / 2;

    float decalage = u_vhs_gigue * ondulation(ligne);

    // Commutation des têtes : les deux têtes du tambour se relaient une fois
    // par trame, quelques lignes avant la fin de l'image active. Le relais
    // n'est pas instantané — ces lignes-là sont franchement décalées.
    float restantes = u_taille.y - 1.0 - ligne;
    float force = 0.0;
    if (u_vhs_commutation > 0.0 && restantes < u_vhs_commutation)
    {
        force = (u_vhs_commutation - restantes) / u_vhs_commutation;
        decalage += force * 0.06 * u_taille.x;
    }

    // Pertes de signal : l'oxyde manque, la tête ne lit rien. Le magnétoscope
    // comble avec la ligne précédente — c'est le rôle du dropout compensator —
    // mais l'escamotage se voit. On découpe la ligne en segments et l'on en
    // condamne quelques-uns.
    float segment = floor(v_uv.x * SEGMENTS);
    bool abandon = perte(ligne, segment);

    // Le décalage est ARRONDI À L'ÉCHANTILLON, et ce n'est pas une paresse.
    //
    // La texture du composite est filtrée au plus proche : une lecture à une
    // position fractionnaire retombe sur le texel voisin. La phase de
    // démodulation, elle, était calculée sur la position exacte demandée — et
    // les deux ne parlaient alors plus du même échantillon. À quatre points
    // par cycle de sous-porteuse, un demi-échantillon d'écart vaut 45° de
    // teinte, et la partie fractionnaire du décalage changeant à chaque ligne,
    // l'image se rayait de bandes horizontales aux couleurs fausses.
    //
    // En arrondissant, la lecture et la phase désignent le même point et
    // l'erreur disparaît. On y perd la finesse du décalage — un échantillon,
    // soit un neuf-cent-vingtième de ligne — ce qui est de toute façon plus
    // fin que ce que l'écran saura montrer.
    decalage = floor(decalage + 0.5);

    vec2 base = v_uv + decalage * dh;
    if (abandon)
        base -= pas_v();          // on relit la ligne précédente

    // ---- une seule boucle pour les trois accumulateurs --------------------
    //
    // La lecture de texture coûte des dizaines de fois plus cher que la
    // multiplication : on lit chaque échantillon une fois et on l'envoie aux
    // trois filtres. Le décalage de la voie couleur se fait sur l'indice, pas
    // par une seconde lecture.
    float luma = 0.0;
    float douce = 0.0;
    vec2  enveloppe = vec2(0.0);

    for (int k = 0; k < N_VHS; ++k)
    {
        float d = float(k - demi);
        float y = texture(u_vhs_entree, base + d * dh).r;

        luma  += u_vhs_noyau_luma[k]  * y;
        douce += u_vhs_noyau_douce[k] * y;

        // Enveloppe de chrominance : le même échantillon, décalé du retard de
        // la voie couleur, ramené en bande de base par la sous-porteuse.
        float xc = base.x + (d + u_vhs_retard) / u_taille.x;
        float c  = texture(u_vhs_entree, vec2(xc, base.y)).r;
        float ph = phase(xc, ligne);
        enveloppe += u_vhs_noyau_chroma[k] * c * vec2(cos(ph), -sin(ph));
    }

    // ---- liseré de contour -----------------------------------------------
    //
    // Tout enregistreur à modulation de fréquence relève fortement les hautes
    // fréquences avant d'écrire et les rabaisse en lisant. Le relèvement est
    // violent, le limiteur écrête les crêtes qu'il fabrique, et la
    // désaccentuation rend un signal dont les dépassements ne se compensent
    // plus : il reste un liseré clair au bord des zones sombres. C'est la
    // signature visuelle du format, visible sur n'importe quel générique.
    luma += 0.35 * u_vhs_depassement * (luma - douce);

    if (u_vhs_bruit_luma > 0.0)
        luma += u_vhs_bruit_luma * bruit_gaussien(v_uv * u_taille + 11.0);

    if (u_vhs_bruit_chroma > 0.0)
        enveloppe += u_vhs_bruit_chroma
                   * vec2(bruit_gaussien(v_uv * u_taille + 29.0),
                          bruit_gaussien(v_uv * u_taille + 53.0));

    // ---- retour à la sous-porteuse ---------------------------------------
    //
    // À la phase de la position d'ARRIVÉE, et non de celle qu'on a lue : c'est
    // ce qui fait que l'image ondule sans que la teinte tourne. Le facteur
    // deux rétablit ce que la représentation analytique avait laissé dans les
    // fréquences négatives.
    float phi = phase(v_uv.x, ligne);
    float chroma = 2.0 * (enveloppe.x * cos(phi) - enveloppe.y * sin(phi));

    float signal = luma + chroma;

    // La bascule du compensateur de perte laisse une marque brève.
    if (abandon && fract(v_uv.x * SEGMENTS) < 0.12)
        signal += 0.25;
    if (force > 0.0)
        signal += 0.05 * force * bruit_gaussien(v_uv * u_taille + 71.0);

    sortie = vec4(signal, 0.0, 0.0, 1.0);
}
