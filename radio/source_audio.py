"""
Lecture des fichiers audio, et écriture des exports.

Le décodage passe par PyAV, déjà présent pour le lecteur vidéo : il ouvre les
MP3, les WAV, les FLAC, les M4A et tout ce que FFmpeg sait lire, ce qui évite
d'ajouter une dépendance pour un usage que l'on a déjà.

Le fichier est décodé **en entier** au chargement, ramené en monophonie et à
48 kHz. Un morceau de cinq minutes tient dans cent quinze mégaoctets de
flottants, et cela simplifie tout le reste : le déplacement dans le morceau
devient un simple indice, et le fil de lecture n'a plus qu'à découper.
"""

from __future__ import annotations

import wave
from pathlib import Path

import av
import numpy as np
from scipy import signal as sig

from .services import F_AUDIO


def charger(chemin: str | Path) -> np.ndarray:
    """Décode un fichier audio en monophonie 48 kHz, normalisé.

    La monophonie n'est pas une facilité : **aucun des services simulés n'est
    stéréophonique.** Une CB, un talkie, une VHF marine ou aéronautique
    transportent une voie et une seule, et la radiodiffusion FM stéréophonique
    n'est pas encore implémentée ici — le multiplex à 38 kHz reste à écrire.
    Mélanger les deux voies est donc ce que ferait le pupitre de l'émetteur.
    """
    chemin = str(chemin)
    with av.open(chemin) as conteneur:
        flux = next((f for f in conteneur.streams if f.type == "audio"), None)
        if flux is None:
            raise ValueError(f"aucune piste audio dans {chemin!r}")

        rendu = av.AudioResampler(format="fltp", layout="mono", rate=F_AUDIO)
        morceaux = []
        for paquet in conteneur.demux(flux):
            for trame in paquet.decode():
                for sortie in rendu.resample(trame):
                    morceaux.append(sortie.to_ndarray().reshape(-1).copy())
        for sortie in rendu.resample(None):
            morceaux.append(sortie.to_ndarray().reshape(-1).copy())

    if not morceaux:
        raise ValueError(f"aucun échantillon décodé dans {chemin!r}")

    audio = np.concatenate(morceaux).astype(np.float64)
    # On normalise à −3 dBFS : le niveau d'entrée du modulateur est un réglage
    # de la chaîne, et il n'a de sens que si la source est calibrée.
    crete = float(np.max(np.abs(audio)))
    if crete > 0.0:
        audio = audio / crete * 0.71
    return audio


def ecrire_wav(chemin: str | Path, audio: np.ndarray) -> None:
    """Écrit un WAV 16 bits, sans dépendance supplémentaire."""
    echantillons = np.clip(np.asarray(audio, dtype=np.float64), -1.0, 1.0)
    entiers = (echantillons * 32_767.0).astype("<i2")
    with wave.open(str(chemin), "wb") as fichier:
        fichier.setnchannels(1)
        fichier.setsampwidth(2)
        fichier.setframerate(F_AUDIO)
        fichier.writeframes(entiers.tobytes())


def ecrire_mp3(chemin: str | Path, audio: np.ndarray, debit: str = "192k") -> None:
    """Encode en MP3 par PyAV.

    Le débit par défaut est généreux à dessein : ce qu'on encode ici est déjà
    passé par un canal radio, et il serait dommage d'ajouter les défauts d'un
    codec à ceux qu'on a simulés exprès.
    """
    echantillons = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    with av.open(str(chemin), mode="w") as conteneur:
        flux = conteneur.add_stream("mp3", rate=F_AUDIO)
        flux.bit_rate = int(debit.rstrip("k")) * 1000
        # `s16p` : l'encodeur MP3 de FFmpeg veut des entiers planaires.
        entiers = (echantillons * 32_767.0).astype(np.int16).reshape(1, -1)
        taille = 1152 * 8
        for debut in range(0, entiers.shape[1], taille):
            bloc = np.ascontiguousarray(entiers[:, debut : debut + taille])
            trame = av.AudioFrame.from_ndarray(bloc, format="s16p", layout="mono")
            trame.rate = F_AUDIO
            for paquet in flux.encode(trame):
                conteneur.mux(paquet)
        for paquet in flux.encode(None):
            conteneur.mux(paquet)


def reponse_en_frequence(sos_ou_none, f_ech: float = F_AUDIO, points: int = 512):
    """(fréquences, gain en dB) d'un filtre en sections du second ordre."""
    if sos_ou_none is None:
        frequences = np.linspace(20.0, f_ech / 2.0, points)
        return frequences, np.zeros_like(frequences)
    frequences, reponse = sig.sosfreqz(sos_ou_none, worN=points, fs=f_ech)
    return frequences, 20.0 * np.log10(np.maximum(np.abs(reponse), 1e-6))
