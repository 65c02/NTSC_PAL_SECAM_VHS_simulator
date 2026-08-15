#version 330 core

// ===========================================================================
//  Somme préfixe le long de chaque ligne, par doublement récursif.
//
//  Sert au SECAM : la phase d'une modulation de fréquence est l'intégrale du
//  signal modulant depuis le début de la ligne, et un fragment shader ne
//  connaît que son propre pixel.
//
//  Algorithme de Hillis et Steele. À l'étape d'écart `e`, chaque échantillon
//  ajoute celui qui se trouve `e` positions plus à gauche :
//
//      e = 1    x  ←  x + (x-1)
//      e = 2    x  ←  x + (x-2)
//      e = 4    x  ←  x + (x-4)
//      ...
//
//  Après ⌈log₂ W⌉ étapes, chaque échantillon contient la somme de tous ceux
//  qui le précèdent. Dix passes suffisent pour une ligne de 920 points, et
//  chacune ne lit que deux texels : le coût total est négligeable devant celui
//  d'une seule passe de filtrage.
//
//  Les échantillons situés avant le début de la ligne comptent pour zéro : la
//  suppression ligne ne transporte pas de chrominance.
// ===========================================================================

uniform sampler2D u_entree;
uniform vec2      u_taille;
uniform float     u_ecart;     // décalage de l'étape courante, en échantillons

in  vec2 v_uv;
out vec4 sortie;

void main()
{
    float somme = texture(u_entree, v_uv).r;

    float x = v_uv.x * u_taille.x;
    if (x - u_ecart >= 0.0)
        somme += texture(u_entree, v_uv - vec2(u_ecart / u_taille.x, 0.0)).r;

    sortie = vec4(somme, 0.0, 0.0, 1.0);
}
