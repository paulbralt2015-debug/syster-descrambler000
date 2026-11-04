"""Chaînes de filtres FFmpeg (utilisées par libmpv) : surround/Pro Logic et standards TV.
Ce module n'a aucune dépendance : il peut être testé seul."""

AUDIO_MODES = {
    "Stéréo (sans traitement)": "stereo",
    "Stéréo élargie": "wide",
    "Dolby Surround (matriciel)": "dss",
    "Dolby Pro Logic (4 canaux)": "pl",
    "Pro Logic II Movie": "pl2m",
    "Pro Logic II Music": "pl2x",
    "Pro Logic II Matrix": "pl2mx",
    "Upmix 5.1 FFmpeg": "ff",
}
# mode: (poids d'extraction du centre, surround mono ?, niveau surround)
PARAMS = {
    "dss": (0.0, True, 1.0),
    "pl": (1.0, True, 1.0),
    "pl2m": (1.0, False, 1.0),
    "pl2x": (0.7, False, 0.75),
    "pl2mx": (1.0, False, 0.9),
}

STANDARDS = {
    "PAL": dict(fps="25", lines=576, chroma="gblur=sigma=2:sigmaV=0.8:planes=6",
                luma="", sat=1.0, setup=False),
    "SECAM": dict(fps="25", lines=576, chroma="gblur=sigma=2:sigmaV=1.2:planes=6",
                  luma="", sat=0.92, setup=False),
    "NTSC": dict(fps="30000/1001", lines=480, chroma="gblur=sigma=3:sigmaV=0:planes=6",
                 luma="gblur=sigma=0.6:sigmaV=0:planes=1", sat=1.08, setup=True),
}


def is_surround(mode):
    return mode in PARAMS or mode == "ff"


def audio_graph(mode, out51, surround=1.0, center=1.0, delay_ms=15, bass_db=0, reverb=0):
    """Retourne le graphe FFmpeg (sans l'enveloppe lavfi de mpv)."""
    f = []
    if bass_db:
        f.append(f"bass=g={bass_db}:f=120")
    if reverb:
        d = reverb / 100 * 0.5
        f.append(f"aecho=0.9:0.9:50|90|140:{d:.2f}|{d * .7:.2f}|{d * .5:.2f}")
    if mode == "wide":
        f.append(f"stereotools=slev={max(surround, 0.02):.2f}")
    elif mode == "ff":
        f.append("surround=chl_out=5.1")
    elif mode in PARAMS:
        c, mono, sm = PARAMS[mode]
        k = sm * surround
        a, b = 1 - 0.5 * c, -0.5 * c            # avant : FL' = a*FL + b*FR (centre retiré)
        cc = 0.707 * c * center
        if mono:                                 # surround mono (Dolby Surround / Pro Logic)
            bl = br = f"{.707 * k:.3f}*c0{-.707 * k:+.3f}*c1"
            d2 = delay_ms
        else:                                    # surround stéréo (Pro Logic II)
            bl = f"{k:.3f}*c0{-.6 * k:+.3f}*c1"
            br = f"{.6 * k:.3f}*c0{-k:+.3f}*c1"
            d2 = delay_ms + 3
        f.append("pan=5.1|"
                 f"c0={a:.3f}*c0{b:+.3f}*c1|"
                 f"c1={a:.3f}*c1{b:+.3f}*c0|"
                 f"c2={cc:.3f}*c0+{cc:.3f}*c1|"
                 "c3=0*c0|"
                 f"c4={bl}|c5={br}")
        if delay_ms:
            f.append(f"adelay=delays=0|0|0|0|{delay_ms}|{d2}")
    if is_surround(mode) and not out51:          # downmix casque
        f.append("pan=stereo|c0=c0+0.707*c2+0.707*c4|c1=c1+0.707*c2+0.707*c5")
        f.append("aresample=44100")
        f.append("earwax")
    return ",".join(f)


def video_graph(std, aspect="4:3", scanlines=False):
    if std not in STANDARDS:
        return ""
    s = STANDARDS[std]
    h = s["lines"]
    w = round(h * (16 / 9 if aspect == "16:9" else 4 / 3) / 2) * 2   # largeur paire
    f = [f"fps={s['fps']}",
         f"scale={w}:{h}:force_original_aspect_ratio=decrease",
         f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
         "setsar=1", "format=yuv420p", s["chroma"]]
    if s["luma"]:
        f.append(s["luma"])
    if s["setup"]:
        f.append("lutyuv=y=val*0.925+19")
    if s["sat"] != 1.0:
        f.append(f"eq=saturation={s['sat']}")
    if scanlines:
        f.append("drawgrid=w=8192:h=2:x=8000:y=1:t=1:c=black@0.14")
    return ",".join(f)


def mpv_wrap(graph):
    return f"lavfi=[{graph}]" if graph else ""
