#!/usr/bin/env python3
"""
Run PEBBL's test suites (test_*.py), each in its own Python process, and
summarize them: pass or fail, time, and how many checks were SKIPPED for lack
of real test data (see testdata.py).

    annotate_env/Scripts/python.exe run_tests.py                  # every suite
    annotate_env/Scripts/python.exe run_tests.py test_smoke.py    # only these
    annotate_env/Scripts/python.exe run_tests.py --require-data   # a skip is a failure

Qt runs offscreen and PEBBL's end-of-session pauses are off, so no windows
appear. Each suite's full output goes to <log dir>/<suite>.log (default: a new
temporary folder, printed at the end).

Exit code 0 if every suite passed (and, with --require-data, no check was
skipped); 1 otherwise.
"""

import argparse
import glob
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP_MARK = "SKIPPED:"


def run_suite(suite, env, log_dir, timeout):
    """(exit code or "timeout", seconds, skip lines) for one suite; its output goes to the log."""
    start = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, "-B", suite], cwd=HERE, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
        output, code = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as e:
        output, code = (e.stdout or b"") + f"\n[run_tests.py: stopped after {timeout:.0f} s]\n".encode(), "timeout"
    seconds = time.monotonic() - start
    name = os.path.splitext(os.path.basename(suite))[0]
    with open(os.path.join(log_dir, name + ".log"), "wb") as f:
        f.write(output)
    text = output.decode("utf-8", errors="replace")
    skips = [line.strip() for line in text.splitlines() if line.strip().startswith(SKIP_MARK)]
    return code, seconds, skips


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run PEBBL's test suites and summarize them.")
    parser.add_argument("suites", nargs="*", help="Test files to run (default: every test_*.py in this folder).")
    parser.add_argument("--require-data", action="store_true",
                        help="Fail if any check was skipped for lack of real test data.")
    parser.add_argument("--log-dir", default=None, help="Folder for each suite's output (default: a new temp folder).")
    parser.add_argument("--timeout", type=float, default=900, help="Seconds before a suite is stopped (default 900).")
    args = parser.parse_args(argv)

    suites = args.suites or sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, "test_*.py")))
    log_dir = args.log_dir or tempfile.mkdtemp(prefix="pebbl_tests_")
    os.makedirs(log_dir, exist_ok=True)
    # UTF-8 output so a suite never fails on printing a character the console code page lacks.
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PEBBL_NO_PAUSE": "1", "PYTHONIOENCODING": "utf-8"}

    failed, all_skips = [], []
    print(f"{'suite':<36} {'result':>7} {'secs':>6} {'skipped':>8}", flush=True)
    for suite in suites:
        code, seconds, skips = run_suite(suite, env, log_dir, args.timeout)
        result = "pass" if code == 0 else ("timeout" if code == "timeout" else f"FAIL {code}")
        if code != 0:
            failed.append(suite)
        all_skips += [(suite, line) for line in skips]
        print(f"{os.path.basename(suite):<36} {result:>7} {seconds:>6.0f} {len(skips):>8}", flush=True)

    if all_skips:
        print(f"\nSkipped for lack of real test data ({len(all_skips)}):")
        for suite, line in all_skips:
            print(f"  {os.path.basename(suite)}: {line}")
    print(f"\n{len(suites)} suite(s): {len(suites) - len(failed)} passed, {len(failed)} failed; "
          f"{len(all_skips)} check(s) skipped for lack of real test data.")
    if failed:
        print("Failed: " + ", ".join(os.path.basename(s) for s in failed))
    print(f"Logs: {log_dir}")
    if failed or (args.require_data and all_skips):
        if not failed:
            print("--require-data: failing because checks were skipped.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
