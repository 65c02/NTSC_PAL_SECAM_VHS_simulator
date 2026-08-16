// ===========================================================================
//  Entête partagé par les trois shaders NTSC, PAL et SECAM.
//
//  Ce fichier est concaténé en tête de chaque programme par `lecteur/gl_util`.
//  Il regroupe ce que les trois normes ont en commun : le matriçage, l'horloge
//  de sous-porteuse, et les fonctions de transfert.
//
//  Les constantes ne sont pas écrites ici en dur : elles arrivent en uniformes,
//  calculées côté Python depuis `tvcolor.constantes`. Il n'y a donc qu'une
//  seule source de vérité pour les valeurs normatives, partagée avec le
//  simulateur de référence et avec le cours.
// ===========================================================================

const float PI      = 3.14159265358979;
const float DEUX_PI = 6.28318530717959;

// --------------------------------------------------------------- uniformes

uniform sampler2D u_source;      // image d'entrée (passe de codage)
uniform sampler2D u_composite;   // signal composite (passe de décodage)
uniform sampler2D u_prepare;     // SECAM : (écart de fréquence, luminance)
uniform sampler2D u_scan;        // SECAM : somme préfixe de l'écart

uniform vec2  u_taille;          // grille de la norme, en échantillons
uniform float u_cycles_actifs;   // f_sc * durée de ligne active
uniform float u_frac_ligne;      // partie fractionnaire de f_sc / f_H
uniform float u_phase_image;     // avance de phase due au numéro d'image
uniform float u_piedestal;
uniform float u_gamma;
uniform float u_amplitude_chroma;
uniform float u_saturation;

uniform float u_phase_diff;      // radians de sous-porteuse par unité de luma
uniform float u_gain_diff;
uniform float u_bruit;           // écart-type du bruit, en amplitude vidéo
uniform float u_graine;          // décorrèle le bruit d'une image à l'autre

uniform int   u_separateur;      // 0 = peigne, 1 = réjecteur
uniform int   u_ligne_retard;    // PAL : 1 = PAL-D, 0 = PAL-S

// Les cinq noyaux ont tous la même longueur, quitte à en compléter certains
// de zéros. Ce n'est pas du gaspillage : cela permet de n'écrire qu'UNE seule
// boucle par passe, et donc de ne lire chaque texel qu'une fois pour alimenter
// à la fois la voie luminance et la voie chrominance. Le coût d'une lecture de
// texture dépasse de loin celui d'une multiplication par zéro.
uniform float u_noyau_luma[N_TAPS];    // limitation de bande de Y'
uniform float u_noyau_c1[N_TAPS];      // limitation de bande de U / I / D'B
uniform float u_noyau_c2[N_TAPS];      // limitation de bande de V / Q / D'R
uniform float u_noyau_dec[N_TAPS];     // passe-bas de chrominance au décodage

// Le piège a sa propre longueur, et bien plus grande. Un passe-bas n'a qu'un
// flanc à former ; un réjecteur en a deux, encadrant une bande étroite. À 21
// coefficients il ne rejette que 11 dB, et la sous-porteuse resterait visible
// en clair dans l'image.
uniform float u_noyau_notch[N_NOTCH];

// SECAM
uniform vec2  u_secam_repos;     // fréquences de repos (bleue, rouge), en Hz
uniform vec2  u_secam_dev;       // excursions par unité (bleue, rouge), en Hz
uniform vec2  u_secam_butees;    // écrêtage de l'excursion (min, max), en Hz
uniform float u_secam_f0;        // centre du filtre cloche, en Hz
uniform float u_secam_gain_max;  // normalisation du filtre cloche
uniform float u_f_ech;           // fréquence d'échantillonnage de la grille

in  vec2 v_uv;
out vec4 sortie;

// ------------------------------------------------------------- colorimétrie

// Coefficients de luma de BT.470, hérités des primaires NTSC 1953.
const vec3 COEFFS_LUMA = vec3(0.299, 0.587, 0.114);

