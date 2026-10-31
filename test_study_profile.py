#!/usr/bin/env python3
"""
Tests study_profile.py, the per-study settings, with synthetic data only:

  1. The built-in settings are the original study's: task "sdi", so a
     recording's path is exactly what it was before profiles existed, and
     nothing is added to saved files or the session log.
  2. A data folder's pebbl_study.toml is read; --study-profile wins over it;
     a folder without one gets the built-in settings.
  3. A profile with an unknown setting, a wrong schema_version, a bad task
     label, no name, broken TOML, or a missing file stops with a plain
     message rather than being ignored.
  4. check_recording(): with a profile file, a recording of another task
     stops the session; with the built-in settings, another task label only
     prints a note.
  5. A whole session through physio_review.py: with a profile in the data
     folder, the saved review records the profile's name and SHA-256 and the
     session log names it; without one, neither does (negative control); a
     profile for another task stops the session before anything is saved.

Run with: annotate_env\\Scripts\\python.exe test_study_profile.py
"""

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

import mne

import physio_review
import processing_log
import session_summary_gui
import study_profile
from physio_io import build_run_path, generate_synthetic_demo

QUIET = contextlib.redirect_stdout


def write_profile(folder, text, name=study_profile.PROFILE_FILE):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:  # these exact bytes, so their SHA-256 is known
        f.write(text)
    return path


def refused(path_or_folder, as_path=False):
    """The message a profile is refused with (AssertionError if it's accepted)."""
    try:
        study_profile.load(path=path_or_folder) if as_path else study_profile.load(path_or_folder)
    except SystemExit as e:
        return str(e)
    raise AssertionError(f"expected {path_or_folder} to be refused")


def make_subject(data_folder, subject, task):
    """A synthetic recording named with `task`, with a minimal sidecar."""
    study_profile.activate(study_profile.StudyProfile(name="t", task=task, path="x", sha256="x"))
    try:
        tsv = build_run_path(data_folder, subject, "1")
    finally:
        study_profile.activate(study_profile.BUILT_IN)
    os.makedirs(os.path.dirname(tsv))
    df, sfreq = generate_synthetic_demo(duration_sec=20)
    df.to_csv(tsv, sep="\t", index=False, header=False, compression="gzip")
    with open(tsv.replace("_physio.tsv.gz", "_physio.json"), "w") as f:
        json.dump({"Columns": list(df.columns), "SamplingFrequency": sfreq}, f)
    return tsv


def run_session(data_folder, subject, snapshot_dir):
    """A non-interactive Step 2 EDA review; returns (exit code, console text)."""
    out = io.StringIO()
    code = 0
    with patch.object(sys, "argv", ["physio_review.py", "--box-path", data_folder, "--subject", subject, "--run", "1",
                                    "--initials", "zz", "--channels", "eda", "--no-local-copy"]), \
         patch.object(mne.io.RawArray, "plot", return_value=None), \
         patch.object(processing_log, "LOCAL_SNAPSHOT_DIR", snapshot_dir), \
         patch.object(session_summary_gui, "show_session_summary", session_summary_gui.headless_decision()), \
         patch("builtins.input", side_effect=AssertionError("no terminal prompt expected")), \
         QUIET(out), contextlib.redirect_stderr(out):
        try:
            physio_review.main()
        except SystemExit as e:
            code = e.code
    study_profile.activate(study_profile.BUILT_IN)
    return code, out.getvalue()


