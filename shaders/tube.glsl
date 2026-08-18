// ===========================================================================
//  La caméra — le tube analyseur, sa rémanence et sa queue de comète.
//
//  Modèle complet dans `tvcolor/tube.py` ; on ne redonne ici que ce qu'il faut
//  pour lire le code, et les précautions propres à la carte graphique.
//
//  Une cible photoconductrice accumule la charge que la lumière lui soutire.
//  Un faisceau d'électrons la balaie et la recharge ; le courant qu'il faut
//  pour cela EST le signal vidéo. Le faisceau a un débit maximal, et la cible
//  une capacité : un reflet spéculaire les dépasse tous deux, et met plusieurs
//  trames à s'évacuer. C'est la queue de comète.
//
//      q       = min( q_reste + L + b, q_max )
//      r(q)    = r_max * q0 / (q + q0)
//      s       = min( q * (1 - r(q)), c )
//      q_reste = q - s
//      signal  = s - b
//
//  TROIS PASSES, et le découpage n'est pas cosmétique :
//
//    1. ÉCLAIREMENT — reconstruit ce que l'objectif dépose vraiment sur la
//       cible : seize points de couverture pour distinguer un éclat de chrome
//       d'un drap blanc.
//    2. PONT — comble ce que l'échantillonnage temporel de la source a laissé
//       vide, en sondant l'éclairement de la passe 1 et la charge précédente.
//    3. SIGNAL  — le courant de faisceau, c'est-à-dire l'image.
//    4. CHARGE  — ce que la cible garde pour la trame suivante.
//
//       Les deux dernières ne lisent plus que deux texels chacune. Avant ce
//       découpage, elles recalculaient l'éclairement toutes les deux.
//
//       Et le pont a SA passe, séparée de l'éclairement, pour une raison qui a
//       coûté cher : tant qu'il calculait lui-même l'éclairement de ses
//       sondages, il le faisait sans la porte de couverture — trop coûteuse à
//       refaire cent vingt-huit fois. Un grand aplat écrêté comptait donc
//       comme un reflet neuf, le pont remplissait vers lui, et le remplissage
//       repassait en charge à l'image suivante : de proche en proche, la tache
//       blanche mangeait l'image. Mesuré : 23 % de blanc à la première image,
//       85 % à la dixième. En lisant la texture de la passe 1, chaque sondage
//       coûte une lecture au lieu de dix-sept, ET voit le même éclairement que
//       le simulateur de référence.
//
//  PREMIÈRE PRÉCAUTION — un shader n'a pas de mémoire. La charge résiduelle
//  vit dans une texture, relue à l'image suivante. C'est la seule passe de ce
//  projet qui garde un état d'une image à l'autre, et il faut donc deux
//  tampons : on ne peut pas lire et écrire la même texture.
//
//  DEUXIÈME PRÉCAUTION — la passe de signal et la passe de charge partagent le
//  même calcul, écrit une seule fois dans `lire()`. Deux versions divergentes
//  de cette formule feraient dériver la traînée du résidu.
//
//  TROISIÈME PRÉCAUTION — la charge n'avance QUE lorsqu'une nouvelle image
//  arrive, et d'autant de TRAMES que la cadence de la source l'exige. Une
//  vidéo à 25 im/s vaut deux trames par image ; l'ignorer faisait durer toutes
//  les traînées deux fois trop longtemps. Cette règle-là est tenue côté Python.
//
//  Les valeurs de `u_source` sont ici prises pour ce qu'elles sont dans tout
//  ce moteur : de la lumière. Le tube précède la correction de gamma, qui est
//  appliquée par la passe de codage.
// ===========================================================================

uniform sampler2D u_source;      // la scène
uniform sampler2D u_charge;      // charge laissée sur la cible à l'image d'avant
uniform sampler2D u_eclairement; // sortie de la passe 1, lue par les passes 2, 3 et 4
uniform sampler2D u_eclairement_avant; // la même, à l'image précédente

