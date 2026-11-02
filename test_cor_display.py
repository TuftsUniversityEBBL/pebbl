#!/usr/bin/env python3
"""
Tests how PEBBL shows corrugator EMG (COR), on physiopipe's planted COR
recording (fixtures/cor_planted_75-140s.npz; see fixtures/README.md): a
held frown, an ordinary 0.3-mV burst and electrode pops in quiet muscle.

The COR row's scale comes from its quiet signal, so all three reach the
row's edge and can't be told apart by height (the render check, HLU
2026-11-01). The fix, checked here:

  1. A read-only full-range row, emg_cor_full, sits right under emg_cor
     whenever COR is reviewed and has data (guide rows on or off), never
     otherwise; it has COR's unit.
  2. Its scale is the recording's largest value, so the pops fill it while
     the burst and the frown stay well below.
  3. Both COR rows are kept inside their own band, in the viewer's copy
     only; the data saved reviews come from are untouched, and so is every
     other row (an ECG row in the same session).
  4. A whole Step 2 session: the row and its opening line are there; the
     saved review is the same as without the row, which is never saved.
  5. Step 3 (reconciliation) shows and clamps it the same way.

Run with: annotate_env\\Scripts\\python.exe test_cor_display.py
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
from unittest.mock import patch

import mne
import numpy as np

import annotation_io
import processing_log
import session_summary_gui
from annotation_io import combine_with_reference_channels, run_stage_b
from channel_config import CHANNELS, FULL_RANGE_CHANNELS, FULL_RANGE_TEXT
from physio_io import (build_raw, clamp_display_rows, compute_scalings, generate_synthetic_demo,
                       sidecar_unit_labels)
from reconcile import run_stage_c

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "cor_planted_75-140s.npz")
BURST, FROWN, POPS = range(3)  # the fixture's events, in its order
# The clamp centres each row on its mean before clipping; the viewer recentres on the mean of what it shows
# (MNE's remove_dc), which clipping shifts by a sliver. For high-pass-filtered COR, well under 2% of a row.
BAND = 0.5 + 0.02


def load_fixture():
    z = np.load(FIXTURE)
    assert z["source_sha256"] == "6d5ccc8d505b2aaf90a1b515eb40189ce02530a5ccf0c6b9cdca7be6e6534766"
    spans = [(int((a - z["start_s"]) * z["sfreq"]), int((b - z["start_s"]) * z["sfreq"])) for a, b in z["event_spans_s"]]
    return z["emg_cor"].astype(float), float(z["sfreq"]), spans


def recording(cor, sfreq):
    """A synthetic recording of the fixture's length, its EMG column replaced by the planted COR."""
    df, demo_sfreq = generate_synthetic_demo(duration_sec=len(cor) / sfreq)
    assert demo_sfreq == sfreq and len(df) == len(cor)
    df["emg_cor"] = cor
    return df


def row(raw, ch):
    """A row's data, picked by position: a row named "ecg" is ambiguous with MNE's "ecg" type."""
    return raw.get_data(picks=[raw.ch_names.index(ch)])[0]


def on_screen(raw, scalings, ch):
    """A row's values as the viewer places them: its mean removed, in row heights (MNE: data / (2 * scale))."""
    x = row(raw, ch)
    return (x - x.mean()) / (2 * scalings[raw.get_channel_types(picks=[raw.ch_names.index(ch)])[0]])


