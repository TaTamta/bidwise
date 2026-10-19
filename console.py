# console.py — make stdout safe for the glyphs the desks print.
#
# The reports, the audit trail and the test harness all print box-drawing
# characters and emoji. On Windows the default console encoding is cp1252,
# which cannot encode them: the process dies with UnicodeEncodeError in the
# middle of a run. That is a presentation bug killing a working pipeline, so
# it is fixed once, here, and imported by every console entry point.
#
# Streamlit (ui.py) renders in a browser and does not need this.

import sys


def use_utf8():
    """Re-encode stdout/stderr as UTF-8. Safe to call more than once."""
    for stream in (sys.stdout, sys.stderr):
        # Guard: a stream swapped for a plain wrapper may not be reconfigurable.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
