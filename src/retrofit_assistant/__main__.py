import os
import sys

if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, "-m", "retrofit_assistant", *sys.argv[1:]])

from .cli import main

sys.exit(main())
