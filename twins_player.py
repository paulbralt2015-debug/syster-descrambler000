#!/usr/bin/env python3
"""Twins Video Player 2 : lecteur natif (PySide6 + libmpv), sans HTML."""
import os
import sys
import locale
import random
import threading
import time

# libmpv (mpv-2.dll sous Windows) est cherchée à côté du programme
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
os.environ["PATH"] = BASE + os.pathsep + os.environ.get("PATH", "")
if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(BASE)

from PySide6.QtCore import Qt, QObject, Signal, QSettings
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QTabWidget, QListWidget,
    QListWidgetItem, QPushButton, QSlider, QLabel, QComboBox, QCheckBox, QFormLayout,
    QFileDialog, QMessageBox, QInputDialog, QLineEdit, QAbstractItemView)

import filters as F

VIDEO_EXT = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mpg", ".mpeg", ".m4v",
             ".ts", ".vob", ".divx", ".asf", ".ogv", ".mp3", ".flac", ".wav", ".ogg", ".m4a",
             ".opus", ".aac", ".ac3", ".dts", ".mid")
STYLE = """
QWidget{background:#14151b;color:#e9e8e4;font-size:13px}
QPushButton{background:#1d1f28;border:1px solid #2e3040;border-radius:6px;padding:6px 10px}
QPushButton:hover{border-color:#3fd0d4}
QPushButton#play{background:#3fd0d4;color:#0b0c10;font-weight:600;border-color:#3fd0d4;min-width:70px}
QListWidget,QLineEdit,QComboBox{background:#1d1f28;border:1px solid #2e3040;border-radius:6px;padding:4px}
QListWidget::item:selected{background:#2a2d3c;border-left:3px solid #f0558a}
QTabBar::tab{padding:8px 10px;color:#8d90a0;border-bottom:2px solid transparent}
QTabBar::tab:selected{color:#e9e8e4;border-bottom:2px solid #f0558a}
QTabWidget::pane{border:1px solid #2e3040}
QSlider::groove:horizontal{height:4px;background:#2e3040;border-radius:2px}
QSlider::sub-page:horizontal{background:#3fd0d4;border-radius:2px}
QSlider::handle:horizontal{width:12px;margin:-5px 0;border-radius:6px;background:#f0558a}
"""


def fmt(s):
    if not s or s < 0:
        return "0:00"
    s = int(s)
    h, m, r = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{r:02d}" if h else f"{m}:{r:02d}"


class Bridge(QObject):
    """Ramène les rappels de libmpv (autre thread) vers le thread de l'interface."""
    call = Signal(object)


