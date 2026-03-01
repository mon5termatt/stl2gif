import sys
import subprocess
import os
import math
import argparse
import importlib.util
import tkinter as tk
from tkinter import filedialog
import time
import tempfile
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

# install/check libraries
def ensure(lib, import_name=None):
    if import_name is None:
        import_name = lib
    if importlib.util.find_spec(import_name) is not None:
        print(f"{lib} ok")
        return
    print(f"{lib} missing, installing...")
    subprocess.run([sys.executable, "-m", "pip", "install", lib], check=True)

# ensure all required packages (lxml, networkx for 3MF support)
for lib, import_name in [("numpy", None), ("trimesh", None), ("pyrender", None), ("imageio", None), ("Pillow", "PIL"), ("pyfqmr", None), ("lxml", None), ("networkx", None)]:
    ensure(lib, import_name)

# imports after install
import numpy as np
import trimesh
import pyrender
import imageio
from PIL import Image, ImageDraw, ImageFont

# Supported 3D mesh file extensions
MESH_EXTENSIONS = (".stl", ".3mf")

def pick_file():
    root = tk.Tk()
    root.withdraw()
    return filedialog.askopenfilename(
        title="Select mesh file",
        filetypes=[("mesh files", "*.stl *.3mf"), ("STL files", "*.stl"), ("3MF files", "*.3mf"), ("All files", "*.*")]
    )


def collect_mesh_paths(input_path: str, recursive: bool) -> list:
    """Return a list of .stl and .3mf file paths from a single file or a directory (optionally recursive)."""
    p = Path(input_path).resolve()
    if not p.exists():
        return []
    if p.is_file():
        if p.suffix.lower() in MESH_EXTENSIONS:
            return [str(p)]
        return []
    # Directory
    paths = []
    for ext in MESH_EXTENSIONS:
        if recursive:
            paths.extend(p.rglob(f"*{ext}"))
        else:
            paths.extend(p.glob(f"*{ext}"))
    return sorted(str(f) for f in paths)