uniform vec2  u_taille;          // taille de la cible, en texels
uniform float u_tube_lod;        // mipmap couvrant le tiers du rayon de reflet
uniform vec2  u_tube_rayon;      // ce rayon, en coordonnées de texture

uniform float u_tube_faisceau;   // capacité du faisceau, en blancs par trame
uniform float u_tube_remanence;  // fraction résiduelle maximale
uniform float u_tube_genou;      // charge à laquelle la rémanence est à moitié
uniform float u_tube_charge_max; // saturation de la cible, en blancs
uniform float u_tube_biais;      // lumière de biais
uniform float u_tube_eclat;      // éclairement réel des reflets écrêtés
uniform float u_tube_seuil;      // niveau au-dessous duquel rien n'est amplifié
uniform float u_tube_ecart;      // désalignement des tubes, en fraction d'écran
uniform vec2  u_tube_pont;       // portée du pont temporel, en coordonnées uv
uniform float u_tube_lod_coeur;  // mipmap équivalent au coeur de la tache
uniform float u_tube_lod_voile;  // mipmap équivalent au voile
uniform vec2  u_tube_pas_coeur;  // un texel de ce niveau, en uv
uniform vec2  u_tube_pas_voile;
uniform float u_tube_voile;      // part de l'énergie emportée par le voile
uniform mat3  u_tube_filtres;    // contamination des filtres dichroïques
uniform mat3  u_tube_masquage;   // matrice de masquage de l'électronique

in  vec2 v_uv;
out vec4 sortie;

const float EXPOSANT_REFLET   = 5.0;
// Le seuil de la COUVERTURE est distinct de celui des reflets, et ce n'est pas
// un raffinement mais une correction : les deux étaient le même réglage, si
// bien que relever le seuil des reflets abaissait du même coup ce qui compte
// comme voisinage clair, ouvrait la porte partout, et empirait les choses.
// Même valeur que `tvcolor.tube.SEUIL_COUVERTURE`.
const float SEUIL_COUVERTURE  = 0.75;
const float COUVERTURE_BASSE  = 0.08;
const float COUVERTURE_HAUTE  = 0.22;
const int   POINTS_COUVERTURE = 16;
const int   ECHANTILLONS_PONT = 8;
// Ce qu'un point comblé reçoit, par rapport à ce qu'un dépôt réel lui aurait
// donné. Strictement inférieur à 1, et c'est vital : un point comblé devient à
// l'image suivante une « trace abandonnée » pour ses voisins, qui se comblent à
// leur tour. À gain unité la tache s'étend indéfiniment — mesuré, de 23 % à
// 85 % de l'écran en dix images. À 0,55, la propagation s'éteint en deux ou
// trois générations, ce qui suffit largement à combler un intervalle entre deux
// images de vidéo.
const float GAIN_PONT         = 0.55;

float luminance(vec3 rgb) { return dot(rgb, vec3(0.299, 0.587, 0.114)); }

// Un niveau de mipmap est une moyenne de BOÎTE : sa réponse à un point est un
// carré, et un carré autour de chaque reflet se voit. Quatre prises décalées
// d'un demi-texel de ce niveau, moyennées, transforment la boîte en tente —
// lisse, et presque ronde. Quatre lectures au lieu d'une, et l'ondulation
// angulaire tombe de 292 % à quelques pour-cent.
vec3 tente(sampler2D image, vec2 uv, float niveau, vec2 pas)
{
    vec3 somme = vec3(0.0);
    somme += textureLod(image, uv + vec2(+0.5, +0.5) * pas, niveau).rgb;
    somme += textureLod(image, uv + vec2(-0.5, +0.5) * pas, niveau).rgb;
    somme += textureLod(image, uv + vec2(+0.5, -0.5) * pas, niveau).rgb;
    somme += textureLod(image, uv + vec2(-0.5, -0.5) * pas, niveau).rgb;
    return somme * 0.25;
}

// --------------------------------------------------------------- la scène

