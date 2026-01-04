#!/usr/bin/env python3
"""
Create simple PNG icons without external dependencies.
Uses a minimal PNG generation approach.
"""

import struct
import zlib
import os

def create_png(width, height, pixels):
    """
    Create a PNG file from raw pixel data.
    pixels should be a list of (r, g, b, a) tuples.
    """
    def png_chunk(chunk_type, data):
        chunk_data = chunk_type + data
        crc = zlib.crc32(chunk_data) & 0xffffffff
        return struct.pack("!I", len(data)) + chunk_data + struct.pack("!I", crc)

    # PNG signature
    png_signature = b'\x89PNG\r\n\x1a\n'

    # IHDR chunk
    ihdr_data = struct.pack("!2I5B", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    ihdr = png_chunk(b'IHDR', ihdr_data)

    # IDAT chunk (image data)
    raw_data = b''
    for y in range(height):
        raw_data += b'\x00'  # Filter type: None
        for x in range(width):
            idx = y * width + x
            if idx < len(pixels):
                r, g, b, a = pixels[idx]
                raw_data += struct.pack('4B', r, g, b, a)
            else:
                raw_data += b'\x00\x00\x00\x00'

    compressed_data = zlib.compress(raw_data, 9)
    idat = png_chunk(b'IDAT', compressed_data)

    # IEND chunk
    iend = png_chunk(b'IEND', b'')

    return png_signature + ihdr + idat + iend

def create_book_icon(size):
    """Create a simple book icon."""
    pixels = []

    # Background color (indigo #6366f1)
    bg_color = (99, 102, 241, 255)

    # Book color (darker indigo #4f46e5)
    book_color = (79, 70, 229, 255)

    # Light color (white-ish #f8fafc)
    light_color = (248, 250, 252, 255)

    for y in range(size):
        for x in range(size):
            # Normalized coordinates (0 to 1)
            nx = x / size
            ny = y / size

            # Create a circular background
            dx = nx - 0.5
            dy = ny - 0.5
            dist = (dx * dx + dy * dy) ** 0.5

            if dist > 0.5:
                # Outside circle - transparent
                pixels.append((0, 0, 0, 0))
            else:
                # Inside circle - background
                if 0.3 < nx < 0.65 and 0.25 < ny < 0.75:
                    # Book area
                    if 0.3 < nx < 0.35:
                        # Spine
                        pixels.append((99, 102, 241, 255))
                    else:
                        # Cover
                        pixels.append(book_color)
                else:
                    # Background
                    pixels.append(bg_color)

    return create_png(size, size, pixels)

def main():
    """Generate all required icon sizes."""
    sizes = [72, 96, 128, 144, 152, 192, 384, 512]
    output_dir = "public/icons"

    os.makedirs(output_dir, exist_ok=True)

    print("Generating simple PNG icons...")
    for size in sizes:
        output_path = os.path.join(output_dir, f"icon-{size}x{size}.png")
        print(f"  Creating {size}x{size} icon...")

        png_data = create_book_icon(size)

        with open(output_path, 'wb') as f:
            f.write(png_data)

        print(f"  ✓ Created {output_path}")

    # Create a simple 32x32 favicon
    print("\nGenerating favicon...")
    favicon_path = "public/favicon.ico"
    png_data = create_book_icon(32)

    # For now, just save as PNG (browsers support .ico as PNG)
    with open(favicon_path, 'wb') as f:
        f.write(png_data)

    print(f"  ✓ Created {favicon_path}")
    print("\n✓ All icons generated successfully!")

if __name__ == "__main__":
    main()
