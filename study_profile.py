"""
Study profiles: the review settings that differ from one study to another.

PEBBL's built-in settings are those of the study it was first built for
(recordings named sub-XXX_ses-runY_task-sdi_physio.tsv.gz), so with no
profile everything behaves as it always has. Another study's settings live
in a small TOML file that lab staff put in that study's data folder, next to
processing_log.csv, named pebbl_study.toml:

    schema_version = 1
    name = "mystudy"   # shown at the start of a session and recorded in saved files
    task = "mystudy"   # the recordings' task label: sub-XXX_ses-runY_task-<task>_physio.tsv.gz

and, each optional, defaulting to the built-in behaviour:

    runs = ["1"]                        # the runs there are (built in: "1" and "2")
    channels = ["ecg", "ppg", "rsp", "eda", "emg_cor"]   # the channels offered (built in: all)
    practice = false                    # certification practice offered (built in: yes)
    ppg_requires_timing_marker = false  # PPG review needs Provenance.CTTiming (built in: yes)
    bad_ecg_from_machine_qc = true      # bad_ecg starts from MachineQC's ecg stretches (built in: no)
    ecg_inversion_option = true         # offer "flip the ECG" for upside-down recordings (built in: no)
    ecg_seed_snap_ms = 0                # Step 1 moves each template-found R peak to the highest
                                        # point within this many ms (built in: 50; 0 = don't move)
    [event_labels]                      # names shown beside event codes (built in: numbers only)
    0 = "off task"
    50 = "baseline"

Lab staff can also name a profile file directly (physio_review.py
--study-profile). Profiles hold settings only, never data, and they are kept
outside this repository with each study's own records.

When a profile file is used:
  - a recording whose task label differs from the profile's stops the
    session, so a study's files are never reviewed with another study's
    settings;
  - the session log's header and every saved review file record the
    profile's name and the SHA-256 of its file ("study_profile"), so each
    review says which settings produced it.
With the built-in settings nothing is added to saved files, and a recording
with a task label other than "sdi" gets a printed note.

An unreadable profile, an unknown setting or a wrong value stops PEBBL with a
plain message rather than being ignored: a misspelled setting that silently
did nothing would be worse than no profile at all.
"""

import hashlib
import os
import re
import tomllib

PROFILE_FILE = "pebbl_study.toml"
SCHEMA_VERSION = 1
BUILT_IN_TASK = "sdi"
TASK_PATTERN = re.compile(r"^[A-Za-z0-9]+$")  # a BIDS label: letters and digits only
SETTINGS = {"schema_version", "name", "task", "runs", "channels", "practice", "ppg_requires_timing_marker",
            "bad_ecg_from_machine_qc", "ecg_inversion_option", "event_labels", "ecg_seed_snap_ms"}
BUILT_IN_SEED_SNAP_MS = 50  # annotation_io.DEFAULT_SNAP_WINDOW_SEC, in ms
FLAGS = {"practice": True, "ppg_requires_timing_marker": True, "bad_ecg_from_machine_qc": False,
         "ecg_inversion_option": False}  # each flag's built-in value


class StudyProfile:
    """One study's settings: the built-in ones (path None) or a profile file's."""

    def __init__(self, name, task, path=None, sha256=None, runs=("1", "2"), channels=None, event_labels=None,
                 ecg_seed_snap_ms=BUILT_IN_SEED_SNAP_MS, **flags):
        self.name = name
        self.task = task
        self.path = path
        self.sha256 = sha256
        self.runs = list(runs)
        self.ecg_seed_snap_ms = ecg_seed_snap_ms
        self.channels = None if channels is None else list(channels)  # None: every channel PEBBL knows
        self.event_labels = dict(event_labels or {})  # {code: name}
        for flag, default in FLAGS.items():
            setattr(self, flag, flags.pop(flag, default))
        if flags:
            raise TypeError(f"unknown settings {sorted(flags)}")

    @property
    def built_in(self):
        return self.path is None

    def saved_record(self):
        """What saved review files record about the settings: nothing for the built-in ones."""
        return {} if self.built_in else {"study_profile": {"name": self.name, "sha256": self.sha256}}

    def log_lines(self):
        """The session log header's line about the settings: none for the built-in ones."""
        return [] if self.built_in else [f"Study profile: {self.name} ({self.path}; SHA-256 {self.sha256})"]


BUILT_IN = StudyProfile(name="", task=BUILT_IN_TASK)
_active = BUILT_IN
# This session's "flip the ECG" choice (physio_review.py --ecg-inverted, only
# with a profile that sets ecg_inversion_option): the ECG was recorded upside
# down, so every step reviews it negated and saved files record "inverted".
_ecg_flipped = False


def set_ecg_flipped(flipped):
    global _ecg_flipped
    _ecg_flipped = bool(flipped)


