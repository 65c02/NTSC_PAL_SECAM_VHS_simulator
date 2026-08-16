// ===========================================================================
//  Halo de tube — ce que la dalle de verre fait de la lumière qu'elle reçoit.
//
//  Deux phénomènes distincts se cachent derrière ce qu'on appelle « bloom » :
//
//    - la HALATION : la lumière émise par le luminophore traverse une dalle
//      de verre épaisse, s'y diffuse et se réfléchit sur la face avant. Une
//      petite fraction de chaque point lumineux repart en un halo large et
//      faible. C'est un phénomène linéaire, proportionnel à la lumière émise ;
//
//    - l'ÉPANOUISSEMENT DU FAISCEAU : à fort courant, le spot s'élargit et
//      perd sa mise au point. C'est franchement non linéaire, et cela ne se
//      déclenche que dans les hautes lumières — d'où le blanc qui bave sur les
//      génériques quand les gris, eux, restent nets.
//
//  Le seuil réglable interpole entre les deux : à zéro, tout diffuse, comme la
//  halation ; relevé, seules les hautes lumières s'épanouissent.
//
//  Trois passes, toutes sur un tampon au quart de la résolution : extraction
//  avec réduction, flou horizontal, flou vertical. Un flou gaussien étant
//  séparable, deux passes de treize échantillons valent une passe de
//  cent soixante-neuf.
//
//  Le fichier est compilé DEUX FOIS, avec ou sans PASSE_EXTRACTION. Un
//  uniforme et un `if` auraient suffi — le branchement est uniforme, donc
//  gratuit sur le matériel — mais deux programmes spécialisés laissent au
//  pilote toute latitude pour dérouler les boucles, et se lisent mieux.
// ===========================================================================

uniform sampler2D u_image;
uniform vec2      u_taille;      // taille de la cible courante, en texels
uniform vec2      u_direction;   // (1,0) ou (0,1)
uniform float     u_sigma;       // écart-type du halo, en texels de la cible
uniform float     u_seuil;       // genou bas, EN LUMIÈRE
uniform float     u_seuil_haut;  // genou haut, EN LUMIÈRE
uniform float     u_gamma;       // gamma de l'écran, pour passer en lumière

in  vec2 v_uv;
out vec4 sortie;

#ifdef PASSE_EXTRACTION

// Le halo se calcule en LUMIÈRE, jamais sur les valeurs affichées.
//
// Additionner des valeurs gamma-corrigées reviendrait à additionner des
// racines : un halo calculé ainsi paraît trop fort dans les ombres et trop
// faible dans les hautes lumières, exactement à l'envers de ce que fait une
// dalle de verre.
vec3 vers_lumiere(vec3 affiche) { return pow(max(affiche, 0.0), vec3(u_gamma)); }

void main()
{
    // Réduction au quart. Quatre lectures bilinéaires décalées d'un demi-texel
    // moyennent chacune un carré de 2x2 : on obtient la moyenne d'un carré de
    // 4x4 pour quatre accès au lieu de seize.
    vec2 pas = 1.0 / u_taille;
    vec3 somme = vec3(0.0);
    for (int i = 0; i < 4; ++i)
    {
        vec2 coin = vec2(float(i % 2) - 0.5, float(i / 2) - 0.5);
        somme += vers_lumiere(texture(u_image, v_uv + coin * pas).rgb);
    }
    vec3 lumiere = somme * 0.25;

    // Genou doux plutôt que seuil franc : un seuil net dessinerait un contour
    // dans le halo, là où un tube n'en a jamais montré.
    //
    // Les deux bornes arrivent déjà converties en lumière. Le réglage, lui,
    // s'exprime en niveau affiché — c'est ainsi qu'on le pense en le tournant,
    // et un seuil de 0,55 comparé à de la lumière correspondrait en réalité à
    // un gris de 0,81 à l'écran.
    float niveau = max(max(lumiere.r, lumiere.g), lumiere.b);
    float part = smoothstep(u_seuil, u_seuil_haut, niveau);
    sortie = vec4(lumiere * part, 1.0);
}

#else   // ------------------------------------------------------------ flou

const int TAPS = 6;   // treize échantillons au total, symétriques

void main()
{
    // Le pas d'échantillonnage suit sigma : le noyau couvre toujours ±3 sigma
    // quel que soit le rayon demandé, pour un coût constant.
    float sigma = max(u_sigma, 0.05);
    float pas = 3.0 * sigma / float(TAPS);
    vec3  somme = vec3(0.0);
    float total = 0.0;

    for (int k = -TAPS; k <= TAPS; ++k)
    {
        float d = float(k) * pas;
        float poids = exp(-0.5 * d * d / (sigma * sigma));
        somme += poids * texture(u_image, v_uv + u_direction * (d / u_taille)).rgb;
        total += poids;
    }
    sortie = vec4(somme / total, 1.0);
}

#endif