// Les trois tubes ne sont jamais réglés exactement l'un sur l'autre, et
// l'erreur est presque toujours une erreur d'échelle : nulle au centre,
// croissante vers les bords. D'où les liserés colorés sur les contours,
// visibles aux coins bien avant de l'être au milieu.
vec3 scene(vec2 uv)
{
    vec3 l;
    if (u_tube_ecart == 0.0) {
        l = texture(u_source, uv).rgb;
    } else {
        vec2 r = uv - 0.5;
        l = vec3(
            texture(u_source, 0.5 + r / (1.0 + u_tube_ecart)).r,
            texture(u_source, uv).g,
            texture(u_source, 0.5 + r / (1.0 - u_tube_ecart)).b
        );
    }
    // Les filtres dichroïques agissent AVANT la cible : c'est le prisme
    // séparateur qui les porte, pas l'électronique. Leurs courbes d'analyse
    // sont forcément tout-positives, alors que les courbes idéales ont des
    // lobes négatifs : chaque voie récolte donc une part de ses voisines, et
    // l'image sort désaturée.
    return max(u_tube_filtres * l, 0.0);
}

// Part du voisinage qui est écrêtée en même temps que le point courant.
//
// C'est ce qui sépare un éclat de chrome d'un drap blanc : les deux sont à
// 100 % dans le fichier, mais le premier occupe un millième de son voisinage
// et le second la moitié. Le simulateur de référence intègre un vrai noyau
// gaussien ; ici on estime la même intégrale par seize points sur deux
// couronnes, chacun lu dans un mipmap qui moyenne déjà sa propre part de
// l'image.
float couverture(vec2 uv)
{
    float marge = max(1.0 - SEUIL_COUVERTURE, 1e-4);
    float somme = 0.0;

    for (int i = 0; i < POINTS_COUVERTURE; ++i)
    {
        float angle = 6.28318530718 * float(i) / float(POINTS_COUVERTURE);
        // Deux couronnes entrelacées, à 0,45 et 0,85 du rayon : les aires
        // qu'elles représentent sont alors à peu près égales.
        float rayon = ((i & 1) == 0) ? 0.45 : 0.85;
        vec2  pas   = rayon * u_tube_rayon * vec2(cos(angle), sin(angle));

        vec3 echantillon = textureLod(u_source, uv + pas, u_tube_lod).rgb;
        somme += clamp((luminance(echantillon) - SEUIL_COUVERTURE) / marge, 0.0, 1.0);
    }
    return somme / float(POINTS_COUVERTURE);
}

// Ce qu'un point ÉMET : son excès, une fois la porte de couverture passée.
//
// L'ORDRE COMPTE, et l'inverse a coûté une transparence. La porte dit si un
// point EST un reflet spéculaire ; l'optique étale ensuite ce que ce reflet
// émet. Étaler d'abord et fermer la porte ensuite laissait l'excès d'une barre
// blanche — que la porte rejetait pourtant en son centre — déborder sur la
// barre voisine, où la porte était ouverte : ΔE*ab de 2,51 à 3,84 sur une mire
// IMMOBILE, alors que rien n'avait bougé.
//
// D'où une passe à part : l'émission se calcule une fois, avec ses seize points
// de couverture, et la diffusion n'a plus qu'à lire le résultat.
vec3 emission(vec2 uv)
{
    float marge = max(1.0 - u_tube_seuil, 1e-4);
    vec3  e = clamp((scene(uv) - u_tube_seuil) / marge, 0.0, 1.0);
    float porte = 1.0 - smoothstep(COUVERTURE_BASSE, COUVERTURE_HAUTE, couverture(uv));
    return porte * pow(e, vec3(EXPOSANT_REFLET));
}

