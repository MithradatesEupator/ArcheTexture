from __future__ import annotations

import os

from archetexture.ui.main_window import main

if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    main()