class Win(QMainWindow):
    def __init__(self, mpv_mod):
        super().__init__()
        self.mpv = mpv_mod
        self.setWindowTitle("Twins Video Player 2")
        self.resize(1320, 800)
        self.cfg = QSettings("Twins", "TwinsVideoPlayer2")
        self.cur = None
        self.dragging = False
        self.last_save = 0
        self.bridge = Bridge()
        self.bridge.call.connect(lambda fn: fn())
        self._build()
        self._start_mpv()
        self._keys()
        self.setAcceptDrops(True)

    # ---------- interface ----------
    def _build(self):
        self.video = QWidget()
        self.video.setAttribute(Qt.WA_NativeWindow)
        self.video.setStyleSheet("background:#000")
        self.video.setMinimumSize(480, 270)
        self.title = QLabel("Aucun fichier")
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.sliderPressed.connect(lambda: setattr(self, "dragging", True))
        self.seek.sliderReleased.connect(self._seek_release)
        self.tcur, self.tdur = QLabel("0:00"), QLabel("0:00")

        def btn(text, fn, name=None, tip=""):
            b = QPushButton(text)
            b.clicked.connect(lambda *_: fn())
            b.setToolTip(tip)
            if name:
                b.setObjectName(name)
            return b
        self.bplay = btn("Lecture", self.toggle, "play", "Z / X / Espace")
        row = QHBoxLayout()
        for w in (btn("Préc.", self.prev, tip="V"), self.bplay, btn("Arrêt", self.stop, tip="C"),
                  btn("Suiv.", lambda: self.next(False), tip="B"), btn("−10 s", lambda: self.seek_by(-10)),
                  btn("+10 s", lambda: self.seek_by(10)), btn("A-B", self.ab, tip="L"),
                  btn("Capture", self.shot, tip="P")):
            row.addWidget(w)
        row.addStretch()
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 130)
        self.vol.setValue(100)
        self.vol.setFixedWidth(120)
        self.vol.valueChanged.connect(lambda v: setattr(self.mp, "volume", v))
        row.addWidget(QLabel("Vol."))
        row.addWidget(self.vol)
        row.addWidget(btn("Muet", self.mute, tip="M"))
        row.addWidget(btn("Plein écran", self.fullscreen, tip="F"))
        sk = QHBoxLayout()
        sk.addWidget(self.tcur)
        sk.addWidget(self.seek)
        sk.addWidget(self.tdur)
        self.ctrl = QWidget()
        cl = QVBoxLayout(self.ctrl)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.title)
        cl.addLayout(sk)
        cl.addLayout(row)
        left = QVBoxLayout()
        left.addWidget(self.video, 1)
        left.addWidget(self.ctrl)
        lw = QWidget()
        lw.setLayout(left)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_list(), "Liste")
        self.tabs.addTab(self._tab_bkm(), "Marque-pages")
        self.tabs.addTab(self._tab_audio(), "Audio")
        self.tabs.addTab(self._tab_video(), "Vidéo")
        self.tabs.addTab(self._tab_opt(), "Options")
        self.tabs.setFixedWidth(380)
        root = QWidget()
        h = QHBoxLayout(root)
        h.addWidget(lw, 1)
        h.addWidget(self.tabs)
        self.setCentralWidget(root)

    def _tab_list(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.lst = QListWidget()
        self.lst.setDragDropMode(QAbstractItemView.InternalMove)
        self.lst.itemDoubleClicked.connect(lambda it: self.load(it.data(Qt.UserRole)))
        r = QHBoxLayout()
        for t, fn in (("Fichiers", self.open_files), ("Dossier", self.open_dir), ("Sous-titres", self.add_subs),
                      ("Retirer", self.remove_sel), ("Vider", self.clear)):
            b = QPushButton(t)
            b.clicked.connect(lambda *_, f=fn: f())
            r.addWidget(b)
        v.addLayout(r)
        v.addWidget(self.lst)
        return w

    def _tab_bkm(self):
        w = QWidget()
        v = QVBoxLayout(w)
        b = QPushButton("Marquer ce moment")
        b.clicked.connect(self.add_bm)
        self.bl = QListWidget()
        self.bl.itemDoubleClicked.connect(lambda it: self.mp.seek(it.data(Qt.UserRole), "absolute"))
        d = QPushButton("Supprimer")
        d.clicked.connect(self.del_bm)
        v.addWidget(b)
        v.addWidget(self.bl)
        v.addWidget(d)
        return w

    def _slider(self, lo, hi, val, cb):
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        s.valueChanged.connect(lambda *_: cb())
        return s

    def _tab_audio(self):
        w = QWidget()
        f = QFormLayout(w)
        self.amode = QComboBox()
        self.amode.addItems(list(F.AUDIO_MODES))
        self.aout = QComboBox()
        self.aout.addItems(["Casque (downmix)", "Enceintes 5.1"])
        self.slev = self._slider(0, 300, 100, self.apply_audio)
        self.clev = self._slider(0, 200, 100, self.apply_audio)
        self.sdel = self._slider(0, 60, 15, self.apply_audio)
        self.bass = self._slider(-6, 12, 0, self.apply_audio)
        self.rev = self._slider(0, 100, 0, self.apply_audio)
        self.amode.currentIndexChanged.connect(self.apply_audio)
        self.aout.currentIndexChanged.connect(self.apply_audio)
        for lab, wd in (("Décodage", self.amode), ("Sortie", self.aout), ("Surround / largeur", self.slev),
                        ("Centre", self.clev), ("Retard surround (ms)", self.sdel),
                        ("Basses (dB)", self.bass), ("Salle", self.rev)):
            f.addRow(lab, wd)
        n = QLabel("Le décodage Pro Logic s’applique à une bande son stéréo encodée Lt/Rt. "
                   "Les flux AC-3 et DTS 5.1 sont lus tels quels par mpv.")
        n.setWordWrap(True)
        n.setStyleSheet("color:#8d90a0")
        f.addRow(n)
        return w

    def _tab_video(self):
        w = QWidget()
        f = QFormLayout(w)
        self.std = QComboBox()
        self.std.addItems(["Original", "PAL", "SECAM", "NTSC"])
        self.dar = QComboBox()
        self.dar.addItems(["4:3", "16:9"])
        self.scan = QCheckBox("Lignes de balayage")
        for c in (self.std, self.dar):
            c.currentIndexChanged.connect(self.apply_video)
        self.scan.stateChanged.connect(self.apply_video)
        exp = QPushButton("Exporter la conversion (MP4)…")
        exp.clicked.connect(self.export)
        f.addRow("Standard", self.std)
        f.addRow("Format", self.dar)
        f.addRow(self.scan)
        f.addRow(exp)
        n = QLabel("PAL et SECAM : 25 i/s, 576 lignes. NTSC : 29,97 i/s, 480 lignes. "
                   "L’export convertit réellement le fichier (cadence, définition, chroma) "
                   "et applique aussi le décodage audio choisi.")
        n.setWordWrap(True)
        n.setStyleSheet("color:#8d90a0")
        f.addRow(n)
        return w

    def _tab_opt(self):
        w = QWidget()
        f = QFormLayout(w)
        self.mode = QComboBox()
        self.mode.addItems(["Normal", "Répéter la liste", "Répéter le fichier", "Aléatoire"])
        self.rate = QComboBox()
        self.rate.addItems(["0.5", "0.75", "1", "1.25", "1.5", "2"])
        self.rate.setCurrentText("1")
        self.rate.currentTextChanged.connect(lambda t: setattr(self.mp, "speed", float(t)))
        self.fit = QComboBox()
        self.fit.addItems(["Ajustée", "Remplie", "Étirée"])
        self.fit.currentIndexChanged.connect(self.apply_fit)
        self.bri = self._slider(-50, 50, 0, lambda: setattr(self.mp, "brightness", self.bri.value()))
        self.con = self._slider(-50, 50, 0, lambda: setattr(self.mp, "contrast", self.con.value()))
        self.sat = self._slider(-100, 100, 0, lambda: setattr(self.mp, "saturation", self.sat.value()))
        self.blk = QLineEdit(str(self.cfg.value("blocked", "")))
        self.blk.setPlaceholderText("mot1, mot2")
        self.blk.editingFinished.connect(lambda: self.cfg.setValue("blocked", self.blk.text()))
        for lab, wd in (("Mode", self.mode), ("Vitesse", self.rate), ("Image", self.fit),
                        ("Luminosité", self.bri), ("Contraste", self.con), ("Saturation", self.sat),
                        ("Mots bloqués", self.blk)):
            f.addRow(lab, wd)
        k = QLabel("Z/X lecture · C arrêt · V/B précédent/suivant · +/− ±10 s · ←/→ ±5 s · T aller à · "
                   "F plein écran · L boucle A-B · P capture · ,/. image par image · M muet · "
                   "O fichiers · D dossier · I infos · Q marque-page · molette volume")
        k.setWordWrap(True)
        k.setStyleSheet("color:#8d90a0")
        f.addRow(k)
        return w

    # ---------- moteur mpv ----------
    def _start_mpv(self):
        self.mp = self.mpv.MPV(wid=str(int(self.video.winId())), input_default_bindings=False,
                               input_vo_keyboard=True, osc=False, keep_open="yes", hwdec="auto-safe",
                               sub_auto="fuzzy", screenshot_format="png")
        gui = self.bridge.call.emit
        self.mp.observe_property("time-pos", lambda n, v: gui(lambda: self.on_pos(v)))
        self.mp.observe_property("duration", lambda n, v: gui(lambda: self.tdur.setText(fmt(v))))
        self.mp.observe_property("pause", lambda n, v: gui(lambda: self.bplay.setText("Lecture" if v else "Pause")))
        self.mp.observe_property("eof-reached", lambda n, v: gui(lambda: self.on_eof()) if v else None)

    def _keys(self):
        T = [("Z", "z", self.toggle), ("X", "x", self.toggle), ("Space", "SPACE", self.toggle),
             ("C", "c", self.stop), ("V", "v", self.prev), ("B", "b", lambda: self.next(False)),
             ("+", "+", lambda: self.seek_by(10)), ("=", "=", lambda: self.seek_by(10)),
             ("-", "-", lambda: self.seek_by(-10)), ("Right", "RIGHT", lambda: self.seek_by(5)),
             ("Left", "LEFT", lambda: self.seek_by(-5)), ("T", "t", self.jump), ("F", "f", self.fullscreen),
             ("Esc", "ESC", self.leave_fs), ("L", "l", self.ab), ("P", "p", self.shot),
             (",", ",", lambda: self.mp.command("frame-back-step")), (".", ".", lambda: self.mp.command("frame-step")),
             ("M", "m", self.mute), ("O", "o", self.open_files), ("A", "a", self.open_files),
             ("D", "d", self.open_dir), ("I", "i", self.info), ("Q", "q", self.add_bm)]
        gui = self.bridge.call.emit
        for qk, mk, fn in T:
            sc = QShortcut(QKeySequence(qk), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(fn)
            try:
                self.mp.register_key_binding(
                    mk, lambda st, key, ch=None, f=fn: gui(f) if st[:1] in ("d", "p") else None)
            except Exception:
                pass
        try:
            for k, d in (("WHEEL_UP", 5), ("WHEEL_DOWN", -5)):
                self.mp.register_key_binding(k, lambda st, key, ch=None, d=d: gui(
                    lambda: self.vol.setValue(self.vol.value() + d)) if st[:1] in ("d", "p") else None)
            self.mp.register_key_binding("MBTN_LEFT_DBL", lambda st, key, ch=None: gui(self.fullscreen)
                                         if st[:1] in ("d", "p") else None)
        except Exception:
            pass

    def prop(self, name, default=None):
        try:
            v = self.mp[name]
            return default if v is None else v
        except Exception:
            return default

    # ---------- lecture ----------
    def paths(self):
        return [self.lst.item(i).data(Qt.UserRole) for i in range(self.lst.count())]

    def add_files(self, files):
        blocked = [w.strip().lower() for w in self.blk.text().split(",") if w.strip()]
        n = skipped = 0
        for p in files:
            if not p.lower().endswith(VIDEO_EXT):
                continue
            if any(w in os.path.basename(p).lower() for w in blocked):
                skipped += 1
                continue
            it = QListWidgetItem(os.path.basename(p))
            it.setData(Qt.UserRole, p)
            self.lst.addItem(it)
            n += 1
        if skipped:
            self.statusBar().showMessage(f"{skipped} fichier(s) bloqué(s) par vos mots bloqués", 4000)
        if n and self.cur is None:
            self.load(self.paths()[-n])

    def open_files(self):
        fs, _ = QFileDialog.getOpenFileNames(self, "Ouvrir des fichiers", "", "Médias (*" + " *".join(VIDEO_EXT) + ");;Tous (*)")
        self.add_files(fs)

    def open_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Ajouter un dossier")
        if d:
            self.add_files(sorted(os.path.join(r, f) for r, _, fl in os.walk(d) for f in fl))

    def add_subs(self):
        if not self.cur:
            return
        f, _ = QFileDialog.getOpenFileName(self, "Sous-titres", "", "Sous-titres (*.srt *.ass *.ssa *.sub *.vtt)")
        if f:
            self.mp.command("sub-add", f)

    def remove_sel(self):
        for it in self.lst.selectedItems():
            self.lst.takeItem(self.lst.row(it))

    def clear(self):
        self.lst.clear()
        self.stop()
        self.mp.command("stop")
        self.cur = None
        self.title.setText("Aucun fichier")
        self.refresh_bkm()

    def key_of(self, p):
        try:
            return f"{os.path.basename(p)}_{os.path.getsize(p)}".replace("/", "_").replace("\\", "_")
        except OSError:
            return os.path.basename(p)

    def load(self, path):
        if not path or not os.path.exists(path):
            self.statusBar().showMessage("Fichier introuvable", 4000)
            return
        self.cur = path
        t = float(self.cfg.value("pos/" + self.key_of(path), 0) or 0)
        self.mp["start"] = str(int(t)) if t > 8 else "none"
        self.mp.play(path)
        self.mp.pause = False
        self.title.setText(os.path.basename(path))
        self.setWindowTitle(os.path.basename(path) + " · Twins Video Player 2")
        for i in range(self.lst.count()):
            self.lst.item(i).setSelected(self.lst.item(i).data(Qt.UserRole) == path)
        self.refresh_bkm()
        if t > 8:
            self.statusBar().showMessage(f"Reprise à {fmt(t)}", 3000)

    def toggle(self):
        if self.cur is None:
            self.open_files()
        else:
            self.mp.pause = not self.mp.pause

    def stop(self):
        self.mp.pause = True
        self.mp.seek(0, "absolute")

    def next(self, auto):
        ps = self.paths()
        if not ps:
            return
        m = self.mode.currentIndex()
        i = ps.index(self.cur) if self.cur in ps else -1
        if m == 3:
            j = random.randrange(len(ps))
        else:
            j = i + 1
            if j >= len(ps):
                if m == 1 or not auto:
                    j = 0
                else:
                    return
        self.load(ps[j])

    def prev(self):
        ps = self.paths()
        if not ps:
            return
        if (self.prop('time-pos') or 0) > 3:
            self.mp.seek(0, "absolute")
            return
        i = ps.index(self.cur) if self.cur in ps else 0
        self.load(ps[(i - 1) % len(ps)])

    def on_eof(self):
        if self.cur:
            self.cfg.setValue("pos/" + self.key_of(self.cur), 0)
        if self.mode.currentIndex() == 2:
            self.mp.seek(0, "absolute")
            self.mp.pause = False
        else:
            self.next(True)

    def on_pos(self, v):
        if v is None:
            return
        self.tcur.setText(fmt(v))
        d = self.prop('duration')
        if d and not self.dragging:
            self.seek.setValue(int(v / d * 1000))
        if self.cur and time.time() - self.last_save > 4:
            self.last_save = time.time()
            self.cfg.setValue("pos/" + self.key_of(self.cur), v)

    def _seek_release(self):
        self.dragging = False
        d = self.prop('duration')
        if d:
            self.mp.seek(self.seek.value() / 1000 * d, "absolute")

    def seek_by(self, s):
        self.mp.seek(s, "relative")

    def jump(self):
        t, ok = QInputDialog.getText(self, "Aller à", "Temps (mm:ss ou hh:mm:ss) :", text=fmt(self.prop('time-pos')))
        if ok:
            try:
                sec = 0
                for p in t.split(":"):
                    sec = sec * 60 + float(p)
                self.mp.seek(sec, "absolute")
            except ValueError:
                self.statusBar().showMessage("Format invalide. Exemple : 1:25:30", 4000)

    def mute(self):
        self.mp.mute = not self.mp.mute

    def ab(self):
        a, b = self.prop('ab-loop-a'), self.prop('ab-loop-b')
        pos = self.prop('time-pos') or 0
        if a in (None, "no"):
            self.mp["ab-loop-a"] = pos
            self.statusBar().showMessage(f"Point A à {fmt(pos)}", 3000)
        elif b in (None, "no"):
            self.mp["ab-loop-b"] = pos
            self.statusBar().showMessage(f"Boucle {fmt(a)} → {fmt(pos)}", 3000)
        else:
            self.mp["ab-loop-a"] = "no"
            self.mp["ab-loop-b"] = "no"
            self.statusBar().showMessage("Boucle désactivée", 3000)

    def shot(self):
        if not self.cur:
            return
        d = os.path.join(os.path.expanduser("~"), "Pictures")
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, f"{os.path.splitext(os.path.basename(self.cur))[0]}_{int(self.prop('time-pos') or 0)}s.png")
        self.mp.command("screenshot-to-file", out, "window")
        self.statusBar().showMessage("Capture : " + out, 5000)

    def info(self):
        g = lambda n: self.prop(n, "?")
        QMessageBox.information(self, "Informations", (
            f"Fichier : {self.cur}\nDurée : {fmt(self.prop('duration'))}\n"
            f"Vidéo : {g('width')}×{g('height')} · {g('container-fps')} i/s · {g('video-format')}\n"
            f"Audio : {g('audio-codec-name')} · {g('audio-params')}"))

    def fullscreen(self):
        fs = not self.isFullScreen()
        self.showFullScreen() if fs else self.showNormal()
        self.tabs.setVisible(not fs)
        self.ctrl.setVisible(not fs)

    def leave_fs(self):
        if self.isFullScreen():
            self.fullscreen()

    # ---------- marque-pages ----------
    def refresh_bkm(self):
        self.bl.clear()
        if not self.cur:
            return
        for t in sorted(self.cfg.value("bkm/" + self.key_of(self.cur), []) or [], key=float):
            it = QListWidgetItem(fmt(float(t)))
            it.setData(Qt.UserRole, float(t))
            self.bl.addItem(it)

    def add_bm(self):
        if not self.cur:
            return
        k = "bkm/" + self.key_of(self.cur)
        v = list(self.cfg.value(k, []) or [])
        v.append(int(self.prop('time-pos') or 0))
        self.cfg.setValue(k, v)
        self.refresh_bkm()
        self.tabs.setCurrentIndex(1)

    def del_bm(self):
        it = self.bl.currentItem()
        if it and self.cur:
            k = "bkm/" + self.key_of(self.cur)
            v = [x for x in (self.cfg.value(k, []) or []) if float(x) != it.data(Qt.UserRole)]
            self.cfg.setValue(k, v)
            self.refresh_bkm()

    # ---------- audio / vidéo ----------
    def audio_cfg(self):
        mode = F.AUDIO_MODES[self.amode.currentText()]
        out51 = self.aout.currentIndex() == 1
        graph = F.audio_graph(mode, out51, self.slev.value() / 100, self.clev.value() / 100,
                              self.sdel.value(), self.bass.value(), self.rev.value())
        if F.is_surround(mode) and out51:
            ch = "5.1"
        else:
            ch = "stereo" if graph else "auto-safe"
        return F.mpv_wrap(graph), ch

    def apply_audio(self):
        af, ch = self.audio_cfg()
        try:
            self.mp["audio-channels"] = ch
            self.mp["af"] = af
        except Exception as e:
            self.mp["af"] = ""
            self.statusBar().showMessage(f"Filtre audio refusé par mpv : {e}", 6000)

    def video_cfg(self):
        return F.mpv_wrap(F.video_graph(self.std.currentText(), self.dar.currentText(), self.scan.isChecked()))

    def apply_video(self):
        try:
            self.mp["vf"] = self.video_cfg()
        except Exception as e:
            self.mp["vf"] = ""
            self.statusBar().showMessage(f"Filtre vidéo refusé par mpv : {e}", 6000)

    def apply_fit(self):
        i = self.fit.currentIndex()
        self.mp["keepaspect"] = "no" if i == 2 else "yes"
        self.mp["panscan"] = 1.0 if i == 1 else 0.0

    # ---------- export (conversion réelle) ----------
    def export(self):
        if not self.cur:
            return
        std = self.std.currentText()
        out, _ = QFileDialog.getSaveFileName(
            self, "Exporter la conversion", os.path.splitext(self.cur)[0] + f"_{std}.mp4", "MP4 (*.mp4)")
        if not out:
            return
        vf, (af, ch) = self.video_cfg(), self.audio_cfg()
        src, mpv, gui = self.cur, self.mpv, self.bridge.call.emit

        def work():
            try:
                m = mpv.MPV(o=out, ovc="libx264", ovcopts="crf=20", oac="aac", vf=vf, af=af,
                            audio_channels="5.1" if ch == "5.1" else "stereo", keep_open="no")
                m.observe_property("percent-pos", lambda n, v: gui(
                    lambda: self.statusBar().showMessage(f"Conversion : {v:.0f} %")) if v else None)
                m.play(src)
                m.wait_for_playback()
                m.terminate()
                gui(lambda: self.statusBar().showMessage("Conversion terminée : " + out, 10000))
            except Exception as e:
                msg = str(e)
                gui(lambda: QMessageBox.warning(self, "Export impossible", msg))
        threading.Thread(target=work, daemon=True).start()
        self.statusBar().showMessage("Conversion en cours…")

    # ---------- divers ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_files([u.toLocalFile() for u in e.mimeData().urls()])

    def closeEvent(self, e):
        try:
            self.mp.terminate()
        except Exception:
            pass
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    locale.setlocale(locale.LC_NUMERIC, "C")  # exigé par libmpv
    try:
        import mpv
    except Exception as e:
        QMessageBox.critical(None, "libmpv introuvable",
                             "Placez mpv-2.dll (Windows) à côté du programme, ou installez libmpv "
                             f"(Linux : libmpv2, macOS : brew install mpv).\n\n{e}")
        return 1
    w = Win(mpv)
    w.show()
    w.add_files([a for a in sys.argv[1:] if os.path.isfile(a)])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
