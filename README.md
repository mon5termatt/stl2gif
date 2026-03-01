Takes a 3D model in STL and renders a quick isometric animation (one axis, or switch between axes with a zoom/return loop).

### Run in a virtual environment (recommended)

```powershell
# Windows (PowerShell) – from project folder
.\run.ps1
# Or create venv once and run manually:
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python stl2gif.py
```

Without an input path, a file picker opens. With a path you can pass a single file or a folder (optionally with `--recursive`).

### CLI options

| Flag | Description |
|------|-------------|
| `input` | Single `.stl` file or directory (optional; omit for file picker) |
| `-p`, `--path` | Same as positional input: path to a `.stl` file or directory |
| `-r`, `--recursive` | If input is a directory, find `.stl` files in subdirectories too |
| `--rotation`, `-rot` | `z` = vertical only, `x` = horizontal only, `switch` = Z then X then return (default) |
| `--duration`, `-d` | GIF duration in seconds (default: 15) |
| `--fps` | Frames per second (default: 20) |
| `-o`, `--output-dir` | Write all output GIFs into this directory (default: next to each .stl) |
| `-j`, `--workers` | Run up to N renders in parallel (default: 1) |
| `--no-open` | Don’t open the output GIF after rendering |

**Examples**

```bash
python stl2gif.py model.stl
python stl2gif.py model.stl --rotation z
python stl2gif.py ./models --recursive --rotation x
python stl2gif.py ./models -o ./gifs
python stl2gif.py ./models -j 4 -o ./gifs
```

**Library requirements:** numpy, trimesh, pyrender, imageio, Pillow, pyfqmr (see `requirements.txt`). The script can auto-install them if not in a venv; using a venv avoids touching your global Python.
