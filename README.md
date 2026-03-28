# Instagram Post Unliker

Run `run.bat`.

If Python 3 is missing, the launcher will try to install it automatically with `winget` before creating `.venv` and starting the script.

The Python entrypoint is `main.py`.

When the Edge WebDriver window opens:

1. Log in to Instagram.
2. Go to the likes page if Instagram does not open there automatically.
3. The script will start automatically when the `Select` button becomes available.
4. You can still press Enter in the console to force a manual start.

After that, the script will start removing likes automatically.
