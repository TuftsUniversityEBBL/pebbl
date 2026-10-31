"""
Capture PEBBL screens from SYNTHETIC data for the RA manual (offscreen; no windows appear).

Writes docs/img/form.png, ecg_viewer.png, eda_viewer.png, summary.png and practice_report.png, for
developers updating the manual. Run from the tool folder, with Windows fonts for Qt:

    QT_QPA_FONTDIR=C:/Windows/Fonts annotate_env/Scripts/python.exe docs/capture_manual_shots.py [form ecg eda summary report]

Then rebuild the PDF and the web page (docs/build_manual_pdf.py) and commit docs/.
"""
import io
import contextlib
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the tool folder (docs/..)
sys.path.insert(0, TOOL)
OUT = os.path.join(TOOL, "docs", "img")
os.makedirs(OUT, exist_ok=True)

import mne  # noqa: E402
import numpy as np  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from PyQt6.QtGui import QFont  # noqa: E402
app.setFont(QFont("Segoe UI", 9))

import session_summary_gui  # noqa: E402
from annotation_io import run_stage_b  # noqa: E402
from channel_config import CHANNELS  # noqa: E402
from physio_io import generate_synthetic_demo  # noqa: E402
from simple_gui import ReviewLauncherDialog  # noqa: E402

which = sys.argv[1:] or ["form", "ecg", "eda", "summary", "report"]
ORIG_PLOT = mne.io.RawArray.plot


def pump(n=5):
    for _ in range(n):
        app.processEvents()


def shot_form():
    dlg = ReviewLauncherDialog()
    dlg.synthetic_checkbox.setChecked(False)
    dlg.box_path_edit.setText(r"C:\Users\you\Box\DATA\Processed\physioProcessing\derivatives")
    dlg.local_path_edit.setText(r"C:\Users\you\PhysioWorking")
    dlg.subject_edit.setText("001")
    dlg.initials_edit.setText("abc")
    dlg.step2_radio.setChecked(True)
    dlg.run_combo.setCurrentText("1")
    dlg.channel_combo.setCurrentIndex(dlg._channel_keys.index("ecg"))
    dlg.show()
    dlg.adjustSize()
    pump()
    dlg.grab().save(os.path.join(OUT, "form.png"))
    dlg.close()


def viewer_shot(name, channels, start_sec, prepare=None, size=(1280, 720), before=None, edit_df=None):
    def fake_plot(self, *a, **k):
        k.update(block=False, show=False)
        if before:
            before(self)
        fig = ORIG_PLOT(self, *a, **k)
        fig.resize(*size)
        fig.show()
        pump()
        fig._fake_keypress("a")  # annotation mode, as an RA would press it
        pump()
        if prepare:
            prepare(self, fig)
            pump()
        fig.mne.plt.setXRange(start_sec, start_sec + 20, padding=0)
        pump(10)
        fig.grab().save(os.path.join(OUT, name))
        fig.close()
        return fig

    df, sfreq = generate_synthetic_demo(duration_sec=90)
    if edit_df:
        edit_df(df, sfreq)
    tmp = tempfile.mkdtemp()
    try:
        with patch.object(mne.io.RawArray, "plot", fake_plot), \
             patch.object(session_summary_gui, "show_session_summary", session_summary_gui.headless_decision()), \
             contextlib.redirect_stdout(io.StringIO()):
            run_stage_b(df, sfreq, {k: CHANNELS[k] for k in channels}, "abc", tmp, "sub-990_ses-run1_task-sdi",
                        "synthetic demo")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def eda_artifact(df, sfreq):
    # An electrode-lift artifact: the signal drops abruptly, then snaps back.
    a, b = int(24.0 * sfreq), int(25.4 * sfreq)
    eda = df["eda"].to_numpy(dtype=float).copy()
    eda[a:b] -= 0.9 * (eda.max() - eda.min())
    df["eda"] = eda


def mark_bad_eda(raw):
    raw.annotations.append(23.8, 1.8, "bad_eda")


def shot_summary():
    dlg = session_summary_gui.SessionSummaryDialog(
        "sub-001_ses-run1_task-sdi · ECG · abc",
        ["ECG: 3 peak(s) added, 2 removed", "ECG bad stretches: 1 added"],
        ["ECG: unusual gap near 312.4 s (1640 ms vs. typical 820 ms)"],
        5, False,
        "Tick this only when you've finished. Then set this channel to \"finished\" in the Google tracking "
        "spreadsheet (the terminal will remind you).")
    dlg.show()
    dlg.adjustSize()
    pump()
    dlg.grab().save(os.path.join(OUT, "summary.png"))
    dlg.close()


def shot_report():
    """The practice score window for a run-1 ECG review whose premature-beat mark was deleted."""
    import practice_certification as pc
    import practice_report_gui
    root = tempfile.mkdtemp(prefix="pebbl_practice_shot_")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            pc.make(root, seed=7)
        key = pc.load_key(pc.key_path_for(root))
        run1 = key["runs"]["1"]
        sub = {"initials": "abc", "channels": {
            "ecg": {"mode": "point", "indices": list(run1["channels"]["ecg"]["true_peaks"])},
            "bad_ecg": {"mode": "segment", "bad_segments": [[a["start"], a["end"]]
                                                            for a in run1["channels"]["bad_ecg"]["artifacts"]]}}}
        sub["channels"]["ecg"]["indices"].remove(run1["channels"]["ecg"]["traps"][0]["sample"])
        passed, _results, lines = pc.score_run(key, sub, "1", ["ecg", "bad_ecg"])
        dlg = practice_report_gui.PracticeReportDialog("Practice participant 990, run 1: ecg", lines, passed)
        dlg.setMinimumSize(640, 400)
        dlg.resize(640, 400)
        dlg.show()
        pump()
        dlg.grab().save(os.path.join(OUT, "practice_report.png"))
        dlg.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)


if "form" in which:
    shot_form()
if "report" in which:
    shot_report()
if "ecg" in which:
    viewer_shot("ecg_viewer.png", ["ecg"], 20)
if "eda" in which:
    viewer_shot("eda_viewer.png", ["eda"], 20, before=mark_bad_eda, edit_df=eda_artifact)
if "summary" in which:
    shot_summary()
print("saved:", sorted(os.listdir(OUT)))
