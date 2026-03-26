import os

import bpy
import bpy.utils.previews

from .super_quick_align import OBJECT_OT_super_quick_align

custom_icons = None


def menu_func(self, context):
    del context
    self.layout.separator()
    self.layout.operator_context = 'INVOKE_DEFAULT'
    icon_id = custom_icons["custom_icon"].icon_id if custom_icons and "custom_icon" in custom_icons else 0
    if icon_id:
        self.layout.operator(
            OBJECT_OT_super_quick_align.bl_idname,
            text="Super Align Pro",
            icon_value=icon_id,
        )
    else:
        self.layout.operator(
            OBJECT_OT_super_quick_align.bl_idname,
            text="Super Align Pro",
            icon='ALIGN_CENTER',
        )


def register():
    global custom_icons

    custom_icons = bpy.utils.previews.new()
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
    if os.path.exists(icon_path):
        custom_icons.load("custom_icon", icon_path, 'IMAGE')
    bpy.types.VIEW3D_MT_object_context_menu.append(menu_func)


def unregister():
    global custom_icons

    try:
        bpy.types.VIEW3D_MT_object_context_menu.remove(menu_func)
    except (AttributeError, ValueError):
        pass

    if custom_icons is not None:
        bpy.utils.previews.remove(custom_icons)
        custom_icons = None