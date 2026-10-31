#!/usr/bin/env python3
"""
Tests the Phase 3 safety fixes, with synthetic data only:

  1. Recording inputs PEBBL used to guess about now stop with a plain
     message and change nothing: no sidecar (it assumed 1000 Hz), a damaged
     or non-object sidecar (a Python traceback), a Columns list that doesn't
     match the file's fields (columns silently shifted or empty), a
     SamplingFrequency that isn't a positive number, and runs recorded at
     different rates (run 2's rate was ignored). A well-formed file still
     loads (positive control).
  2. Event markers: a missing event value is a gap, not a meaningless huge
     code; whole-number codes give exactly the markers they always did.
  3. Saved JSON is written all at once: the same bytes as before, and a
     write that fails leaves the earlier file untouched and no temporary
     file behind.
  4. A saved review records the ECG template's file name, not its full
     local path.
  5. Certification practice from the command line (Step 1 + Step 2 in one
     go) never refreshes the real log's local snapshot, and shows no
     tracking-spreadsheet reminder.

Run with: annotate_env\\Scripts\\python.exe test_input_safety.py
"""

import contextlib
import gzip
import io
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import mne
import numpy as np
import pandas as pd

import physio_review
import processing_log
import qrs_template
import qrs_template_stage
import session_summary_gui
from annotation_io import compute_event_transitions, resolve_ecg_peaks, write_json_atomic
from physio_io import build_run_path, generate_synthetic_demo, load_physio_tsv, read_sidecar

QUIET = contextlib.redirect_stdout


def write_run(path, df, sidecar):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, sep="\t", index=False, header=False, compression="gzip")
    if sidecar is not None:
        with open(path.replace("_physio.tsv.gz", "_physio.json"), "w") as f:
            if isinstance(sidecar, str):
                f.write(sidecar)
            else:
                json.dump(sidecar, f)
    return path


def stops(fn, *expected):
    """The SystemExit message fn raises; asserts it contains each expected fragment."""
    try:
        with QUIET(io.StringIO()):
            fn()
    except SystemExit as e:
        message = str(e)
        assert all(x in message for x in expected), message
        return message
    raise AssertionError(f"expected a stop mentioning {expected}")


