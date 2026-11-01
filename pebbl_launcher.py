#!/usr/bin/env python3
"""
Start PEBBL for an RA: update, then open the form (HLU, 2026-10-04).

Run by "Start PEBBL.bat" (Windows) and "Start PEBBL.command" (Mac) with the
annotate_env Python. In order:

1. If this folder is its own git checkout (it has a .git folder, as a clone
   of the public pebbl repo does) and git is installed, pull the latest
   version (`git pull --ff-only`). A failed pull (no internet, git missing)
   is reported in one line and the current version starts anyway, unless
   step 2 stops it. A folder without a .git of its own is never pulled.
2. In such a checkout, check that PEBBL's files are still the ones
   downloaded (HLU, 2026-10-31). PEBBL won't start when any of its own files
   has been changed or deleted, or a new Python file has appeared (Python
   could load it in place of PEBBL's own): it lists them and asks for a
   photo for the lab staff (DEVELOPER_README.md says how to put the copy
   back). Other new files (Finder's .DS_Store, a saved screenshot) can't
   change what runs and are ignored. The check comes after the pull, so an
   update can clear a false alarm everywhere at once; a pull never
   overwrites a local edit. If git can't run the check, one line says so
   and PEBBL starts anyway: the check catches accidental edits, it isn't a
   lock. Developers run physio_review.py directly, which skips this script.
3. If requirements.txt differs from the copy saved at the last successful
   install (annotate_env/requirements.installed.txt), install it again and
   save the new copy. A failed install stops here: the form would fail
   anyway.
4. On a Mac, keep "Start PEBBL.command" executable (a pull can rewrite it
   without the executable bit).
5. Run physio_review.py with no arguments, which opens the form, once per
   session (HLU, 2026-10-05). Each session runs in its own process, so it
   finishes completely (copy back, cleanup, session log) first. When a
   session ends, normally or stopped with its own message, the form opens
   again. The form's Cancel closes PEBBL. So do Ctrl-C and any other
   failure, such as an error before the form could open, so a broken
   update can't loop.

Only the standard library is used, so an update that changes the packages
can't break this script.
"""

import filecmp
import importlib.machinery
import os
import shutil
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(HERE, "annotate_env")
REQUIREMENTS = os.path.join(HERE, "requirements.txt")
INSTALLED = os.path.join(ENV, "requirements.installed.txt")
MAC_LAUNCHER = os.path.join(HERE, "Start PEBBL.command")
PHYSIO_REVIEW = os.path.join(HERE, "physio_review.py")
# Exit codes from physio_review.py (copies: this script imports only the
# standard library; test_pebbl_launcher.py checks they match).
FORM_CANCELED_EXIT = 3
SESSION_STOPPED_EXIT = 4
# The files Python can import (.py, .pyw, .pyd, ...): a new one here could load in place of PEBBL's own.
PYTHON_SUFFIXES = tuple(importlib.machinery.all_suffixes())
MAX_LISTED = 20  # changed files listed when PEBBL won't start; the rest are counted


def update_code():
    """Pull the latest PEBBL if this folder is its own git checkout. Returns a one-line status."""
    if not os.path.isdir(os.path.join(HERE, ".git")):
        return None
    if shutil.which("git") is None:
        return "Couldn't check for PEBBL updates (Git isn't installed); starting the version you have."
    try:
        result = subprocess.run(["git", "pull", "--ff-only", "--quiet"], cwd=HERE, capture_output=True, text=True,
                                timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return f"Couldn't check for PEBBL updates ({type(e).__name__}); starting the version you have."
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return ("Couldn't update PEBBL; starting the version you have. If this keeps happening, send the lab "
                "staff this message: " + (detail[-1] if detail else f"git exit code {result.returncode}"))
    return "PEBBL is up to date."


def local_changes():
    """
    What has been changed in this copy of PEBBL since it was downloaded: (["path (changed)", ...], None), or
    (None, a one-line note) when the check can't run. Like update_code(), only in a folder that is its own git
    checkout.
    """
    if not os.path.isdir(os.path.join(HERE, ".git")):
        return [], None
    if shutil.which("git") is None:
        return None, "Couldn't check this copy of PEBBL for changes (Git isn't installed); starting anyway."
    try:
        # --no-optional-locks: only look, never rewrite git's index (other accounts share a lab copy).
        result = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain", "-z", "--untracked-files=all"],
                                cwd=HERE, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"Couldn't check this copy of PEBBL for changes ({type(e).__name__}); starting anyway."
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return None, ("Couldn't check this copy of PEBBL for changes; starting anyway. If this keeps happening, send "
                      "the lab staff this message: " + (detail[-1] if detail else f"git exit code {result.returncode}"))
    changes = []
    fields = iter(result.stdout.split("\0"))  # "XY path" each; -z: names as they are, never quoted
    for field in fields:
        if not field:
            continue
        code, path = field[:2], field[3:]
        if "R" in code or "C" in code:
            next(fields, None)  # a rename's or copy's original name
        if code == "??":
            if path.lower().endswith(PYTHON_SUFFIXES):
                changes.append(f"{path} (new)")
        elif "D" in code:
            changes.append(f"{path} (deleted)")
        else:
            changes.append(f"{path} ({'new' if 'A' in code else 'changed'})")
    return changes, None


def refusal(changes):
    """What the RA sees when this copy of PEBBL has been changed."""
    listed = changes[:MAX_LISTED]
    more = len(changes) - len(listed)
    return "\n".join([f"PEBBL won't start: some of its files in {HERE} have been changed since it was downloaded, "
                      "so it might not review data the way the lab expects."]
                     + [f"  {c}" for c in listed] + ([f"  ...and {more} more"] if more else [])
                     + ["Take a photo of this window and send it to the lab staff."])


def requirements_changed():
    return not (os.path.exists(INSTALLED) and filecmp.cmp(REQUIREMENTS, INSTALLED, shallow=False))


def install_requirements():
    """Install requirements.txt into this environment; True on success (then the copy is saved)."""
    print("Installing updated PEBBL components (this can take a few minutes)...")
    code = subprocess.call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r",
                            REQUIREMENTS])
    if code == 0:
        shutil.copyfile(REQUIREMENTS, INSTALLED)
        return True
    return False


def keep_mac_launcher_executable():
    if sys.platform == "darwin" and os.path.exists(MAC_LAUNCHER):
        mode = os.stat(MAC_LAUNCHER).st_mode
        os.chmod(MAC_LAUNCHER, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def run_sessions():
    """Open the form, run the session, and open the form again until it's canceled. Returns the exit code."""
    env = dict(os.environ, PEBBL_LAUNCHER="1")
    while True:
        code = subprocess.call([sys.executable, PHYSIO_REVIEW], cwd=HERE, env=env)
        if code == 0:
            print("\nOpening the form for your next session. Click Cancel there to close PEBBL.\n")
        elif code == SESSION_STOPPED_EXIT:
            print("\nThat session stopped early (see the message above). Opening the form again; click Cancel "
                  "there to close PEBBL.\n")
        elif code == FORM_CANCELED_EXIT:
            return 0
        else:
            return code


def main():
    status = update_code()
    changes, note = local_changes()
    if changes:
        print(refusal(changes))  # without the update line, which says the version you have starts
        return 1
    for line in (status, note):
        if line:
            print(line)
    if requirements_changed() and not install_requirements():
        print("PEBBL couldn't install its updated components. Take a photo of this window and send it to the "
              "lab staff.")
        return 1
    keep_mac_launcher_executable()
    return run_sessions()


if __name__ == "__main__":
    sys.exit(main())
