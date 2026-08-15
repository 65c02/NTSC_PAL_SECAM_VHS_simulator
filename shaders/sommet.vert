#version 330 core

// Triangle plein écran, sans le moindre tampon de sommets.
//
// Trois sommets suffisent à couvrir l'écran, et un triangle unique vaut mieux
// que deux : le GPU rasterise par tuiles de 2x2 fragments, et la diagonale
// d'un quad fait calculer deux fois les fragments qui la chevauchent.
// Les coordonnées sont déduites de gl_VertexID, donc aucun attribut, aucun
// VBO, aucun transfert.

out vec2 v_uv;

void main()
{
    vec2 coin = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = coin;
    gl_Position = vec4(coin * 2.0 - 1.0, 0.0, 1.0);
}