def main():
    cor, sfreq, spans = load_fixture()
    df = recording(cor, sfreq)
    reviewed = {"ecg": CHANNELS["ecg"], "emg_cor": CHANNELS["emg_cor"]}

    print("1. emg_cor_full sits under emg_cor when COR is reviewed and has data; never otherwise...")
    for guides in (True, False):
        combined = combine_with_reference_channels(reviewed, df, ppg_guide=guides)
        keys = list(combined)
        assert keys[keys.index("emg_cor") + 1] == "emg_cor_full", keys
    assert "emg_cor_full" not in combine_with_reference_channels({"ecg": CHANNELS["ecg"]}, df), "COR not reviewed"
    for empty, why in ((np.nan, "COR without data"), (0.0, "an all-zero placeholder, as in the synthetic demo")):
        no_cor = df.copy()
        no_cor["emg_cor"] = empty
        assert "emg_cor_full" not in combine_with_reference_channels(reviewed, no_cor), why
    units, _ = sidecar_unit_labels({"emg_cor": {"Units": "mV"}}, combine_with_reference_channels(reviewed, df))
    assert units.get("emg") == "mV" and units.get("eog") == "mV", units
    print("   OK")

    print("2-3. Its scale is the largest value; both COR rows stay in their band; nothing else changes...")
    full = combine_with_reference_channels(reviewed, df)
    raw = build_raw(df, full, sfreq)
    assert np.array_equal(row(raw, "emg_cor_full"), cor)
    assert raw.get_channel_types(picks=[raw.ch_names.index("emg_cor_full")]) == ["eog"]
    scalings = compute_scalings(df, full)
    assert scalings == {**compute_scalings(df, reviewed), "eog": scalings["eog"]}, "other rows' scales unchanged"
    assert np.isclose(scalings["eog"], np.max(np.abs(cor - cor.mean())))
    unclamped = on_screen(raw, scalings, "emg_cor")
    clamp_display_rows(raw, full, scalings)
    fine, wide = on_screen(raw, scalings, "emg_cor"), on_screen(raw, scalings, "emg_cor_full")
    assert np.abs(unclamped).max() > 3, "without the clamp, COR's tall parts run over the rows below"
    for shown in (fine, wide):
        assert np.abs(shown).max() <= BAND, np.abs(shown).max()
    peak = [{name: np.abs(shown[a:b]).max() for name, shown in (("fine", fine), ("full", wide))} for a, b in spans]
    assert all(p["fine"] > 0.49 for p in peak), f"on emg_cor all three reach the edge: {peak}"
    assert peak[POPS]["full"] > 0.49 and peak[BURST]["full"] < 0.2 and peak[FROWN]["full"] < 0.05, peak
    assert np.array_equal(row(raw, "ecg"), df["ecg"].to_numpy()), "the ECG row isn't clamped"
    assert np.array_equal(df["emg_cor"].to_numpy(), cor), "the data reviews are saved from are untouched"
    print(f"   OK: on emg_cor_full the pops reach {peak[POPS]['full']:.2f} of a row, the burst "
          f"{peak[BURST]['full']:.2f}, the frown {peak[FROWN]['full']:.3f}")

    print("4. A whole Step 2 session: the row and its line are shown; the saved review is as without it...")
    n = len(df)
    sidecar = {"Provenance": {"NumberOfSamples": n}, "ecg": {"Units": "mV"}, "emg_cor": {"Units": "mV"},
               "MachineQC": {"Channels": {"emg_cor": {"BadSegments": [[1000, 2000]], "Rule": "planted"}}}}
    tmp = tempfile.mkdtemp()
    seen = {}

    def capture(self, *args, **kwargs):
        seen["ch_names"] = list(self.ch_names)
        seen["rows"] = {ch: on_screen(self, kwargs["scalings"], ch) for ch in self.ch_names
                        if ch in ("emg_cor", "emg_cor_full")}
        seen["ecg"] = row(self, "ecg") if "ecg" in self.ch_names else None

    def session(initials, without_row=False):
        out = io.StringIO()
        with patch.object(mne.io.RawArray, "plot", capture), \
             patch.object(processing_log, "LOCAL_SNAPSHOT_DIR", tmp), \
             patch.object(session_summary_gui, "show_session_summary", session_summary_gui.headless_decision()), \
             patch.object(annotation_io, "FULL_RANGE_CHANNELS", {} if without_row else FULL_RANGE_CHANNELS), \
             contextlib.redirect_stdout(out):
            run_stage_b(df.copy(), sfreq, dict(reviewed), initials, tmp, "sub-999_ses-run1_task-planted", "planted",
                        sidecar=sidecar)
        with open(os.path.join(tmp, f"sub-999_ses-run1_task-planted_annotations_{initials}.json")) as f:
            return out.getvalue(), json.load(f)["channels"]

    try:
        text, with_row = session("aaa")
        names = seen["ch_names"]
        assert names[names.index("emg_cor") + 1] == "emg_cor_full", names
        assert FULL_RANGE_TEXT in text, text[-1500:]
        assert all(np.abs(shown).max() <= BAND for shown in seen["rows"].values())
        assert np.array_equal(seen["ecg"], df["ecg"].to_numpy())
        text, without = session("bbb", without_row=True)
        assert "emg_cor_full" not in seen["ch_names"] and FULL_RANGE_TEXT not in text
        assert "emg_cor_full" not in with_row and set(with_row) == set(without), (set(with_row), set(without))
        assert with_row["emg_cor"]["bad_segments"] == without["emg_cor"]["bad_segments"] == [[1000, 2000]]
        assert with_row["ecg"]["indices"] == without["ecg"]["indices"]
        print("   OK")

        print("5. Step 3 (reconciliation) shows and clamps it the same way...")
        seen.clear()
        segments = {"emg_cor": {"mode": "segment", "bad_segments": [[1000, 2000]]}}
        with patch.object(mne.io.RawArray, "plot", capture), \
             patch.object(processing_log, "LOCAL_SNAPSHOT_DIR", tmp), \
             patch.object(session_summary_gui, "show_session_summary", session_summary_gui.headless_decision()), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            run_stage_c(df.copy(), sfreq, {"emg_cor": CHANNELS["emg_cor"]}, tmp, "sub-999_ses-run1_task-planted",
                        "planted", segments, segments, "aaa", "bbb", reconciler="hlu")
        names = seen["ch_names"]
        assert names[names.index("emg_cor") + 1] == "emg_cor_full", names
        assert FULL_RANGE_TEXT in out.getvalue()
        assert set(seen["rows"]) == {"emg_cor", "emg_cor_full"}
        assert all(np.abs(shown).max() <= BAND for shown in seen["rows"].values())
        print("   OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nALL COR DISPLAY TESTS PASSED.")


if __name__ == "__main__":
    main()
