# FunPrint: first print on a Mac

This guide starts with a fresh Mac and a Fun Print / Yintibao / MXW01 printer. It
uses the Terminal app for a few copy-and-paste commands. The printer connection
is Bluetooth; there is no account or cloud service.

## 1. Prepare the printer

1. Load a roll of thermal paper and close the cover.
2. Turn the printer on. Its light should blink slowly green.
3. If the phone app is open or the light is solid green, quit the phone app so
   it releases the printer.

## 2. Install Python

Install Python 3 from [python.org](https://www.python.org/downloads/macos/).
After installation, open **Terminal** (Applications → Utilities → Terminal)
and enter:

```bash
python3 --version
```

It should print a Python version. If macOS asks whether Terminal or Python may
use Bluetooth, allow it.

## 3. Download and install FunPrint

1. Download and unzip the **FunPrint friend kit ZIP** you were given. It
   contains the app, this guide, and the JPEG converter.
2. In Terminal, type `cd ` (including the space), drag the unzipped
   `funprint` folder from Finder into Terminal, then press Return.
3. Copy and run these commands one at a time:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python3 -m pip install -e .
   ```

   Leave this Terminal window open. When you use FunPrint later, first open
   Terminal, move into this same `funprint` folder, and run
   `source .venv/bin/activate`.

## 4. Find the printer

With the printer awake and nearby, run:

```bash
funprint scan
```

The command lists nearby Fun Print printers and their Bluetooth addresses. On
macOS the address is usually a UUID, not the printer's printed serial number.
Copy the address shown beside your printer. If no printer appears, wake it,
check that the phone app is closed, and scan again.

## 5. Prepare pictures (optional)

To convert pictures in a folder to JPEG, run this from the `funprint` folder:

```bash
python3 scripts/convert_folder_to_jpeg.py "/path/to/your/pictures"
```

Replace the example path by typing the command up to the space after `pictures`,
dragging your picture folder from Finder into Terminal, and pressing Return. The
script puts JPEG copies in a new `JPEG` folder inside it. Your original files
are left alone. It supports common image formats; animated files use their
first frame and transparent areas become white. To include subfolders, add
`--recursive` before the folder path.

## 6. Preview, then print

Preview the JPEG folder first. Replace the address and drag the `JPEG` folder
into Terminal where the example path appears:

```bash
funprint --mac "PASTE-PRINTER-ADDRESS-HERE" folder "/path/to/your/pictures/JPEG" --dry-run
```

If the list looks right, run the same command without `--dry-run`:

```bash
funprint --mac "PASTE-PRINTER-ADDRESS-HERE" folder "/path/to/your/pictures/JPEG"
```

You can also print a single picture:

```bash
funprint --mac "PASTE-PRINTER-ADDRESS-HERE" image "/path/to/picture.jpg"
```

Keep the printer on and near the Mac until each picture is confirmed. If a job
times out or reports an error, check the paper and printer before trying again;
the printer may have printed part of that picture already.

## Useful commands

```bash
funprint --help
funprint folder --help
python3 scripts/convert_folder_to_jpeg.py --help
```
