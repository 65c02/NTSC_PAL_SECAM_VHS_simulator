// ===========================================================================
//  SECAM — modulation de FRÉQUENCE, séquentielle, à mémoire de ligne.
//
//  C'est le shader difficile, et pour une raison précise : en modulation de
//  fréquence, la phase est l'INTÉGRALE du signal modulant depuis le début de
//  la ligne. Or un fragment shader ne connaît que son propre pixel. Aucune
//  formule locale n'a pour dérivée le signal modulant — il faut réellement
//  l'intégrale.
//
//  D'où le découpage en trois temps :
//
//    1. PASSE_PREPARATION  calcule, pour chaque échantillon, la luminance et
//                          l'écart de fréquence de la composante que cette
//                          ligne transporte ;
//    2. scan.frag          somme cet écart depuis le début de la ligne, par
//                          doublement récursif — dix passes minuscules ;
//    3. PASSE_CODAGE       synthétise la sous-porteuse à partir de la phase
//                          ainsi intégrée, et l'ajoute à la luminance.
//
//  Le décodage emploie ensuite un vrai discriminateur à quadrature. Ni le
//  cross-color, ni le « feu » à faible rapport signal/bruit, ni l'immunité au
//  gain ne sont ajoutés à la main : ils tombent du calcul, comme dans le
//  simulateur de référence.
// ===========================================================================

// Vrai sur les lignes qui transportent D'R, faux sur celles qui portent D'B.
bool ligne_rouge(float ligne) { return mod(ligne, 2.0) >= 0.5; }

// Préaccentuation haute fréquence, dite « filtre cloche ».
//
// Courbe en cloche INVERSÉE : minimum à f0, remontée de part et d'autre. Plus
// la couleur est proche du gris, plus la fréquence instantanée est proche du
// repos, et plus la sous-porteuse est atténuée. Sans elle, un mur blanc
// afficherait un motif de sous-porteuse parfaitement visible — en SECAM la
// porteuse est émise en permanence, saturée ou non.
//
// La formule normative diverge loin de f0 ; on la borne à la bande que la voie
// chrominance occupe réellement, ce qu'un vrai codeur fait avec son filtre
// passe-bande d'entrée.
float gain_cloche(float f)
{
    float F  = f / u_secam_f0 - u_secam_f0 / max(f, 1.0);
    float g  = sqrt((1.0 + 256.0 * F * F) / (1.0 + 1.5876 * F * F));
    float ga = smoothstep(2.75e6, 3.20e6, f) * (1.0 - smoothstep(5.50e6, 5.95e6, f));
    return g * ga;
}

// Phase de la sous-porteuse SECAM. Contrairement au NTSC et au PAL, la
// fréquence de repos dépend de la ligne — d'où le calcul explicite plutôt que
// l'uniforme `u_cycles_actifs`.
float phase_secam(float x, float ligne, float f_repos, float integrale_cycles)
{
    float cycles = u_phase_image
                 + fract(u_frac_ligne * ligne)
                 + fract((f_repos / u_f_ech) * x)
                 + integrale_cycles;
    return DEUX_PI * fract(cycles);
}

// ===========================================================================
#ifdef PASSE_PREPARATION

void main()
{
    vec2  dh    = pas_h();
    float ligne = floor(v_uv.y * u_taille.y);
    int   demi  = N_TAPS / 2;
    bool  rouge = ligne_rouge(ligne);

    float y = 0.0;
    vec2  drdb = vec2(0.0);

    for (int k = 0; k < N_TAPS; ++k)
    {
        float d   = float(k - demi);
        vec3  rgb = oetf(texture(u_source, v_uv + d * dh).rgb);
        vec2  kd  = vers_drdb(rgb);

        y      += u_noyau_luma[k] * luma(rgb);
        drdb.x += u_noyau_c2[k]   * kd.x;   // D'R
        drdb.y += u_noyau_c1[k]   * kd.y;   // D'B
    }

    // Séquentiel : on jette une composante sur deux. Le récepteur retrouvera
    // la manquante dans sa mémoire de ligne — mais la résolution chromatique
    // verticale est bel et bien divisée par deux, et cela ne se rattrape pas.
    float composante = rouge ? drdb.x : drdb.y;
    float deviation  = rouge ? u_secam_dev.y : u_secam_dev.x;

    float ecart = clamp(composante * deviation,
                        u_secam_butees.x, u_secam_butees.y);

    // On range l'écart en CYCLES PAR ÉCHANTILLON plutôt qu'en hertz : la somme
    // préfixe qui suit reste alors dans les dizaines, là où des hertz
    // atteindraient la centaine de millions et mangeraient la précision.
    sortie = vec4(ecart / u_f_ech, y, 0.0, 1.0);
}

// ===========================================================================
#elif defined(PASSE_CODAGE)

