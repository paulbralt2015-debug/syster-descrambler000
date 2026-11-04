# Twins Video Player 2 (version native)

Lecteur vidéo de bureau écrit en Python (PySide6 + libmpv). Aucune page web.

## Fonctions
- Liste de lecture (glisser-déposer, réordonner), reprise de lecture, marque-pages, sous-titres, boucle A-B,
  capture d'image, image par image, vitesse, plein écran, mots bloqués.
- Audio : Dolby Surround, Pro Logic, Pro Logic II (Movie / Music / Matrix) par matrice, upmix 5.1 FFmpeg,
  stéréo élargie, basses, salle, sortie casque ou 5.1.
- Vidéo : conversion PAL / SECAM / NTSC en direct, et export MP4 réel.

## Lancer depuis les sources
```
pip install -r requirements.txt
python twins_player.py [fichiers...]
```
libmpv est requise : `mpv-2.dll` à côté du script (Windows), `libmpv2` (Linux), `brew install mpv` (macOS).

## Obtenir le .exe
Onglet **Actions** → « Build Windows exe » → **Run workflow**, ou `git tag v2.0.0 && git push --tags`.

## Limites
Le décodage Pro Logic II est une approximation matricielle (sans logique de direction adaptative).