// Éclairement réel de la scène : le fichier a été écrêté par celui qui l'a
// fabriqué, et sans cette reconstruction la cible ne serait jamais en surcharge
// — il n'y aurait donc pas la moindre queue de comète.
//
// `u_eclairement` porte ici l'ÉMISSION calculée par la passe précédente, et
// l'on y applique la tache de diffusion de l'objectif : un cœur étroit, et un
// VOILE large. Sans elle, l'éclairement passait de 0,1 à 26 d'un pixel à
// l'autre : tout saturait la cible, tout traînait aussi longtemps, et la tache
// blanche n'avait aucun dégradé. Une gaussienne seule ne suffit pas non plus —
// elle retombe à rien en trois écarts-types. La lumière parasite d'un zoom de
// reportage, elle, s'étend sur toute l'image.
vec3 eclairement(vec2 uv)
{
    vec3 l = scene(uv);
    if (u_tube_eclat <= 0.0) return l;

    if (u_tube_lod_coeur <= 0.0)
        return l + u_tube_eclat * texture(u_eclairement, uv).rgb;

    // Deux lectures, et pas seize. Une pyramide de mipmaps EST un flou
    // séparable que la carte a déjà calculé ; l'approcher par des couronnes de
    // huit points laissait huit satellites autour de chaque reflet — mesuré,
    // 973 % d'ondulation sur un cercle au rayon du voile, ce qui donnait des
    // motifs blancs sur toute l'image.
    //
    // Un niveau de mipmap est une moyenne de boîte et non une gaussienne : une
    // boîte de largeur L a l'écart-type L/√12, et c'est cette équivalence qui
    // fixe les deux niveaux, calculés côté Python. Le niveau fractionnaire fait
    // que la carte mélange deux tailles de boîte, ce qui adoucit encore.
    vec3 coeur = tente(u_eclairement, uv, u_tube_lod_coeur, u_tube_pas_coeur);
    vec3 voile = tente(u_eclairement, uv, u_tube_lod_voile, u_tube_pas_voile);
    return l + u_tube_eclat * mix(coeur, voile, u_tube_voile);
}

// --------------------------------------------------------------- le pont

// Comble ce que l'échantillonnage temporel de la source a laissé vide.
//
// La cible intègre en continu pendant toute la trame ; une vidéo n'a que
// vingt-cinq images par seconde. Ce qui s'est passé entre deux images N'EST
// PAS DANS LE FICHIER, et la charge se dépose donc par paquets espacés : la
// traînée sort en chapelet. Mesuré sur un reflet de quatre pixels avançant de
// vingt-quatre par image, 21 % de la traînée allumée.
//
// On ne cherche pas le mouvement, on constate son résultat : un point situé
// ENTRE un reflet présent et une trace passée a été traversé. D'où, sur huit
// directions :
//
//     pont = max de  min( max sur +d de « reflet neuf »,
//                         max sur -d de « trace abandonnée » )
//
// Les deux qualificatifs font tout le travail. Sans eux, deux reflets
// IMMOBILES distants de vingt-quatre pixels se retrouvaient reliés par un
// trait purement inventé. On exige donc un reflet ICI qui n'était pas là avant,
// et un reflet qui était LÀ et n'y est plus : un reflet immobile est dans les
// deux images au même endroit, et ne remplit rien.
//
// Le seuil à un blanc, enfin, réserve le pont à la SURCHARGE. Sans lui il
// fuyait sur n'importe quelle image, un pixel sombre se trouvant relevé de
// trois millièmes par le résidu de rémanence de ses voisins.
//
// C'est une interpolation, pas un phénomène. Elle échoue au-delà de sa portée,
// et la traînée y redevient un chapelet — faute de quoi que ce soit à
// interpoler.
vec3 pont(vec2 uv)
{
    vec3 ici = texture(u_eclairement, uv).rgb;
    if (u_tube_pont.x <= 0.0) return ici;

    // Le pont ne lit QUE l'éclairement — celui-ci et celui d'avant — et jamais
    // la charge. C'est structurel, et c'est ce qui l'empêche de s'emballer :
    // un point comblé n'entre dans aucune des deux textures qu'il consulte, et
    // ne peut donc pas devenir la source d'un comblement voisin.

    const vec2 AXES[4] = vec2[4](
        vec2(1.0, 0.0), vec2(0.0, 1.0), vec2(1.0, 1.0), vec2(1.0, -1.0)
    );

    vec3 meilleur = vec3(0.0);
    for (int a = 0; a < 4; ++a)
    {
        for (int signe = -1; signe <= 1; signe += 2)
        {
            vec2 d = float(signe) * AXES[a] * u_tube_pont;
            vec3 devant = vec3(0.0), derriere = vec3(0.0);

            for (int k = 1; k <= ECHANTILLONS_PONT; ++k)
            {
                float t = float(k) / float(ECHANTILLONS_PONT);

                // « neuf » : un reflet ICI qui n'était PAS là à l'image d'avant.
                vec3 loin_ici   = texture(u_eclairement, uv + t * d).rgb;
                vec3 loin_avant = texture(u_eclairement_avant, uv + t * d).rgb;
                devant = max(devant, max(loin_ici - 1.0, 0.0)
                             * clamp(1.0 - loin_avant / u_tube_charge_max, 0.0, 1.0));

                // « abandonné » : un reflet qui était LÀ et qui n'y est plus.
                vec3 pres_ici   = texture(u_eclairement, uv - t * d).rgb;
                vec3 pres_avant = texture(u_eclairement_avant, uv - t * d).rgb;
                derriere = max(derriere, max(pres_avant - 1.0, 0.0)
                               * clamp(1.0 - pres_ici / u_tube_charge_max, 0.0, 1.0));
            }
            meilleur = max(meilleur, min(devant, derriere));
        }
    }

    // Le « + 1 » rend le piédestal que le seuil avait retiré.
    meilleur *= GAIN_PONT;
    return mix(ici, max(ici, meilleur + 1.0), step(1e-6, dot(meilleur, vec3(1.0))));
}