def open_file(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform.startswith("darwin"):
            subprocess.run(["open", path], check=True)
        else:  # linux
            subprocess.run(["xdg-open", path], check=True)
        return True
    except Exception as e:
        print(f"Could not open file: {e}")
        return False

def make_rotating_gif(stl_path, duration_seconds=15, fps=20, rotation_mode="switch", open_result=True, output_dir=None, zoom=1.0, verbose=True):
    """
    rotation_mode: "z" = spin around vertical axis (horizontal spin, turntable);
                   "x" = rotate around horizontal axis (tilt);
                   "switch" = Z then X then return.
    output_dir: if set, write the GIF into this directory (using the STL base name).
    zoom: 1.0 = default framing; >1 = zoom in (model larger), <1 = zoom out (model smaller).
    verbose: if False, suppress progress output (use when running parallel workers).
    """
    # force='mesh' so 3MF/Scene files are merged into a single mesh when possible
    loaded = trimesh.load(stl_path, force="mesh")
    if isinstance(loaded, trimesh.Trimesh):
        mesh = loaded
    else:
        # Scene (e.g. 3MF with multiple objects): merge all geometry into one mesh
        geos = list(loaded.geometry.values()) if hasattr(loaded, "geometry") else []
        if not geos:
            raise ValueError(f"No mesh geometry found in {stl_path}")
        mesh = trimesh.util.concatenate(geos)
    
    # Simplify mesh if it has too many faces (speeds up rendering significantly)
    if len(mesh.faces) > 50000:
        if verbose:
            print(f"Simplifying mesh from {len(mesh.faces)} faces...")
        try:
            mesh = mesh.simplify_quadric_decimation(50000)
            if verbose:
                print(f"Simplified to {len(mesh.faces)} faces")
        except Exception as e:
            if verbose:
                print(f"Quadric decimation failed, trying alternate method...")
            try:
                # Fallback to vertex clustering
                mesh = mesh.simplify_vertex_clustering(voxel_size=mesh.extents.max() / 100)
                if verbose:
                    print(f"Simplified to {len(mesh.faces)} faces using vertex clustering")
            except Exception as e2:
                if verbose:
                    print(f"Simplification not available, continuing with full mesh (may be slower)")
    
    mesh.merge_vertices(0.2)
    trimesh.repair.fix_normals(mesh)
    
    # Output path: next to STL or in output_dir if specified
    base_name = os.path.basename(os.path.splitext(stl_path)[0]) + ".gif"
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, base_name)
    else:
        output_path = os.path.splitext(stl_path)[0] + ".gif"
    
    frames = int(duration_seconds * fps)
    tmp_dir = tempfile.mkdtemp(prefix="stl2gif_")
    
    # Calculate model dimensions and center
    bounds = mesh.bounds
    centroid = mesh.centroid
    size = bounds[1] - bounds[0]
    max_dim = max(size)
    max_horizontal = max(size[0], size[1])  # X and Y
    vertical_dim = size[2]  # Z dimension
    
    # For isometric view, camera should be at 45° horizontally and ~35.26° vertically
    iso_angle = math.radians(35.264)  # arctan(1/sqrt(2)) for true isometric
    
    # Calculate distance so model takes up ~52.5% of view (75% * 0.7 for more zoom out)
    fov = np.pi / 3.0
    target_coverage = 0.75 * 0.7
    
    # Base distance uses max horizontal dimension for vertical rotation
    base_cam_distance = max_horizontal / (2 * target_coverage * math.tan(fov / 2))
    
    # For horizontal rotation, we need to account for vertical dimension
    # When looking from the side, we see the vertical dimension
    vertical_cam_distance = vertical_dim / (2 * target_coverage * math.tan(fov / 2))
    
    # Use the larger of the two to ensure model fits in both rotations
    phase1_cam_distance = max(base_cam_distance, vertical_cam_distance * 0.8) / zoom
    phase2_cam_distance = max(base_cam_distance, vertical_cam_distance * 0.95) / zoom  # Less zoomed out
    
    # Position camera for fixed isometric view (use phase1 distance initially)
    cam_height = phase1_cam_distance * math.sin(iso_angle)
    cam_horizontal = phase1_cam_distance * math.cos(iso_angle)
    cam_pos_phase1 = centroid + np.array([cam_horizontal, cam_horizontal, cam_height])
    
    # For phase 2, adjust distance
    cam_height_phase2 = phase2_cam_distance * math.sin(iso_angle)
    cam_horizontal_phase2 = phase2_cam_distance * math.cos(iso_angle)
    cam_pos_phase2 = centroid + np.array([cam_horizontal_phase2, cam_horizontal_phase2, cam_height_phase2])
    
    # Create initial camera pose
    cam_pos = cam_pos_phase1
    forward = centroid - cam_pos
    forward = forward / np.linalg.norm(forward)
    
    right = np.cross(forward, np.array([0, 0, 1]))
    right = right / np.linalg.norm(right)
    
    up = np.cross(right, forward)
    
    cam_pose = np.eye(4)
    cam_pose[:3, 0] = right
    cam_pose[:3, 1] = up
    cam_pose[:3, 2] = -forward
    cam_pose[:3, 3] = cam_pos
    
    # Animation phases (for rotation_mode "switch" only):
    # Phase 1: rotate around Z while zooming out; Phase 2: rotate around X; Phase 3: return
    transition_frames = int(fps * 0.5) if rotation_mode == "switch" else 0
    remaining = frames - (transition_frames * 2)
    phase_frames = remaining // 3 if rotation_mode == "switch" else frames

    intro_frames = phase_frames if rotation_mode == "switch" else frames
    phase2_frames = phase_frames if rotation_mode == "switch" else 0
    outro_frames = remaining - (phase_frames * 2) if rotation_mode == "switch" else 0
    
    # scene setup
    scene = pyrender.Scene(ambient_light=[0.3, 0.3, 0.3])  # Add ambient light to reduce directional light needs
    mesh_node = scene.add(pyrender.Mesh.from_trimesh(mesh, smooth=False))
    
    # Create camera (fixed position)
    camera = pyrender.PerspectiveCamera(yfov=fov)
    cam_node = scene.add(camera, pose=cam_pose)
    
    # Single lighter directional light (ambient handles the rest) at camera position
    light = pyrender.DirectionalLight(intensity=2.0)
    light_node = scene.add(light, pose=cam_pose)
    
    renderer = pyrender.OffscreenRenderer(1024, 1024)
    
    # Get model dimensions for display
    dim_x, dim_y, dim_z = size
    
    # Pre-load font once
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        except:
            font = ImageFont.load_default()
    
    if verbose:
        print(f"Rendering {frames} frames...")
    for i in range(frames):
        if rotation_mode == "z":
            cam_pos = cam_pos_phase1
            scale = 1.0
            angle = 2 * math.pi * (i / frames)
            rotation_matrix = np.array([
                [math.cos(angle), -math.sin(angle), 0, 0],
                [math.sin(angle),  math.cos(angle), 0, 0],
                [0,                0,               1, 0],
                [0,                0,               0, 1]
            ])
        elif rotation_mode == "x":
            cam_pos = cam_pos_phase1
            scale = 1.0
            angle = 2 * math.pi * (i / frames)
            rotation_matrix = np.array([
                [1, 0,                0,               0],
                [0, math.cos(angle), -math.sin(angle), 0],
                [0, math.sin(angle),  math.cos(angle), 0],
                [0, 0,                0,               1]
            ])
        else:
            # rotation_mode == "switch": multi-phase with zoom and direction switch
            if i < intro_frames:
                cam_pos = cam_pos_phase1
            elif i < intro_frames + transition_frames:
                transition_progress = (i - intro_frames) / transition_frames
                cam_pos = cam_pos_phase1 + (cam_pos_phase2 - cam_pos_phase1) * transition_progress
            elif i < intro_frames + transition_frames + phase2_frames:
                cam_pos = cam_pos_phase2
            elif i < intro_frames + transition_frames + phase2_frames + transition_frames:
                transition_progress = (i - intro_frames - transition_frames - phase2_frames) / transition_frames
                cam_pos = cam_pos_phase2 + (cam_pos_phase1 - cam_pos_phase2) * transition_progress
            else:
                cam_pos = cam_pos_phase1

            if i < intro_frames:
                progress = i / intro_frames
                scale = 0.9 + (0.1 * progress)
            elif i >= frames - outro_frames:
                progress = (i - (frames - outro_frames)) / outro_frames
                scale = 1.0 - (0.1 * progress)
            else:
                scale = 1.0

            if i < intro_frames:
                phase_progress = i / intro_frames
                angle = 2 * math.pi * phase_progress * 0.75
                rotation_matrix = np.array([
                    [math.cos(angle), -math.sin(angle), 0, 0],
                    [math.sin(angle),  math.cos(angle), 0, 0],
                    [0,                0,               1, 0],
                    [0,                0,               0, 1]
                ])
            elif i < intro_frames + transition_frames:
                angle = 2 * math.pi * 0.75
                rotation_matrix = np.array([
                    [math.cos(angle), -math.sin(angle), 0, 0],
                    [math.sin(angle),  math.cos(angle), 0, 0],
                    [0,                0,               1, 0],
                    [0,                0,               0, 1]
                ])
            elif i < intro_frames + transition_frames + phase2_frames:
                phase_progress = (i - intro_frames - transition_frames) / phase2_frames
                angle = 2 * math.pi * phase_progress * 0.75
                z_angle = 2 * math.pi * 0.75
                z_rotation = np.array([
                    [math.cos(z_angle), -math.sin(z_angle), 0, 0],
                    [math.sin(z_angle),  math.cos(z_angle), 0, 0],
                    [0,                  0,                 1, 0],
                    [0,                  0,                 0, 1]
                ])
                x_rotation = np.array([
                    [1, 0,                0,               0],
                    [0, math.cos(angle), -math.sin(angle), 0],
                    [0, math.sin(angle),  math.cos(angle), 0],
                    [0, 0,                0,               1]
                ])
                rotation_matrix = z_rotation @ x_rotation
            elif i < intro_frames + transition_frames + phase2_frames + transition_frames:
                z_angle = 2 * math.pi * 0.75
                x_angle = 2 * math.pi * 0.75
                z_rotation = np.array([
                    [math.cos(z_angle), -math.sin(z_angle), 0, 0],
                    [math.sin(z_angle),  math.cos(z_angle), 0, 0],
                    [0,                  0,                 1, 0],
                    [0,                  0,                 0, 1]
                ])
                x_rotation = np.array([
                    [1, 0,                0,               0],
                    [0, math.cos(x_angle), -math.sin(x_angle), 0],
                    [0, math.sin(x_angle),  math.cos(x_angle), 0],
                    [0, 0,                0,               1]
                ])
                rotation_matrix = z_rotation @ x_rotation
            else:
                z_angle = 2 * math.pi * 0.75
                x_angle = 2 * math.pi * 0.75
                outro_progress = (i - (frames - outro_frames)) / outro_frames
                current_z = z_angle * (1 - outro_progress)
                current_x = x_angle * (1 - outro_progress)
                z_rotation = np.array([
                    [math.cos(current_z), -math.sin(current_z), 0, 0],
                    [math.sin(current_z),  math.cos(current_z), 0, 0],
                    [0,                    0,                   1, 0],
                    [0,                    0,                   0, 1]
                ])
                x_rotation = np.array([
                    [1, 0,                    0,                   0],
                    [0, math.cos(current_x), -math.sin(current_x), 0],
                    [0, math.sin(current_x),  math.cos(current_x), 0],
                    [0, 0,                    0,                   1]
                ])
                rotation_matrix = z_rotation @ x_rotation

        # Update camera look-at for current position
        forward = centroid - cam_pos
        forward = forward / np.linalg.norm(forward)
        right = np.cross(forward, np.array([0, 0, 1]))
        right = right / np.linalg.norm(right)
        up = np.cross(right, forward)
        cam_pose = np.eye(4)
        cam_pose[:3, 0] = right
        cam_pose[:3, 1] = up
        cam_pose[:3, 2] = -forward
        cam_pose[:3, 3] = cam_pos
        scene.set_pose(cam_node, cam_pose)
        scene.set_pose(light_node, cam_pose)

        # Apply scale for zoom effect (scale the model, not the camera)
        scale_matrix = np.eye(4)
        scale_matrix[0, 0] = scale
        scale_matrix[1, 1] = scale
        scale_matrix[2, 2] = scale
        
        # Create translation matrices to rotate around centroid instead of origin
        # Translate to origin, rotate, then translate back
        translate_to_origin = np.eye(4)
        translate_to_origin[:3, 3] = -centroid
        
        translate_back = np.eye(4)
        translate_back[:3, 3] = centroid
        
        # Combine transformations: translate to origin, scale, rotate, translate back
        final_transform = translate_back @ rotation_matrix @ scale_matrix @ translate_to_origin
        scene.set_pose(mesh_node, final_transform)
        
        color, _ = renderer.render(scene)
        
        # Add dimensions text overlay
        img = Image.fromarray(color)
        draw = ImageDraw.Draw(img)
        
        # Format dimensions
        text_lines = [
            f"X: {dim_x:.2f}",
            f"Y: {dim_y:.2f}",
            f"Z: {dim_z:.2f}"
        ]
        
        # Position in top right with padding
        padding = 15
        line_spacing = 22
        
        for idx, line in enumerate(text_lines):
            # Get text size
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            
            x = img.width - text_width - padding
            y = padding + (idx * line_spacing)
            
            # Draw text with slight shadow for readability
            draw.text((x+1, y+1), line, fill=(0, 0, 0, 180), font=font)
            draw.text((x, y), line, fill=(255, 255, 255, 255), font=font)
        
        img.save(f"{tmp_dir}/f_{i:04d}.png")
        
        # Progress bar (only when verbose to avoid interleaving with parallel workers)
        if verbose:
            percent = ((i + 1) / frames) * 100
            bar_width = 40
            filled = int(bar_width * (i + 1) / frames)
            bar = '█' * filled + '░' * (bar_width - filled)
            print(f"\rRendering: [{bar}] {percent:.1f}%", end='', flush=True)
    
    if verbose:
        print()  # New line after progress bar
        print("Compiling GIF...")
    # Use pillow mode for faster compilation with optimization
    imgs = []
    for i in range(frames):
        img = Image.open(f"{tmp_dir}/f_{i:04d}.png")
        imgs.append(img)
        
        # Progress bar for loading images
        if verbose:
            percent = ((i + 1) / frames) * 100
            bar_width = 40
            filled = int(bar_width * (i + 1) / frames)
            bar = '█' * filled + '░' * (bar_width - filled)
            print(f"\rLoading frames: [{bar}] {percent:.1f}%", end='', flush=True)
    
    if verbose:
        print()
        print("Saving GIF (this may take a moment)...")
    
    start_time = time.time()
    
    # Save with pillow directly - much faster for large GIFs
    imgs[0].save(
        output_path,
        save_all=True,
        append_images=imgs[1:],
        duration=int(1000/fps),  # duration in milliseconds
        loop=0,
        optimize=False  # Skip optimization for speed
    )
    
    elapsed = time.time() - start_time
    if verbose:
        print(f"GIF saved in {elapsed:.1f} seconds")
        print(f"GIF saved to: {output_path}")
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except OSError:
        pass
    if open_result:
        if open_file(output_path):
            if verbose:
                print("GIF opened successfully!")
        else:
            if verbose:
                print(f"Please open manually: {output_path}")
    return output_path


