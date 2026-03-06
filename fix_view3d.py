import os

path = r"g:\My Drive\Libraries\Blender\Blender-Super-Align\Super Align.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix view3d_utils
content = content.replace("view3d_utils.matrix_world.translation_3d", "view3d_utils.location_3d")
content = content.replace("view3d_utils.region_2d_to_matrix_world.translation_3d", "view3d_utils.region_2d_to_location_3d")
content = content.replace("view3d_utils.matrix_world.translation_to", "view3d_utils.location_to") # Just in case

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Fix successfully applied!")