def main():
    tmp = tempfile.mkdtemp()
    try:
        print("1. Built-in settings: task 'sdi', the same path as before profiles, nothing recorded...")
        assert study_profile.active() is study_profile.BUILT_IN and study_profile.BUILT_IN.task == "sdi"
        assert build_run_path("D", "001", "1") == os.path.join("D", "sub-001", "ses-run1", "beh",
                                                               "sub-001_ses-run1_task-sdi_physio.tsv.gz")
        assert study_profile.BUILT_IN.saved_record() == {} and study_profile.BUILT_IN.log_lines() == []
        print("   OK")

        print("2. Reading a data folder's profile; --study-profile wins; no file means built-in...")
        folder = os.path.join(tmp, "data")
        os.makedirs(folder)
        assert study_profile.load(folder) is study_profile.BUILT_IN and study_profile.load() is study_profile.BUILT_IN
        text = 'schema_version = 1\nname = "Demo study"\ntask = "demo"\n'
        path = write_profile(folder, text)
        profile = study_profile.load(folder)
        assert (profile.name, profile.task, profile.path) == ("Demo study", "demo", os.path.abspath(path))
        assert profile.sha256 == hashlib.sha256(text.encode()).hexdigest()
        assert profile.saved_record() == {"study_profile": {"name": "Demo study", "sha256": profile.sha256}}
        other = write_profile(tmp, 'schema_version = 1\nname = "Other"\ntask = "other"\n', name="other.toml")
        assert study_profile.load(folder, other).task == "other"
        print("   OK")

        print("3. Unknown settings, wrong values, broken files and missing files are refused...")
        bad = os.path.join(tmp, "bad")
        os.makedirs(bad)
        cases = {
            'schema_version = 1\nname = "x"\ntask = "x"\ntaks = "y"\n': "doesn't know: taks",
            'schema_version = 2\nname = "x"\ntask = "x"\n': "schema_version must be 1",
            'schema_version = 1\nname = "x"\ntask = "ur glab"\n': "letters and digits only",
            'schema_version = 1\ntask = "x"\n': "name must be some text",
            'schema_version = 1\nname = "x"\ntask = \n': "can't be read",
        }
        for text, expected in cases.items():
            write_profile(bad, text)
            message = refused(bad)
            assert expected in message and "ask the lab staff" in message, message
        assert "no such file" in refused(os.path.join(tmp, "missing.toml"), as_path=True)
        print("   OK")

        print("4. check_recording(): another task stops with a profile, only notes without one...")
        sdi_file = os.path.join("x", "sub-001_ses-run1_task-sdi_physio.tsv.gz")
        demo_file = os.path.join("x", "sub-001_ses-run1_task-demo_physio.tsv.gz")
        out = io.StringIO()
        with QUIET(out):
            study_profile.check_recording(sdi_file)
            study_profile.check_recording(os.path.join("x", "renamed.tsv.gz"))
        assert out.getvalue() == "", out.getvalue()
        with QUIET(out):
            study_profile.check_recording(demo_file)
        assert "task label is 'demo'" in out.getvalue() and "built-in settings" in out.getvalue(), out.getvalue()
        study_profile.activate(profile)
        try:
            study_profile.check_recording(demo_file)
            try:
                study_profile.check_recording(sdi_file)
                raise AssertionError("expected SystemExit")
            except SystemExit as e:
                assert "task label is 'sdi'" in str(e) and "for task 'demo'" in str(e), str(e)
        finally:
            study_profile.activate(study_profile.BUILT_IN)
        print("   OK")

        print("5. A whole session: the profile is recorded only when one is used; a mismatch stops it...")
        snapshot = os.path.join(tmp, "snapshot")
        os.makedirs(snapshot)
        with_profile = os.path.join(tmp, "with_profile")
        os.makedirs(with_profile)
        demo_tsv = make_subject(with_profile, "041", "demo")
        write_profile(with_profile, 'schema_version = 1\nname = "Demo study"\ntask = "demo"\n')
        code, text = run_session(with_profile, "041", snapshot)
        assert code in (0, None) and "Study profile: Demo study" in text, text[-2000:]
        stem = demo_tsv.replace("_physio.tsv.gz", "")
        with open(stem + "_annotations_zz.json") as f:
            saved = json.load(f)
        expected_sha = hashlib.sha256(open(os.path.join(with_profile, study_profile.PROFILE_FILE), "rb").read()).hexdigest()
        assert saved["study_profile"] == {"name": "Demo study", "sha256": expected_sha}, saved.get("study_profile")
        with open(stem + "_annotations_zz.log", encoding="utf-8") as f:
            assert f"Study profile: Demo study (" in f.read()

        without = os.path.join(tmp, "without_profile")
        os.makedirs(without)
        sdi_tsv = make_subject(without, "042", "sdi")
        code, text = run_session(without, "042", snapshot)
        assert code in (0, None) and "Study profile" not in text and "Note: this recording" not in text, text[-2000:]
        with open(sdi_tsv.replace("_physio.tsv.gz", "_annotations_zz.json")) as f:
            assert "study_profile" not in json.load(f)
        with open(sdi_tsv.replace("_physio.tsv.gz", "_annotations_zz.log"), encoding="utf-8") as f:
            assert "Study profile" not in f.read()

        mismatch = os.path.join(tmp, "mismatch")
        os.makedirs(mismatch)
        mismatch_tsv = make_subject(mismatch, "043", "demo")
        write_profile(mismatch, 'schema_version = 1\nname = "Other"\ntask = "other"\n')
        code, text = run_session(mismatch, "043", snapshot)
        assert code not in (0, None) and "for task 'other'" in text, text[-2000:]
        assert not os.path.exists(mismatch_tsv.replace("_physio.tsv.gz", "_annotations_zz.json"))
        print("   OK: recorded with a profile; nothing without one; a mismatch saves nothing")
    finally:
        study_profile.activate(study_profile.BUILT_IN)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nALL STUDY PROFILE TESTS PASSED.")


if __name__ == "__main__":
    main()
