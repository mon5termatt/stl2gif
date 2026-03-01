Takes a 3D model (STL or 3MF) and renders a quick isometric animation (one axis, or switch between axes with a zoom/return loop).

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
> [!CAUTION]
> **3MF support is experimental.** It may not work for all models.

Without an input path, a file picker opens. With a path you can pass a single file or a folder (optionally with `--recursive`).

### CLI options

| Flag | Description |
|------|-------------|
| `input` | Single `.stl` or `.3mf` file or directory (optional; omit for file picker) |
| `-p`, `--path` | Same as positional input: path to a mesh file or directory |
| `-r`, `--recursive` | If input is a directory, find `.stl`/`.3mf` files in subdirectories too |
| `-rot`, `--rotation` | `z` = spin around vertical (turntable), `x` = tilt around horizontal, `switch` = Z then X then return (default) |
| `-d`, `--duration` | GIF duration in seconds (default: 15) |
| `-o`, `--output-dir` | Write all output GIFs into this directory (default: next to each .stl) |
| `-j`, `--workers` | Run up to N renders in parallel (default: 1) |
| `-z`, `--zoom` | Zoom level: 1.0 = default, >1 = zoom in, <1 = zoom out |
| `-v`, `--verbose` | Show progress from each worker when using `-j` (default: quiet in parallel) |
| `--fps` | Frames per second (default: 20) |
| `--no-open` | Don’t open the output GIF after rendering |

**Examples**

```bash
python stl2gif.py model.stl
python stl2gif.py model.stl --rotation z
python stl2gif.py ./models --recursive --rotation x
python stl2gif.py ./models -o ./gifs
python stl2gif.py ./models -j 4 -o ./gifs
.\run.ps1 -p ".\Path\To\Models" -r --no-open --fps 30 -rot z -d 5 -o gifs -j 10 -z 2
```

**Library requirements:** numpy, trimesh, pyrender, imageio, Pillow, pyfqmr, lxml, networkx (see `requirements.txt`). 3MF support needs lxml and networkx. The script can auto-install them if not in a venv; using a venv avoids touching your global Python.