def _render_one(stl_path, duration_seconds, fps, rotation_mode, output_dir, zoom, verbose=False):
    """Worker for parallel rendering: returns (stl_path, output_path or None, error_msg or None)."""
    try:
        out = make_rotating_gif(
            stl_path,
            duration_seconds=duration_seconds,
            fps=fps,
            rotation_mode=rotation_mode,
            open_result=False,
            output_dir=output_dir,
            zoom=zoom,
            verbose=verbose,
        )
        return (stl_path, out, None)
    except Exception as e:
        return (stl_path, None, str(e))


def main():
    parser = argparse.ArgumentParser(
        description="Render STL model(s) to rotating GIF(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python stl2gif.py model.stl
  python stl2gif.py model.3mf --rotation z
  python stl2gif.py --path model.stl --rotation z
  python stl2gif.py ./models --recursive -o ./gifs
  python stl2gif.py ./models -j 4 -o ./gifs
  python stl2gif.py                    (no args: open file picker)
        """,
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Path to a single .stl/.3mf file or a directory containing mesh files",
    )
    parser.add_argument(
        "-p", "--path",
        default=None,
        metavar="PATH",
        help="Same as positional input: path to a .stl/.3mf file or directory",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="If input is a directory, recurse into subdirectories to find .stl/.3mf files",
    )
    parser.add_argument(
        "--rotation", "-rot",
        choices=["z", "x", "switch"],
        default="switch",
        help="Rotation: z = spin around vertical (turntable), x = tilt around horizontal, switch = Z then X then return (default)",
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=15,
        help="GIF duration in seconds (default: 15)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=20,
        help="Frames per second (default: 20)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the output GIF after rendering",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        metavar="DIR",
        help="Write all output GIFs into this directory (default: next to each source file)",
    )
    parser.add_argument(
        "-j", "--workers",
        type=int,
        default=1,
        metavar="N",
        help="Run up to N renders in parallel (default: 1)",
    )
    parser.add_argument(
        "-z", "--zoom",
        type=float,
        default=1.0,
        metavar="FACTOR",
        help="Zoom level: 1.0 = default, >1 = zoom in (model larger), <1 = zoom out (default: 1.0)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show progress output from each worker when running in parallel (default: quiet when -j > 1)",
    )
    args = parser.parse_args()
    input_path = args.path or args.input

    if input_path is None:
        f = pick_file()
        if f:
            make_rotating_gif(
                f,
                duration_seconds=args.duration,
                fps=args.fps,
                rotation_mode=args.rotation,
                open_result=not args.no_open,
                output_dir=args.output_dir,
                zoom=args.zoom,
            )
        return

    paths = collect_mesh_paths(input_path, args.recursive)
    if not paths:
        print(f"No .stl or .3mf files found at: {input_path}")
        if os.path.isdir(input_path):
            print("Tip: use --recursive to search subdirectories.")
        sys.exit(1)

    print(f"Found {len(paths)} mesh file(s).")
    workers = max(1, args.workers)
    single = len(paths) == 1

    if workers == 1 or single:
        for stl_path in paths:
            print(f"\n--- {stl_path} ---")
            make_rotating_gif(
                stl_path,
                duration_seconds=args.duration,
                fps=args.fps,
                rotation_mode=args.rotation,
                open_result=not args.no_open and single,
                output_dir=args.output_dir,
                zoom=args.zoom,
                verbose=True,
            )
    else:
        n = min(workers, len(paths))
        print(f"Running {n} worker(s) in parallel...")
        done = 0
        failed = []
        with ProcessPoolExecutor(max_workers=n) as executor:
            futures = {
                executor.submit(
                    _render_one,
                    stl_path,
                    args.duration,
                    args.fps,
                    args.rotation,
                    args.output_dir,
                    args.zoom,
                    args.verbose,
                ): stl_path
                for stl_path in paths
            }
            for future in as_completed(futures):
                stl_path, output_path, err = future.result()
                done += 1
                if err:
                    failed.append((stl_path, err))
                    print(f"[{done}/{len(paths)}] FAILED: {os.path.basename(stl_path)}: {err}", flush=True)
                else:
                    print(f"[{done}/{len(paths)}] OK: {os.path.basename(stl_path)} -> {output_path}", flush=True)
        if failed:
            print(f"\n{len(failed)} failed:")
            for stl_path, err in failed:
                print(f"  {stl_path}: {err}")
        if len(paths) > 1:
            print(f"\nDone. Rendered {len(paths) - len(failed)}/{len(paths)} GIF(s).")


if __name__ == "__main__":
    main()
