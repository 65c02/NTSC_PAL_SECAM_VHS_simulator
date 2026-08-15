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

in  vec2 v_uv;
out vec4 sortie;

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

    vec3 rgb = texture(u_image, uv).rgb;

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
