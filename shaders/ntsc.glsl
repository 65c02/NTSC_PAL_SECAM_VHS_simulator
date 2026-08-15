// ===========================================================================
//  NTSC — modulation en quadrature sur une sous-porteuse à 455/2 . f_H
//
//  Le même fichier sert aux deux passes : compilé avec PASSE_CODAGE il produit
//  le signal composite, sans lui il le décode. Cela garantit que les deux
//  moitiés partagent exactement la même horloge de sous-porteuse — une phase
//  qui divergerait d'un iota entre codeur et décodeur ferait tourner toutes
//  les teintes, et le bogue serait indétectable à la lecture.
// ===========================================================================

#ifdef PASSE_CODAGE

void main()
{
    vec2  dh    = pas_h();
    float ligne = floor(v_uv.y * u_taille.y);
    int   demi  = N_TAPS / 2;

    // Une seule boucle, une seule lecture de texture par tap, trois
    // accumulateurs. Les axes I et Q reçoivent des noyaux différents :
    // 1,3 MHz pour l'axe orange-cyan, 0,4 MHz seulement pour l'axe
    // vert-magenta, que l'œil distingue mal (cf. cours, chapitre 6).
    float y = 0.0;
    vec2  iq = vec2(0.0);

    for (int k = 0; k < N_TAPS; ++k)
    {
        float d   = float(k - demi);
        vec3  rgb = oetf(texture(u_source, v_uv + d * dh).rgb);
        vec2  kiq = uv_vers_iq(vers_uv(rgb));

        y    += u_noyau_luma[k] * luma(rgb);
        iq.x += u_noyau_c1[k]   * kiq.x;
        iq.y += u_noyau_c2[k]   * kiq.y;
    }

    vec2 uv = iq_vers_uv(iq);

    // Non-linéarité de l'émetteur : le déphasage dépend du niveau. C'est le
    // défaut historique du NTSC, et la seule chose qui distingue vraiment son
    // comportement de celui du PAL sur un canal dégradé.
    float phi = phase(v_uv.x, ligne) + u_phase_diff * y;
    float gain = u_amplitude_chroma * (1.0 + u_gain_diff * y);

    float chroma = gain * (uv.x * sin(phi) + uv.y * cos(phi));
    float signal = u_piedestal + (1.0 - u_piedestal) * (y + chroma);

    if (u_bruit > 0.0)
        signal += u_bruit * bruit_gaussien(v_uv * u_taille);

    sortie = vec4(signal, 0.0, 0.0, 1.0);
}

#else   // ------------------------------------------------------ décodage

void main()
{
    vec2  dh    = pas_h();
    vec2  dv    = pas_v();
    float ligne = floor(v_uv.y * u_taille.y);
    int   demi  = N_TAPS / 2;

    float c_centre = 0.0, c_precedent = 0.0;
    vec2  uv = vec2(0.0);

    for (int k = 0; k < N_TAPS; ++k)
    {
        float d = float(k - demi);
        vec2  p = v_uv + d * dh;
        float c = composite_en(p);

        float ch;
        if (u_separateur == 0)
        {
            // Filtre en peigne. En NTSC la sous-porteuse tourne exactement de
            // 180° d'une ligne à la suivante : la chrominance change de signe
            // là où la luminance, elle, ne bouge presque pas. La différence
            // isole donc l'une, la somme isole l'autre.
            float precedente = composite_en(p - dv);
            ch = 0.5 * (c - precedente);
            if (k == demi) { c_centre = c; c_precedent = precedente; }
        }
        else
        {
            // Réjecteur. La voie chrominance n'est PAS le complément de la
            // voie luminance : ce sont deux filtres indépendants, comme dans
            // un vrai téléviseur. La démodulation qui suit se charge elle-même
            // du passe-bande, il n'y a donc rien à retrancher ici.
            ch = c;
        }

        // Démodulation synchrone et passe-bas fusionnés : multiplier par la
        // référence locale puis pondérer, c'est exactement filtrer le produit.
        float ph = phase(v_uv.x + d / u_taille.x, ligne);
        uv += u_noyau_dec[k] * 2.0 * ch * vec2(sin(ph), cos(ph));
    }

    float y = (u_separateur == 0) ? 0.5 * (c_centre + c_precedent)
                                  : luminance_piegee(v_uv, dh);

    y  = (y - u_piedestal) / (1.0 - u_piedestal);
    uv *= u_saturation / (1.0 - u_piedestal);

    sortie = vec4(eotf(clamp(yuv_vers_rgb(y, uv), 0.0, 1.0)), 1.0);
}

#endif
