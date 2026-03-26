import importlib

import bpy

bl_info = {
    "name": "Super Quick Align Pro",
    "author": "Ban va AI",
    "version": (3, 2, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Toolbar (Phim T)",
    "description": "Truc ao tu co gian theo vat the | Thu hep vung hover 2 dau mut",
    "warning": "",
    "doc_url": "",
    "category": "Object",
}

if "super_quick_align" in locals():
    importlib.reload(super_quick_align)
else:
    from . import super_quick_align

if "ui" in locals():
    importlib.reload(ui)
else:
    from . import ui

CLASSES = (
    super_quick_align.OBJECT_OT_super_quick_align,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    ui.register()


def unregister():
    ui.unregister()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)