def ecg_flipped():
    return _ecg_flipped


def _refuse(path, reason):
    raise SystemExit(f"The study profile {path} can't be used: {reason}. Please ask the lab staff.")


def read_profile(path):
    """A StudyProfile from a TOML file, after checking every setting."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
        settings = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        _refuse(path, f"it can't be read ({exc})")
    unknown = sorted(set(settings) - SETTINGS)
    if unknown:
        _refuse(path, f"it has setting(s) PEBBL doesn't know: {', '.join(unknown)}")
    if settings.get("schema_version") != SCHEMA_VERSION:
        _refuse(path, f"schema_version must be {SCHEMA_VERSION}")
    name, task = settings.get("name"), settings.get("task")
    if not isinstance(name, str) or not name.strip():
        _refuse(path, "name must be some text")
    if not isinstance(task, str) or not TASK_PATTERN.match(task):
        _refuse(path, "task must be the recordings' task label (letters and digits only)")
    optional = {}
    if "runs" in settings:
        runs = settings["runs"]
        if (not isinstance(runs, list) or not runs or len(set(map(str, runs))) != len(runs)
                or not all(isinstance(r, str) and r.isdigit() for r in runs)):
            _refuse(path, 'runs must be a list of run numbers as text, e.g. ["1"]')
        optional["runs"] = runs
    if "channels" in settings:
        from channel_config import CHANNELS  # here, not at the top: channel_config needn't load for paths alone
        channels = settings["channels"]
        if not isinstance(channels, list) or not channels or not all(isinstance(c, str) for c in channels):
            _refuse(path, "channels must be a list of channel names")
        unknown_channels = [c for c in channels if c not in CHANNELS]
        if unknown_channels:
            _refuse(path, f"channels has name(s) PEBBL doesn't know: {', '.join(unknown_channels)} "
                          f"(it knows {', '.join(CHANNELS)})")
        optional["channels"] = channels
    for flag in FLAGS:
        if flag in settings:
            if not isinstance(settings[flag], bool):
                _refuse(path, f"{flag} must be true or false")
            optional[flag] = settings[flag]
    if "ecg_seed_snap_ms" in settings:
        snap = settings["ecg_seed_snap_ms"]
        if isinstance(snap, bool) or not isinstance(snap, int) or not 0 <= snap <= 200:
            _refuse(path, "ecg_seed_snap_ms must be a whole number of milliseconds from 0 to 200")
        optional["ecg_seed_snap_ms"] = snap
    if "event_labels" in settings:
        labels = settings["event_labels"]
        if (not isinstance(labels, dict) or not all(k.lstrip("-").isdigit() for k in labels)
                or not all(isinstance(v, str) and v.strip() for v in labels.values())):
            _refuse(path, 'event_labels must map event codes to names, e.g. 50 = "baseline"')
        optional["event_labels"] = {int(k): v.strip() for k, v in labels.items()}
    return StudyProfile(name=name.strip(), task=task, path=os.path.abspath(path),
                        sha256=hashlib.sha256(raw).hexdigest(), **optional)


def load(data_folder=None, path=None):
    """
    The settings for a session: the profile file named by `path` if given,
    else the data folder's pebbl_study.toml if there is one, else the
    built-in settings.
    """
    if path:
        if not os.path.isfile(path):
            _refuse(path, "there's no such file")
        return read_profile(path)
    if data_folder:
        candidate = os.path.join(data_folder, PROFILE_FILE)
        if os.path.isfile(candidate):
            return read_profile(candidate)
    return BUILT_IN


def activate(profile):
    """Makes `profile` the settings every module uses for the rest of this session."""
    global _active
    _active = profile


def active():
    """The settings in use (the built-in ones until a profile is activated)."""
    return _active


def task_label(tsv_path):
    """The task label in a recording's file name (..._task-<label>_physio.tsv.gz), or None."""
    match = re.search(r"_task-([^_]+)_physio\.tsv\.gz$", os.path.basename(tsv_path))
    return match.group(1) if match else None


def check_recording(tsv_path):
    """
    Stops when a profile file is in use and the recording's task label isn't
    its task; with the built-in settings, prints a note for a task label
    other than "sdi". A file name without a task label isn't checked.
    """
    label = task_label(tsv_path)
    if label is None or label == _active.task:
        return
    if _active.built_in:
        print(f"Note: this recording's task label is '{label}'. There's no study profile ({PROFILE_FILE}) in its "
              f"data folder, so PEBBL uses its built-in settings, made for task-{BUILT_IN_TASK} recordings.")
        return
    raise SystemExit(f"This recording's task label is '{label}', but the study profile in use "
                     f"({_active.path}) is for task '{_active.task}'. PEBBL won't review one study's files with "
                     f"another study's settings. Please ask the lab staff.")