// --------------------------------------------------------------- le faisceau

// Charge évacuée en une trame. Les deux passes appellent CETTE fonction, et
// c'est pour cela qu'elle existe.
vec3 lire(vec3 q)
{
    // Le genou est un uniforme et non une constante, et cela compte : figé, il
    // plafonne le résidu à 0,7 % dans les hautes lumières quelle que soit la
    // rémanence, et tous les tubes finissent par se ressembler. C'est lui qui
    // sépare un vidicon d'un Plumbicon.
    vec3 residu = u_tube_remanence * u_tube_genou / (q + u_tube_genou);
    return min(q * (1.0 - residu), vec3(u_tube_faisceau));
}

void main()
{
#ifdef PASSE_EMISSION

    sortie = vec4(emission(v_uv), 1.0);

#elif defined(PASSE_ECLAIREMENT)

    sortie = vec4(eclairement(v_uv), 1.0);

#elif defined(PASSE_PONT)

    sortie = vec4(pont(v_uv), 1.0);

#else

    // La cible SATURE : sa face arrière ne peut pas remonter au-delà du
    // potentiel de sa face avant, et l'éclairement excédentaire ne dépose plus
    // rien. Sans cette borne, un projecteur resté une seconde dans le champ
    // accumule de quoi traîner quinze secondes derrière lui — mesuré, sur la
    // version qui en manquait.
    vec3 q = min(texture(u_charge, v_uv).rgb
                 + texture(u_eclairement, v_uv).rgb + u_tube_biais,
                 u_tube_charge_max);
    vec3 s = lire(q);

#ifdef PASSE_CHARGE
    sortie = vec4(q - s, 1.0);
#else
    // L'écrêteur de blanc de la caméra : le faisceau encaisse 130 % du blanc,
    // l'amplificateur vidéo n'en a jamais laissé passer autant sur la ligne.
    // C'est pourquoi une traînée est d'un blanc plat, et pourquoi l'image
    // disparaît derrière elle.
    // La matrice de masquage, elle, est APRÈS la cible : c'est de
    // l'électronique. L'ordre compte — entre les deux il y a l'écrêteur de
    // blanc, et la correction ne rattrape donc pas ce qu'il a coupé.
    vec3 signal = clamp(s - u_tube_biais, 0.0, 1.0);
    sortie = vec4(clamp(u_tube_masquage * signal, 0.0, 1.0), 1.0);
#endif

#endif
}