def main():
    tmp = tempfile.mkdtemp()
    try:
        df, sfreq = generate_synthetic_demo(duration_sec=10)
        columns = list(df.columns)

        print("1. Inputs PEBBL used to guess about now stop; a good file still loads...")
        good = write_run(os.path.join(tmp, "good", "a_physio.tsv.gz"), df, {"Columns": columns, "SamplingFrequency": sfreq})
        loaded, rate = load_physio_tsv(good)
        assert rate == sfreq and list(loaded.columns) == columns and len(loaded) == len(df)
        no_sidecar = write_run(os.path.join(tmp, "nosidecar", "a_physio.tsv.gz"), df, None)
        stops(lambda: load_physio_tsv(no_sidecar), "There's no sidecar", "Nothing has been changed")
        broken = write_run(os.path.join(tmp, "broken", "a_physio.tsv.gz"), df, '{"Columns": [')
        stops(lambda: load_physio_tsv(broken), "can't be read", "Nothing has been changed")
        stops(lambda: read_sidecar(broken.replace("_physio.tsv.gz", "_physio.json")), "can't be read")
        listy = write_run(os.path.join(tmp, "listy", "a_physio.tsv.gz"), df, "[1, 2]")
        stops(lambda: load_physio_tsv(listy), "isn't in the expected format")
        for label, names in (("fewer", columns[:-2]), ("more", columns + ["extra1", "extra2"])):
            path = write_run(os.path.join(tmp, label, "a_physio.tsv.gz"), df, {"Columns": names, "SamplingFrequency": sfreq})
            stops(lambda: load_physio_tsv(path), f"{len(columns)} field(s) per row", f"names {len(names)} column(s)")
        for bad_rate in ("1000", 0, -5, True, None):
            path = write_run(os.path.join(tmp, f"rate_{bad_rate}", "a_physio.tsv.gz"), df,
                             {"Columns": columns, "SamplingFrequency": bad_rate})
            stops(lambda: load_physio_tsv(path), "SamplingFrequency")
        two = os.path.join(tmp, "two_rates")
        run1 = write_run(build_run_path(two, "050", "1"), df, {"Columns": columns, "SamplingFrequency": 1000})
        run2 = write_run(build_run_path(two, "050", "2"), df, {"Columns": columns, "SamplingFrequency": 500})
        args = SimpleNamespace(synthetic=False, input_run1=run1, input_run2=run2, box_path=None, subject=None,
                               out_dir=None)
        stops(lambda: physio_review.load_run_data(args), "Run 2 was recorded at 500 Hz", "at 1000 Hz")
        stops(lambda: qrs_template_stage.load_run_data(args), "Run 2 was recorded at 500 Hz")
        print("   OK")

        print("2. Event markers: a missing value is a gap; whole-number codes are unchanged...")
        events = compute_event_transitions(pd.DataFrame({"event": [0, 0, 50, 50, np.nan, np.nan, 50, 10]}), "event", 1000)
        assert events[:, [0, 2]].tolist() == [[2, 50], [6, 50], [7, 10]], events.tolist()
        codes = np.random.default_rng(2024).choice([0, 20, 30, 50, 65], size=5000).repeat(3)
        old = np.where(np.diff(codes) != 0)[0] + 1  # the rule before Phase 3
        new = compute_event_transitions(pd.DataFrame({"event": codes}), "event", 1000)
        assert new[:, 0].tolist() == old.tolist() and new[:, 2].tolist() == codes[old].tolist()
        print("   OK")

        print("3. JSON written all at once: same bytes; a failed write leaves the old file and no temp file...")
        payload = {"schema_version": 2, "channels": {"ecg": {"indices": [1, 2, 3], "unit": "µV"}}}
        plain, atomic = os.path.join(tmp, "plain.json"), os.path.join(tmp, "atomic.json")
        with open(plain, "w") as f:
            json.dump(payload, f, indent=2)
        write_json_atomic(atomic, payload, indent=2)
        assert open(plain, "rb").read() == open(atomic, "rb").read()
        before = os.listdir(tmp)
        try:
            write_json_atomic(atomic, {"bad": object()}, indent=2)
            raise AssertionError("expected a TypeError")
        except TypeError:
            pass
        assert open(atomic, "rb").read() == open(plain, "rb").read() and os.listdir(tmp) == before
        print("   OK")

        print("4. A saved review names the ECG template by file name only...")
        template = os.path.join(tmp, "deep", "folder", "x_ecg_corrected_qrs_zz.json")
        os.makedirs(os.path.dirname(template))
        with open(template, "w") as f:
            json.dump({"ecg": {"corrected_peaks": [100, 900], "initials": ["zz"]}}, f)
        _, label = resolve_ecg_peaks(df.copy(), "template", template)
        assert label == "QRS template (x_ecg_corrected_qrs_zz.json, 2 peaks)", label
        print("   OK")

        print("5. Practice from the command line: no real-log snapshot, no tracking reminder...")
        practice = os.path.join(tmp, "practice")
        df30, _ = generate_synthetic_demo(duration_sec=30)  # Step 1's template window is 20 s
        for run in ("1", "2"):
            write_run(build_run_path(practice, "990", run), df30, {"Columns": columns, "SamplingFrequency": sfreq})
        calls = []
        real_append = processing_log.append_processing_log_entry

        def record(*a, **k):
            calls.append((a[4] if len(a) > 4 else k.get("step"), k.get("snapshot", True)))
            return real_append(*a, **k)

        out = io.StringIO()
        snapshot = os.path.join(tmp, "snapshot")
        os.makedirs(snapshot)
        with patch.object(sys, "argv", ["physio_review.py", "--practice", "--box-path", practice, "--subject", "990",
                                        "--run", "1", "--initials", "zz", "--channels", "ecg", "--no-local-copy"]), \
             patch.object(physio_review, "append_processing_log_entry", record), \
             patch.object(processing_log, "LOCAL_SNAPSHOT_DIR", snapshot), \
             patch.object(mne.io.RawArray, "plot", return_value=None), \
             patch.object(qrs_template, "show_template_preview", return_value=(True, "")), \
             patch.object(session_summary_gui, "show_session_summary", session_summary_gui.headless_decision()), \
             patch.object(physio_review, "_practice_feedback", return_value=None), \
             patch("builtins.input", side_effect=AssertionError("no terminal prompt expected")), \
             QUIET(out), contextlib.redirect_stderr(out):
            try:
                physio_review.main()
            except SystemExit:
                pass
        assert ("created QRS template", True) not in calls and calls, (calls, out.getvalue()[-1500:])
        assert any(step == "created QRS template" for step, _ in calls), calls
        assert not os.listdir(snapshot), os.listdir(snapshot)
        assert "TRACKING SPREADSHEET" not in out.getvalue(), out.getvalue()[-1500:]
        print(f"   OK: log entries {calls}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nALL INPUT SAFETY TESTS PASSED.")


if __name__ == "__main__":
    main()
