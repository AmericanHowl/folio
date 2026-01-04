#!/usr/bin/env python3
"""
Generate PWA icons from SVG source.
This script uses available system tools to convert SVG to PNG.
"""

import subprocess
import os
import sys

ICON_SIZES = [72, 96, 128, 144, 152, 192, 384, 512]
SVG_SOURCE = "public/icons/icon.svg"
OUTPUT_DIR = "public/icons"

def check_command(cmd):
    """Check if a command is available."""
    try:
        subprocess.run([cmd, "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def generate_with_inkscape(svg_path, output_path, size):
    """Generate PNG using Inkscape."""
    subprocess.run([
        "inkscape",
        svg_path,
        "--export-filename=" + output_path,
        f"--export-width={size}",
        f"--export-height={size}"
    ], check=True)

def generate_with_imagemagick(svg_path, output_path, size):
    """Generate PNG using ImageMagick."""
    subprocess.run([
        "convert",
        "-background", "none",
        "-resize", f"{size}x{size}",
        svg_path,
        output_path
    ], check=True)

def generate_with_rsvg(svg_path, output_path, size):
    """Generate PNG using rsvg-convert."""
    subprocess.run([
        "rsvg-convert",
        "-w", str(size),
        "-h", str(size),
        svg_path,
        "-o", output_path
    ], check=True)

def main():
    """Generate all icon sizes."""
    # Check which tool is available
    tool = None
    if check_command("inkscape"):
        tool = "inkscape"
        print("Using Inkscape for icon generation")
    elif check_command("convert"):
        tool = "imagemagick"
        print("Using ImageMagick for icon generation")
    elif check_command("rsvg-convert"):
        tool = "rsvg"
        print("Using rsvg-convert for icon generation")
    else:
        print("ERROR: No suitable SVG conversion tool found.")
        print("Please install one of: inkscape, imagemagick, or librsvg2-bin")
        sys.exit(1)

    # Generate icons
    for size in ICON_SIZES:
        output_path = os.path.join(OUTPUT_DIR, f"icon-{size}x{size}.png")
        print(f"Generating {size}x{size} icon...")

        try:
            if tool == "inkscape":
                generate_with_inkscape(SVG_SOURCE, output_path, size)
            elif tool == "imagemagick":
                generate_with_imagemagick(SVG_SOURCE, output_path, size)
            elif tool == "rsvg":
                generate_with_rsvg(SVG_SOURCE, output_path, size)

            print(f"  ✓ Created {output_path}")
        except subprocess.CalledProcessError as e:
            print(f"  ✗ Failed to create {output_path}: {e}")
            sys.exit(1)

    # Create favicon.ico from the 32x32 version (create it first)
    print("\nGenerating favicon.ico...")
    favicon_png = os.path.join(OUTPUT_DIR, "favicon-32x32.png")
    favicon_ico = "public/favicon.ico"

    try:
        if tool == "inkscape":
            generate_with_inkscape(SVG_SOURCE, favicon_png, 32)
        elif tool == "imagemagick":
            generate_with_imagemagick(SVG_SOURCE, favicon_png, 32)
        elif tool == "rsvg":
            generate_with_rsvg(SVG_SOURCE, favicon_png, 32)

        # Convert PNG to ICO
        if tool == "imagemagick":
            subprocess.run(["convert", favicon_png, favicon_ico], check=True)
            print(f"  ✓ Created {favicon_ico}")
        else:
            print(f"  ℹ Created {favicon_png} (use ImageMagick to convert to .ico)")
    except subprocess.CalledProcessError as e:
        print(f"  ✗ Failed to create favicon: {e}")

    print("\n✓ All icons generated successfully!")

if __name__ == "__main__":
    main()