// Facteurs d'échelle des différences de couleur (cf. cours, chapitre 4).
const float FACTEUR_U = 0.492111;
const float FACTEUR_V = 0.877283;
const float FACTEUR_DB =  1.505;
const float FACTEUR_DR = -1.902;

// Rotation des axes I/Q du NTSC.
const float COS33 = 0.83867057;
const float SIN33 = 0.54463904;

float luma(vec3 rgb)          { return dot(rgb, COEFFS_LUMA); }
vec2  vers_uv(vec3 rgb)       { float y = luma(rgb);
                                return vec2(FACTEUR_U * (rgb.b - y),
                                            FACTEUR_V * (rgb.r - y)); }
vec2  uv_vers_iq(vec2 uv)     { return vec2(-SIN33 * uv.x + COS33 * uv.y,
                                             COS33 * uv.x + SIN33 * uv.y); }
vec2  iq_vers_uv(vec2 iq)     { return vec2(-SIN33 * iq.x + COS33 * iq.y,
                                             COS33 * iq.x + SIN33 * iq.y); }
vec2  vers_drdb(vec3 rgb)     { float y = luma(rgb);
                                return vec2(FACTEUR_DR * (rgb.r - y),
                                            FACTEUR_DB * (rgb.b - y)); }

vec3 yuv_vers_rgb(float y, vec2 uv)
{
    return vec3(y + 1.139883 * uv.y,
                y - 0.394642 * uv.x - 0.580622 * uv.y,
                y + 2.032062 * uv.x);
}

vec3 ydrdb_vers_rgb(float y, vec2 drdb)
{
    // Simple changement d'échelle vers U et V, puis matriçage inverse commun.
    return yuv_vers_rgb(y, vec2(FACTEUR_U / FACTEUR_DB * drdb.y,
                                FACTEUR_V / FACTEUR_DR * drdb.x));
}

// Correction de gamma de la prise de vue. Le matriçage a lieu APRÈS elle :
// c'est l'origine de la non-constant-luminance (cf. cours, chapitre 11).
vec3 oetf(vec3 lineaire) { return pow(max(lineaire, 0.0), vec3(1.0 / u_gamma)); }
vec3 eotf(vec3 corrige)  { return pow(max(corrige, 0.0), vec3(u_gamma)); }

// --------------------------------------------------------------- sous-porteuse

// Phase de la sous-porteuse, en radians, au point (u, ligne).
//
// Comme dans le simulateur de référence, la phase est calculée en temps
// absolu et n'est jamais remise à zéro en début de ligne. C'est de là, et de
// rien d'autre, que naissent l'alternance de 180° du NTSC, le fourmillement
// des points et le fonctionnement du filtre en peigne.
//
// La réduction modulo 1 est faite terme à terme et non à la fin : en simple
// précision, 283,7516 x 576 lignes vaut 163 441, dont l'ulp est de 0,015625
// cycle — soit 5,6° d'erreur de teinte en bas de l'image, et rien du tout en
// haut. En ne propageant que la partie fractionnaire de f_sc/f_H, la valeur
// reste dans l'intervalle [0, 1[ où l'ulp vaut 6·10⁻⁸, et l'erreur retombe
// sous le millionième de degré.
float phase(float u, float ligne)
{
    float cycles = u_phase_image
                 + fract(u_frac_ligne * ligne)
                 + u_cycles_actifs * u;
    return DEUX_PI * fract(cycles);
}

// ------------------------------------------------------------------- bruit

// Générateur pseudo-aléatoire sans texture ni état.
//
// Le réflexe est le « hash sinus », fract(sin(dot(p, k)) * grand_nombre). Il a
// deux défauts qui se voient ici. Sa qualité dépend de la précision de sin(),
// donc le grain change d'une carte graphique à l'autre ; et il laisse des
// corrélations régulières le long des lignes, qui donnent au bruit un aspect
// trop lisse, trop « tapis ». Un mélangeur entier coûte la même chose et n'a
// ni l'un ni l'autre.
uint melanger(uint h)
{
    h ^= h >> 16; h *= 0x7FEB352Du;
    h ^= h >> 15; h *= 0x846CA68Bu;
    h ^= h >> 16;
    return h;
}

