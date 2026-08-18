# La radio : de l'émetteur au haut-parleur

### AM, FM, bande latérale unique — et ce que le matériel fait au son

---

Ce document accompagne `radio/`, le pendant sonore du simulateur de télévision.
Le principe est le même, et c'est le seul qui vaille : **on reconstruit le signal
réellement transmis**, on lui fait traverser un canal bruité, et on le démodule
comme le ferait le poste. Ce qu'on entend n'est pas un effet appliqué à un
fichier ; c'est ce qui ressort de la démodulation.

**Table des matières**

1. [Pourquoi l'enveloppe complexe](#1-pourquoi-lenveloppe-complexe)
2. [Les sept services](#2-les-sept-services)
3. [Les trois modulations](#3-les-trois-modulations)
4. [Le canal](#4-le-canal)
5. [Ce que la modulation de fréquence achète, et à quel prix](#5-ce-que-la-modulation-de-fréquence-achète-et-à-quel-prix)
6. [Le poste : compresseur, silencieux, haut-parleur](#6-le-poste--compresseur-silencieux-haut-parleur)
7. [Ce qui n'est pas simulé](#7-ce-qui-nest-pas-simulé)

---

## 1. Pourquoi l'enveloppe complexe

Simuler une porteuse à 446 mégahertz en échantillonnant la sinusoïde demanderait
un milliard de points par seconde. Et cela n'apprendrait rien de plus : **la
fréquence de la porteuse n'intervient nulle part** dans ce qui ressort du
démodulateur. Elle décide de la propagation et de l'encombrement du spectre, pas
du son.

On travaille donc sur l'**enveloppe complexe**, ce que les récepteurs à
définition logicielle appellent I/Q :

$$x(t) = \mathrm{Re}\big\{ s(t)\, e^{j 2\pi f_p t} \big\}$$

$s(t)$ porte toute l'information. Son module est l'amplitude instantanée, son
argument la phase. La modulation d'amplitude agit sur le module, celle de
fréquence sur la dérivée de l'argument, la bande latérale unique sur les deux à
la fois. Ce n'est pas une approximation commode : c'est la **représentation
exacte** d'un signal à bande étroite.

Une conséquence pratique qu'il faut avoir en tête : une enveloppe complexe
échantillonnée à $f$ couvre **toute** la bande de $-f/2$ à $+f/2$, et non la
moitié comme un signal réel. Un canal FM de 180 kHz tient donc dans 288
kilo-points par seconde — jouable, et mesuré à dix-huit fois le temps réel.

## 2. Les sept services

| service | modulation | canal | largeur occupée | β | gain FM | simulé à |
|---|---|---|---|---|---|---|
| Radiodiffusion AM, ondes moyennes | AM | 9,00 kHz | 9,0 kHz | — | — | 48 kHz |
| Radiodiffusion FM, mono | FM | 100,00 kHz | 180,0 kHz | 5,00 | +26,5 dB | 288 kHz |
| CB 27 MHz, AM | AM | 10,00 kHz | 6,0 kHz | — | — | 48 kHz |
| CB 27 MHz, bande latérale unique | BLU | 10,00 kHz | 2,7 kHz | — | — | 48 kHz |
| Talkie-walkie PMR446 | FM | 12,50 kHz | 11,0 kHz | 0,83 | +5,8 dB | 48 kHz |
| VHF marine | FM | 25,00 kHz | 16,0 kHz | 1,67 | +13,5 dB | 48 kHz |
| VHF aéronautique | AM | 25,00 kHz | 5,4 kHz | — | — | 48 kHz |

La largeur occupée est celle de **Carson**, $B = 2(\Delta f + W)$ : non pas une
approximation commode, mais la bande qui contient 98 % de la puissance, et celle
que les régulateurs ont retenue pour allouer les canaux.

### Ce qui est réglementaire, et ce qui est d'usage

La distinction compte, et elle est faite service par service dans le code.

Sont **réglementaires**, c'est-à-dire fixés par un texte : les bandes de
fréquences, l'espacement des canaux, l'excursion maximale en modulation de
fréquence, la puissance maximale, le type de modulation.

Sont **d'usage** — mesurés sur du matériel, ou simplement la pratique
courante — la bande audio réelle des postes, le taux de compression des
modulateurs, la constante de temps de préaccentuation des services mobiles, et
la réponse du haut-parleur. Ce sont eux qui font qu'un talkie-walkie *sonne*
comme un talkie-walkie, et ils sont donc tous réglables.

### Pourquoi l'aéronautique est en amplitude

C'est la question que tout le monde pose, et la réponse est une décision de
sécurité, pas un archaïsme.

En modulation de fréquence, deux stations qui émettent en même temps produisent
l'**effet de capture** : la plus forte efface complètement l'autre, et personne
ne sait qu'il y a eu collision. En modulation d'amplitude, les deux porteuses
battent l'une contre l'autre et l'on entend un sifflement — le contrôleur *sait*
que deux avions ont parlé ensemble, et redemande.

Le simulateur le produit par le calcul : on additionne deux nombres complexes,
et le sifflement sort du module. Sa fréquence est **l'écart des deux
émetteurs**, ce que vérifie `tests/test_radio.py` à trois écarts différents. Il
suffit de comparer, dans l'application, la VHF aéronautique et la VHF marine
avec le même réglage de seconde station : c'est tout le sujet en dix secondes.

## 3. Les trois modulations

### Amplitude

$$s(t) = 1 + m\, a(t)$$

Le « 1 » est la porteuse, et c'est elle qui coûte les deux tiers de la puissance
d'un émetteur AM pour ne transporter aucune information. C'est le prix d'un
détecteur d'enveloppe à une diode — et c'est ce prix qui a mis un poste dans
chaque foyer.

La démodulation est le module, littéralement ce que fait une diode suivie d'un
condensateur. D'où une propriété que le simulateur **n'a pas eu à programmer** :
au-delà de $m = 1$, l'enveloppe passe par zéro et repart négative ; le module la
replie, et fabrique une distorsion massive. C'est le son de la CB poussée à
fond, et le curseur de niveau de modulation permet de l'entendre plutôt que de
l'interdire.

### Fréquence

$$s(t) = \exp\Big( j 2\pi \Delta f \int a(\tau)\,d\tau \Big)$$

Le module vaut 1 partout : **une porteuse FM a une amplitude constante**. De là
vient son immunité, et de là vient que le récepteur puisse la faire passer par
un limiteur avant le discriminateur sans rien perdre — en supprimant du même
coup tout le bruit qui se trouvait dans l'amplitude.

Le discriminateur prend la dérivée de l'argument par différence de phase :

$$a(t) = \arg\big( s(t)\, \overline{s(t-T)} \big) \cdot \frac{f_e}{2\pi \Delta f}$$

Écrire `diff(angle(s))` serait le piège classique : l'argument saute de $+\pi$ à
$-\pi$ à chaque tour, et la dérivée y verrait une impulsion géante. Le produit
par le conjugué donne directement l'écart, déjà ramené dans $(-\pi, +\pi]$ —
c'est exactement ce que fait un discriminateur à quadrature.

### Bande latérale unique

$$s(t) = a(t) \pm j\,\mathcal{H}\{a\}(t)$$

Ni porteuse ni seconde bande latérale : toute la puissance est dans la parole.
Le transformateur de Hilbert est un filtre à réponse impulsionnelle finie de 255
coefficients, et la voie en phase passe par un retard pur de même longueur —
sans quoi les deux voies ne seraient pas en quadrature et la bande indésirable
réapparaîtrait à pleine puissance.

**Et c'est là que la BLU se distingue de tout le reste.** En AM comme en FM, une
erreur d'accord de cent hertz ne s'entend pas. Ici, elle décale l'intégralité du
spectre audio de cent hertz — pas d'un facteur, d'un *décalage* : les
harmoniques cessent d'être des multiples de la fondamentale, et la voix prend ce
timbre métallique que les cibistes appellent Donald. C'est pour cela qu'un poste
BLU a un bouton d'accord fin, et qu'on l'entend tourner jusqu'à ce que la voix
redevienne humaine. Mesuré à trois désaccords, le pic se déplace exactement de
la valeur demandée.

## 4. Le canal

### Le bruit, et où on le mesure

Le point délicat de tout le module. **Le rapport porteuse/bruit se définit dans
la bande du récepteur**, pas dans celle de la simulation : le bruit thermique
est blanc, donc sa puissance est proportionnelle à la largeur où on le mesure,
et l'enveloppe complexe est échantillonnée bien plus large que le canal.

$$\sigma^2 = P_c \cdot 10^{-\frac{C/N}{10}} \cdot \frac{f_{\text{travail}}}{B_{\text{récepteur}}}$$

On injecte donc un bruit plus fort qu'il n'y paraît, pour qu'après le filtre de
fréquence intermédiaire il reste exactement ce qui était demandé. La conséquence
déroute au premier abord — rétrécir le filtre n'*améliore* pas le rapport
annoncé, il le maintient — et c'est justement ce qui rend la mesure honnête :
deux récepteurs de largeurs différentes rendent le même son au même C/N annoncé.

Ce que l'on gagne à rétrécir, c'est de la portée à densité de bruit donnée.

### Évanouissement

Deux trajets qui arrivent avec des retards différents s'additionnent parfois en
phase, parfois en opposition. Quand la bande du signal est étroite devant
l'inverse de l'écart de retard, tout le canal monte et descend ensemble : c'est
l'évanouissement **plat**, celui d'un poste mobile qui roule ou d'une liaison
décamétrique qui rebondit sur l'ionosphère.

On le simule pour ce qu'il est : un processus gaussien complexe filtré passe-bas
à la fréquence Doppler. Le module d'un tel processus suit une loi de Rayleigh,
ce qui est le résultat classique — et il n'a pas fallu l'écrire, il tombe du
filtrage.

### Parasites atmosphériques

Le bruit atmosphérique n'est pas gaussien, et c'est tout ce qui le distingue :
il est **impulsionnel**. Un éclair à mille kilomètres met dans l'antenne une
impulsion large bande dont le poste ne garde que ce qui tient dans son canal —
soit une brève oscillation amortie. On tire donc des instants d'arrivée selon
une loi de Poisson, et l'on y place des impulsions à décroissance exponentielle.

Un souffle se supporte. Un craquement fait sursauter. C'est la signature des
ondes moyennes et du 27 MHz, et elle ne s'entend pas du tout comme du bruit
blanc.

## 5. Ce que la modulation de fréquence achète, et à quel prix

Rapport signal/bruit **de sortie**, mesuré sur un ton à 1 kHz, en fonction du
rapport porteuse/bruit **d'entrée** :

| C/N | AM (OM) | CB AM | aéro | CB BLU | PMR446 | marine | FM radio |
|---|---|---|---|---|---|---|---|
| 0 dB | −9,9 | −7,1 | −8,1 | −5,8 | −8,7 | −2,4 | +4,9 |
| 5 | −3,7 | −0,9 | −1,9 | −1,1 | +6,3 | +10,2 | +19,1 |
| 10 | +1,6 | +4,4 | +3,3 | +3,7 | +15,6 | +25,7 | +38,5 |
| 15 | +6,7 | +9,4 | +8,4 | +8,5 | +20,7 | +30,8 | +43,6 |
| 20 | +11,7 | +14,5 | +13,5 | +13,5 | +25,8 | +35,8 | +48,7 |
| 30 | +21,8 | +24,5 | +23,5 | +23,4 | +35,8 | +45,8 | +58,7 |
| 40 | +31,8 | +34,5 | +33,5 | +33,4 | +45,8 | +55,8 | +68,7 |

Trois choses à lire dans ce tableau, et toutes trois sont des lois, pas des
réglages.

**Un — l'AM ne gagne rien.** Les quatre colonnes de gauche montent d'exactement
un décibel par décibel, avec un décalage constant : la démodulation d'enveloppe
ne fait aucune faveur au signal. Le décalage vient de la part de puissance qui
part dans la porteuse plutôt que dans les bandes latérales.

**Deux — la FM gagne ce que sa largeur de bande lui coûte.** À C/N de 20 dB, le
talkie fait douze décibels de mieux qu'une AM de même encombrement, la marine
vingt-deux, la radiodiffusion trente-cinq. L'ordre est celui des indices de
modulation, et c'est la formule $G = 3\beta^2(\beta+1)$ qui le dit.

**Trois — la FM s'effondre.** Regardez la colonne de droite entre 0 et 10 dB :
elle monte de 33 décibels pour 10 d'entrée. C'est le **seuil**, et il n'a pas
été programmé. Quand le bruit devient comparable à la porteuse, le vecteur somme
passe de temps en temps de l'autre côté de l'origine ; l'écart de phase fait
alors un tour complet, et le discriminateur sort une impulsion. Ce sont les
craquements qu'on entend juste avant qu'une station lointaine ne décroche —
et ils sortent de la formule du discriminateur, pas d'un générateur de clics.

## 6. Le poste : compresseur, silencieux, haut-parleur

Ces trois-là ne changent rien à la théorie, et tout à ce qu'on entend.

**Le compresseur.** Un émetteur de radiodiffusion en met quelques décibels pour
tenir sa modulation ; un poste de communication en met quinze, parce que ce qui
compte n'est pas la fidélité mais que le mot arrive. C'est ce qui donne aux
talkies leur niveau constant, leur souffle de fond remonté entre les syllabes,
et leur fatigue à l'écoute prolongée.

**Le niveau de modulation.** Il compte d'autant plus que la préaccentuation est
forte : à 750 µs — la valeur des services mobiles — un kilohertz ressort
**treize décibels et demi plus haut** qu'il n'est entré. Régler l'entrée comme
en radiodiffusion enverrait le limiteur dans ses butées à chaque syllabe.
Mesuré, sur un ton à 1 kHz en PMR446 et canal parfait : 23 dB de rapport
signal/bruit à niveau 0,70 — c'est de la distorsion pure — contre 48 dB à 0,15.

**Le silencieux.** Il écoute le **souffle**, pas la porteuse, et c'est le vrai
mécanisme. Un récepteur FM sans signal sort un bruit qui monte jusqu'au bout de
sa bande ; avec un signal, la porteuse capture le discriminateur et ce bruit
s'écroule. On mesure donc entre 5 et 7 kilohertz, là où il n'y a jamais de
parole : fort = pas de signal, faible = signal présent. Le fameux « pschit » de
fin de transmission en découle sans qu'on ait rien à ajouter — quand l'émetteur
relâche l'alternat, le souffle revient avant que le circuit n'ait eu le temps de
refermer.

**Le haut-parleur**, enfin, fait la moitié du caractère d'un poste. Un
talkie-walkie ne sonne pas comme un talkie-walkie à cause de sa modulation : un
fichier simplement filtré entre 300 et 3000 Hz n'y ressemble pas. C'est le
transducteur de trente-six millimètres monté dans un boîtier plastique fermé —
il ne descend pas, il résonne à onze cents hertz, et il s'éteint vite.

| poste | bande | résonance |
|---|---|---|
| transducteur 36 mm en boîtier (talkie) | 450 – 4000 Hz | 1100 Hz, +9 dB |
| haut-parleur 66 mm de tableau de bord (CB, marine) | 300 – 5000 Hz | 800 Hz, +6 dB |
| casque aviation, écouteur fermé | 280 – 4500 Hz | 900 Hz, +4 dB |
| haut-parleur 130 mm en coffret bois (poste à lampes) | 120 – 4500 Hz | 300 Hz, +5 dB |
| sortie de ligne (tuner FM) | 30 – 20000 Hz | aucune |

La case « écouter par le haut-parleur du poste » se décoche : l'écart entre les
deux est saisissant, et il dit à quel point le transducteur fait le son.

## 7. Ce qui n'est pas simulé

Il vaut mieux le dire que de le laisser deviner.

- **La stéréophonie FM.** Le multiplex à 38 kHz, son pilote à 19 kHz et les
  vingt-trois décibels de rapport signal/bruit qu'il coûte ne sont pas encore
  écrits. Le service `fm-mono` est donc bien mono, et il ne prétend rien d'autre.
- **Le RDS**, qui vit sur la même porteuse à 57 kHz.
- **Les tonalités CTCSS** des talkies, ces sous-porteuses de 67 à 250 Hz qui
  ouvrent le silencieux d'un groupe et pas d'un autre.
- **La propagation** : rien ici ne calcule une portée, une hauteur d'antenne ou
  un bilan de liaison. Le rapport porteuse/bruit est un réglage, pas un résultat.
- **L'effet de capture FM** n'est présent que sous la forme où il tombe du
  calcul — deux porteuses FM s'additionnent bien, et la plus forte l'emporte —
  mais aucun récepteur à boucle à verrouillage de phase n'est modélisé.
- **Le codec MP3 de la source** : ce qui entre a déjà été compressé par
  quelqu'un d'autre, et ce simulateur n'y peut rien.

> **Dans le code** — `radio/services.py` pour la table, `radio/modulation.py`
> pour les trois modulations, `radio/canal.py` pour le bruit et les voisins,
> `radio/chaine.py` pour l'enchaînement complet, `radio/app.py` pour la fenêtre.
> `tests/test_radio.py` vérifie chaque loi citée dans ce document.
