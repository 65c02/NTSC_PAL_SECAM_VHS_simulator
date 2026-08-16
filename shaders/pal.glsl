// ===========================================================================
//  PAL — la même modulation en quadrature que NTSC, à un signe près.
//
//  Une ligne sur deux voit sa composante V inversée. C'est tout le PAL, et
//  cela suffit à annuler l'erreur de phase : les termes parasites, étant
//  proportionnels à ce signe, s'opposent d'une ligne à l'autre et disparaissent
//  à la moyenne. Il ne reste qu'une perte de saturation en cos θ.
// ===========================================================================

// Signe de la composante V pour une ligne donnée : +1, -1, +1, -1...
float signe_pal(float ligne)
{
    return (mod(ligne, 2.0) < 0.5) ? 1.0 : -1.0;
}

#ifdef PASSE_CODAGE

void main()
{
    vec2  dh    = pas_h();
    float ligne = floor(v_uv.y * u_taille.y);
    int   demi  = N_TAPS / 2;

    float y  = 0.0;
    vec2  uv = vec2(0.0);

    for (int k = 0; k < N_TAPS; ++k)
    {
        float d   = float(k - demi);
        vec3  rgb = oetf(texture(u_source, v_uv + d * dh).rgb);
        vec2  kuv = vers_uv(rgb);

        y    += u_noyau_luma[k] * luma(rgb);
        uv.x += u_noyau_c1[k]   * kuv.x;
        uv.y += u_noyau_c2[k]   * kuv.y;
    }

    float phi  = phase(v_uv.x, ligne) + u_phase_diff * y;
    float gain = u_amplitude_chroma * (1.0 + u_gain_diff * y);

    // L'unique différence avec NTSC tient dans ce signe.
    float chroma = gain * (uv.x * sin(phi) + signe_pal(ligne) * uv.y * cos(phi));
    float signal = u_piedestal + (1.0 - u_piedestal) * (y + chroma);

    if (u_bruit > 0.0)
        signal += u_bruit * bruit_video(v_uv * u_taille);

    sortie = vec4(signal, 0.0, 0.0, 1.0);
}

#else   // ------------------------------------------------------ décodage

// Démodule une ligne complète et rétablit le signe de V. Retourne
// (luminance, U, V).
vec3 demoduler_ligne(vec2 base, float ligne, vec2 dh, vec2 dv)
{
    int   demi = N_TAPS / 2;
    float c_centre = 0.0, c_reference = 0.0;
    vec2  uv = vec2(0.0);

    for (int k = 0; k < N_TAPS; ++k)
    {
        float d = float(k - demi);
        vec2  p = base + d * dh;
        float c = composite_en(p);

        float ch;
        if (u_separateur == 0)
        {
            // Le peigne PAL utilise DEUX lignes de retard, pas une. La
            // sous-porteuse n'avance que de 270,576° par ligne, ce qui ne
            // convient pas ; mais sur deux lignes cela fait 541,15°, soit
            // 181,15° modulo un tour — assez proche de l'inversion pour que
            // la soustraction annule la luminance.
            float reference = composite_en(p - 2.0 * dv);
            ch = 0.5 * (c - reference);
            if (k == demi) { c_centre = c; c_reference = reference; }
        }
        else
        {
            ch = c;
        }

        float ph = phase(base.x + d / u_taille.x, ligne);
        uv += u_noyau_dec[k] * 2.0 * ch * vec2(sin(ph), cos(ph));
    }

    float y = (u_separateur == 0) ? 0.5 * (c_centre + c_reference)
                                  : luminance_piegee(base, dh);

    // Le récepteur, prévenu par le burst oscillant (135° ou 225°), rétablit
    // le signe avant toute moyenne.
    uv.y *= signe_pal(ligne);

    return vec3(y, uv);
}

void main()
{
    vec2  dh    = pas_h();
    vec2  dv    = pas_v();
    float ligne = floor(v_uv.y * u_taille.y);

    vec3 courante = demoduler_ligne(v_uv, ligne, dh, dv);
    vec2 uv = courante.yz;

    if (u_ligne_retard == 1)
    {
        // PAL-D. La moyenne des deux lignes annule l'erreur de phase, au prix
        // de la moitié de la résolution chromatique verticale. Sans elle,
        // c'est le PAL-S des premiers récepteurs, et les barres de Hanover
        // apparaissent dès que la phase dérive.
        vec3 precedente = demoduler_ligne(v_uv - dv, ligne - 1.0, dh, dv);
        uv = 0.5 * (uv + precedente.yz);
    }

    float y = (courante.x - u_piedestal) / (1.0 - u_piedestal);
    uv *= u_saturation / (1.0 - u_piedestal);

    sortie = vec4(eotf(clamp(yuv_vers_rgb(y, uv), 0.0, 1.0)), 1.0);
}

#endif
