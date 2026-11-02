"""
Makes fixtures/cor_planted_75-140s.npz (test_cor_display.py's data) from physiopipe's planted corrugator
recording, so it can be rebuilt if physiopipe's COR filters change. See fixtures/README.md for its origin.

    annotate_env/Scripts/python.exe fixtures/make_cor_planted.py <cor_render_quiet300.csv>
"""
import hashlib
import os
import sys

import numpy as np
import pandas as pd

SOURCE_SHA256 = "6d5ccc8d505b2aaf90a1b515eb40189ce02530a5ccf0c6b9cdca7be6e6534766"
SFREQ = 1000
START_S, END_S = 75.0, 140.0
# The planted events inside the cut, in the source recording's seconds.
EVENTS = (("ordinary burst, 0.3 mV (do not mark)", 79.75, 80.25),
          ("held frown, 4 s (do not mark)", 100.0, 104.0),
          ("electrode pop cluster (mark)", 130.0, 130.9))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cor_planted_75-140s.npz")


def main(csv_path):
    with open(csv_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit(f"{csv_path} isn't the planted recording this fixture is made from (SHA-256 {digest}).")
    signal = pd.read_csv(csv_path)["emg_cor_mV"].to_numpy(dtype=float)
    cut = signal[int(START_S * SFREQ):int(END_S * SFREQ)].astype(np.float32)
    np.savez_compressed(OUT, emg_cor=cut, sfreq=SFREQ, start_s=START_S, source_sha256=SOURCE_SHA256,
                        event_names=np.array([e[0] for e in EVENTS]),
                        event_spans_s=np.array([e[1:] for e in EVENTS]))
    print(f"wrote {OUT} ({len(cut)} samples, {os.path.getsize(OUT)} bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
