# Super Quick Align Pro

Blender add-on packaged in extension-style layout for quick snap, align, and distribute workflows in the 3D View.

## Structure

- `__init__.py`: Blender package entry point and class registration
- `super_quick_align.py`: core operator logic
- `ui.py`: context menu and icon registration helpers
- `blender_manifest.toml`: Blender Extensions manifest
- `README.md`: project notes and install guide
- `.gitignore`: ignores cache and packaged zip files

## Install

1. Zip the contents of this folder.
2. In Blender, go to `Edit > Preferences > Add-ons`.
3. Click `Install from Disk...` or `Install...`.
4. Choose the zip file.
5. Enable `Super Quick Align Pro`.

## Notes

- The project follows the Blender extension/package pattern with `__init__.py` and `blender_manifest.toml`.
- `__init__.py` stays intentionally small. The operator logic and UI registration are split into separate modules so the addon is easier to read and maintain.