float alea(vec2 p, uint sel)
{
    // Décalage avant la conversion : les noyaux lisent à gauche du bord, donc
    // p peut être négatif, et le tour du compteur non signé casserait la
    // continuité du champ juste à cet endroit.
    uvec2 e = uvec2(ivec2(floor(p)) + 8192);
    return float(melanger(e.x * 0x9E3779B9u ^ melanger(e.y * 0x85EBCA6Bu)
                          ^ floatBitsToUint(u_graine) ^ sel))
           * (1.0 / 4294967296.0);
}

// Deux tirages uniformes -> un tirage gaussien, par la transformation de
// Box-Muller. Le bruit d'un canal de transmission est gaussien ; un bruit
// uniforme n'aurait ni les mêmes queues de distribution ni le même aspect.
float bruit_gaussien(vec2 p)
{
    float a = max(alea(p, 0x1u), 1e-6);
    float b = alea(p, 0x2u);
    return sqrt(-2.0 * log(a)) * cos(DEUX_PI * b);
}

// Bruit du canal, limité à la bande de luminance.
//
// C'est ce que fait `canal._bruit` : un tirage gaussien blanc, un passe-bas à
// `bande_y`, puis une renormalisation pour retrouver le sigma demandé. Le
// shader ajoutait pour sa part du bruit blanc, ce qui était un écart à la
// référence, et un écart visible.
//
// Le filtrage n'est pas cosmétique. Le bruit thermique arrive plat, mais rien
// de ce qui dépasse la bande de luminance ne parvient à l'écran : l'étage FI
// puis l'amplificateur vidéo le coupent, exactement comme ils coupent le
// signal. Employer ici le noyau de luminance n'est donc pas une approximation
// du passe-bas de la référence, c'est le même filtre — `noyau_passe_bas` est
// justement taillé pour épouser sa réponse.
//
// La conséquence est ce que l'oeil lit en premier. Les échantillons d'une même
// ligne restent corrélés sur plusieurs positions, alors que deux lignes sont
// indépendantes : le grain est plus large que haut, et il s'agglomère. C'est
// toute la différence entre de la neige de télévision et du poivre et sel.
float bruit_video(vec2 p)
{
    int demi = N_TAPS / 2;
    float somme = 0.0;
    float energie = 0.0;

    for (int k = 0; k < N_TAPS; ++k)
    {
        float w = u_noyau_luma[k];
        somme += w * bruit_gaussien(p + vec2(float(k - demi), 0.0));
        // Des tirages indépendants ajoutent leurs variances, pas leurs
        // écarts-types. La référence mesure la valeur efficace obtenue et
        // divise par elle ; ici l'énergie du noyau donne la même chose sans
        // avoir à parcourir l'image.
        energie += w * w;
    }
    return somme * inversesqrt(max(energie, 1e-12));
}

// ---------------------------------------------------------------- accès

float composite_en(vec2 uv) { return texture(u_composite, uv).r; }

// Voie luminance d'un décodeur à réjecteur : le piège de sous-porteuse, dans
// sa propre boucle puisqu'il est bien plus long que les autres noyaux.
float luminance_piegee(vec2 base, vec2 dh)
{
    int   demi = N_NOTCH / 2;
    float y = 0.0;
    for (int k = 0; k < N_NOTCH; ++k)
        y += u_noyau_notch[k] * composite_en(base + float(k - demi) * dh);
    return y;
}

// Un pas d'un échantillon, horizontalement puis verticalement.
vec2 pas_h() { return vec2(1.0 / u_taille.x, 0.0); }
vec2 pas_v() { return vec2(0.0, 1.0 / u_taille.y); }
