"""
Where the tests find REAL recordings, and how they say when there are none.

Real participant data is never part of this repository. Lab staff point the
tests at a local folder holding some (physioProcess *_physio.tsv.gz files with
their .json sidecars), either way:

  - set the environment variable PEBBL_TEST_INPUT to that folder, or
  - put (or link) the folder at test_input/ next to this file (gitignored).

A file is looked for in that folder, then in its run8/ subfolder, where the
lab's current test copies live. A check that needs a file that isn't there
calls skip(), which prints a "SKIPPED:" line. run_tests.py counts those lines,
and `run_tests.py --require-data` fails if there are any.
"""

import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_INPUT = os.environ.get("PEBBL_TEST_INPUT") or os.path.join(HERE, "test_input")
SUBFOLDERS = ("", "run8")


def path(filename):
    """
    The first existing copy of `filename` in TEST_INPUT or TEST_INPUT/run8;
    if there is none, where it would be in TEST_INPUT (so callers can keep
    testing os.path.exists()).
    """
    for sub in SUBFOLDERS:
        candidate = os.path.join(TEST_INPUT, sub, filename)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(TEST_INPUT, filename)


def all_physio_files():
    """Every *_physio.tsv.gz anywhere under TEST_INPUT (a Box copy nests them under sub-XXX/ses-runY/beh/)."""
    return sorted(glob.glob(os.path.join(TEST_INPUT, "**", "*_physio.tsv.gz"), recursive=True))


def skip(what):
    """Say that a check didn't run for lack of real data, in the form run_tests.py counts."""
    print(f"   SKIPPED: {what} (no real test data in {TEST_INPUT})")