void main()
{
    float ligne = floor(v_uv.y * u_taille.y);
    bool  rouge = ligne_rouge(ligne);

    vec2  prepare  = texture(u_prepare, v_uv).rg;
    float ecart    = prepare.r * u_f_ech;      // en hertz
    float y        = prepare.g;
    float integrale = texture(u_scan, v_uv).r; // en cycles

    float f_repos = rouge ? u_secam_repos.y : u_secam_repos.x;
    float f_inst  = f_repos + ecart;

    float x = v_uv.x * u_taille.x;
    // La non-linéarité de l'émetteur agit ici comme un retard dépendant du
    // niveau. Le SECAM y est insensible dans les aplats — un retard constant
    // ne change pas une fréquence — et ne s'en ressent qu'aux contours de
    // luminance. C'est exactement le comportement réel, et il n'a rien d'un
    // traitement de faveur : c'est le même canal pour les trois normes.
    float phi = phase_secam(x, ligne, f_repos, integrale) + u_phase_diff * y;

    float amplitude = u_amplitude_chroma * gain_cloche(f_inst) / u_secam_gain_max;
    float signal = u_piedestal + (1.0 - u_piedestal) * (y + amplitude * cos(phi));

    if (u_bruit > 0.0)
        signal += u_bruit * bruit_video(v_uv * u_taille);

    sortie = vec4(signal, 0.0, 0.0, 1.0);
}

// ===========================================================================
#else   // décodage

// Discriminateur de fréquence à quadrature, tel que décrit au cours §9.6.
//
// On ramène la sous-porteuse en bande de base avec un oscillateur local calé
// sur la fréquence de repos, en phase puis en quadrature ; l'écart de
// fréquence est alors la dérivée de l'argument du vecteur complexe obtenu.
//
// Astuce de coût : les deux positions dont on a besoin pour dériver, x et
// x+1, partagent presque tous leurs échantillons. Une seule boucle les
// alimente donc toutes les deux, avec un décalage d'indice sur le noyau —
// N+1 lectures au lieu de 2N.
//
// La boucle compte bien N_TAPS+1 tours, et ce détail est vital : à N tours,
// l'accumulateur de x+1 perdrait son dernier coefficient. Son noyau devenant
// asymétrique, il introduirait un déphasage propre — exactement la grandeur
// que l'on cherche à mesurer. Avec treize coefficients, ce biais suffisait à
// faire décrocher complètement le discriminateur.
//
// Prendre l'argument revient à ignorer le module : c'est le limiteur, gratuit,
// et c'est de là que vient l'insensibilité du SECAM au gain.
vec2 discriminer(vec2 base, float ligne, vec2 dh)
{
    int   demi  = N_TAPS / 2;
    bool  rouge = ligne_rouge(ligne);
    float f_repos = rouge ? u_secam_repos.y : u_secam_repos.x;
    float deviation = rouge ? u_secam_dev.y : u_secam_dev.x;

    vec2 a = vec2(0.0), b = vec2(0.0);

    for (int k = 0; k <= N_TAPS; ++k)
    {
        float d = float(k - demi);
        float c = composite_en(base + d * dh);

        float x  = base.x * u_taille.x + d;
        float ph = phase_secam(x, ligne, f_repos, 0.0);
        vec2  osc = 2.0 * c * vec2(cos(ph), -sin(ph));

        if (k < N_TAPS) a += u_noyau_dec[k]     * osc;
        if (k >= 1)     b += u_noyau_dec[k - 1] * osc;
    }

    // arg(b . conj(a)), c'est-à-dire l'avance de phase d'un échantillon.
    float dphi = atan(b.y * a.x - b.x * a.y, b.x * a.x + b.y * a.y);

    // La fenêtre du passe-bande borne ce que le discriminateur peut voir ;
    // au-delà il décroche, et c'est ce décrochage qui produit les taches
    // colorées vives du « feu » SECAM.
    float ecart = clamp(dphi / DEUX_PI * u_f_ech, -1.0e6, 1.0e6);

    return vec2(ecart / deviation, luminance_piegee(base, dh));
}

void main()
{
    vec2  dh    = pas_h();
    vec2  dv    = pas_v();
    float ligne = floor(v_uv.y * u_taille.y);

    vec2 courante   = discriminer(v_uv, ligne, dh);
    vec2 precedente = discriminer(v_uv - dv, ligne - 1.0, dh);

    // Mémoire de ligne : chaque ligne n'apporte qu'une composante, l'autre
    // vient de la précédente, conservée dans le retard de 64 µs.
    bool rouge = ligne_rouge(ligne);
    vec2 drdb = rouge ? vec2(courante.x, precedente.x)
                      : vec2(precedente.x, courante.x);

    float y = (courante.y - u_piedestal) / (1.0 - u_piedestal);
    drdb *= u_saturation / (1.0 - u_piedestal);

    sortie = vec4(eotf(clamp(ydrdb_vers_rgb(y, drdb), 0.0, 1.0)), 1.0);
}

#endif
