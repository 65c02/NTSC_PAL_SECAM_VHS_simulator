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

in  vec2 v_uv;
out vec4 sortie;

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

    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0))))
    {
        sortie = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

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
        // Position à l'intérieur de la ligne de balayage courante.
        float dans_la_ligne = fract(uv.y * u_taille_source.y);
        float profil = sin(dans_la_ligne * PI);
        rgb *= mix(1.0, profil * profil, u_lignes);
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
    sortie = vec4(clamp(rgb * u_luminosite, 0.0, 1.0), 1.0);
}
