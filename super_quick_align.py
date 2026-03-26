import bpy
import gpu
import blf
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector, geometry
from bpy_extras import view3d_utils


def get_shader():
    shader_names = ['UNLIT', 'POLYLINE_UNLIT_COLOR', '3D_UNLIT_COLOR', '3D_SMOOTH_COLOR', 'POLYLINE_SMOOTH_COLOR']
    for name in shader_names:
        try: return gpu.shader.from_builtin(name)
        except ValueError: continue
    return None

class OBJECT_OT_super_quick_align(bpy.types.Operator):
    """Super Quick Align Tool (Pro Version)"""
    bl_idname = "object.super_quick_align"
    bl_label = "Super Quick Align Pro"
    bl_options = {'REGISTER', 'UNDO'}
    
    _is_running = False

    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'
    
    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        if OBJECT_OT_super_quick_align._is_running:
            return {'PASS_THROUGH'}
        
        OBJECT_OT_super_quick_align._is_running = True
        self.draw_handle_3d = None
        self.draw_handle_2d = None
        self.mouse_pos = (0, 0)
        
        self.active_obj = getattr(context, "active_object", None)
        self.selected_objs = [obj for obj in context.selected_objects if obj != self.active_obj]
        
        self.tool_mode = 'SNAP' 
        self.base_mode = 'SNAP'
        self.show_axes = False
        self.hovered_axis = None 
        self.hovered_align_mode = 'CENTER' 
        
        self.snap_target = None 
        self.snap_normal = Vector((0,0,1))
        self.snap_edge_dir = Vector((1,0,0)) 
        self.current_auto_mode = None 
        
        self.draw_highlight_verts = []
        
        self.distribute_axis = None
        self.input_distance = ""
        self.is_typing = False
        self.current_preview_distance_str = "" 
        
        self.is_ctrl_pressed = False 
        self.is_tab_pressed = False
        self.is_shift_pressed = False
        self.is_alt_pressed = False

        self.draw_handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_3d, (context,), 'WINDOW', 'POST_VIEW'
        )
        self.draw_handle_2d = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_2d, (context,), 'WINDOW', 'POST_PIXEL'
        )
        
        self.update_mode_logic(context)
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def update_status_text(self, context):
        total_selected = len(context.selected_objects)
        parts = []

        if self.is_shift_pressed:
            parts.append("Selection mode")
            parts.append("Click objects to add or remove them")
        elif self.is_typing:
            unit_sym = self.get_unit_symbol(context)
            value = self.input_distance if self.input_distance else "0"
            parts.append(f"Spacing: {value} {unit_sym}")
            parts.append("Enter: confirm")
            parts.append("Backspace: edit")
        else:
            if self.is_tab_pressed:
                parts.append("Mode: Forced Smart Snap")
            elif total_selected <= 1:
                parts.append("Mode: Smart Snap")
            else:
                parts.append(f"Mode: Distribute ({total_selected} objects)")

            if self.tool_mode == 'SNAP':
                if self.is_alt_pressed:
                    if self.current_auto_mode == 'FACE':
                        parts.append("Click: copy and mirror across face plane" if self.is_ctrl_pressed else "Click: mirror across face plane")
                    elif self.current_auto_mode == 'EDGE':
                        parts.append("Click: copy and mirror across edge midpoint plane" if self.is_ctrl_pressed else "Click: mirror across edge midpoint plane")
                    else:
                        parts.append("Hover a face or edge to preview mirror plane")
                    parts.append("Ctrl+Alt: copy and mirror")
                else:
                    if self.current_auto_mode == 'FACE':
                        parts.append("Click: copy and snap to face" if self.is_ctrl_pressed else "Click: snap to face")
                    elif self.current_auto_mode == 'EDGE':
                        parts.append("Click: copy and slide along edge" if self.is_ctrl_pressed else "Click: slide along edge")
                    else:
                        parts.append("Hover a face or edge to preview snapping")
                    parts.append("Ctrl: copy")
                parts.append("Alt: mirror")
                parts.append("Shift: selection")
            else:
                if self.hovered_axis is not None:
                    if self.hovered_align_mode in {'MIN', 'MAX'}:
                        edge_name = 'MIN' if self.hovered_align_mode == 'MIN' else 'MAX'
                        parts.append(f"Click: align all objects to {edge_name}")
                    else:
                        parts.append("Click axis center: distribute evenly")
                        parts.append("Type 0: collapse to center")
                else:
                    parts.append("Hover an axis: middle distributes, ends align")
                parts.append("Tab: force Smart Snap")
                parts.append("Shift: selection")

        try:
            context.workspace.status_text_set(" | ".join(parts))
        except Exception:
            pass
    def mirror_matrix_across_plane(self, matrix_world, plane_point, plane_normal):
        normal = plane_normal.normalized()
        nx, ny, nz = normal
        reflection = Matrix((
            (1.0 - 2.0 * nx * nx, -2.0 * nx * ny, -2.0 * nx * nz, 0.0),
            (-2.0 * ny * nx, 1.0 - 2.0 * ny * ny, -2.0 * ny * nz, 0.0),
            (-2.0 * nz * nx, -2.0 * nz * ny, 1.0 - 2.0 * nz * nz, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        ))
        return Matrix.Translation(plane_point) @ reflection @ Matrix.Translation(-plane_point) @ matrix_world

    def get_snap_preview_matrices(self):
        all_objs = self.selected_objs + [self.active_obj]
        preview_items = []

        if not all_objs or self.snap_target is None:
            return preview_items

        for obj in all_objs:
            preview_matrix = obj.matrix_world.copy()

            if self.is_alt_pressed:
                if self.current_auto_mode == 'FACE':
                    preview_matrix = self.mirror_matrix_across_plane(preview_matrix, self.snap_target, self.snap_normal)
                elif self.current_auto_mode == 'EDGE':
                    preview_matrix = self.mirror_matrix_across_plane(preview_matrix, self.snap_target, self.snap_edge_dir)
                else:
                    continue
            elif self.current_auto_mode == 'FACE':
                bbox_corners = [preview_matrix @ Vector(corner) for corner in obj.bound_box]
                distances = [(corner - self.snap_target).dot(self.snap_normal) for corner in bbox_corners]
                center_pt = sum(bbox_corners, Vector()) / 8.0
                center_dist = (center_pt - self.snap_target).dot(self.snap_normal)
                dist_to_move = min(distances) if center_dist >= 0 else max(distances)
                preview_matrix.translation -= self.snap_normal * dist_to_move
            elif self.current_auto_mode == 'EDGE':
                bbox_corners = [preview_matrix @ Vector(corner) for corner in obj.bound_box]
                center_pt = sum(bbox_corners, Vector((0, 0, 0))) / 8.0
                vec_center_to_midpoint = self.snap_target - center_pt
                translation_vec = vec_center_to_midpoint.dot(self.snap_edge_dir) * self.snap_edge_dir
                preview_matrix.translation += translation_vec
            else:
                continue

            preview_items.append((obj, preview_matrix))

        return preview_items

    def draw_preview_bboxes(self, shader, preview_items):
        if not preview_items:
            return

        bbox_edge_indices = (
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        )
        line_coords = []

        if self.is_alt_pressed and self.is_ctrl_pressed:
            line_color = (0.45, 1.0, 0.45, 0.95)
        elif self.is_alt_pressed:
            line_color = (1.0, 0.65, 0.25, 0.95)
        elif self.is_ctrl_pressed:
            line_color = (0.25, 1.0, 0.45, 0.95)
        else:
            line_color = (0.25, 1.0, 1.0, 0.9)

        for obj, preview_matrix in preview_items:
            if obj == self.active_obj and obj.type == 'MESH' and getattr(obj.data, 'edges', None):
                verts = obj.data.vertices
                for edge in obj.data.edges:
                    line_coords.extend([
                        preview_matrix @ verts[edge.vertices[0]].co,
                        preview_matrix @ verts[edge.vertices[1]].co,
                    ])
            else:
                corners = [preview_matrix @ Vector(corner) for corner in obj.bound_box]
                for start_idx, end_idx in bbox_edge_indices:
                    line_coords.extend([corners[start_idx], corners[end_idx]])

        batch_lines = batch_for_shader(shader, 'LINES', {"pos": line_coords, "color": [line_color] * len(line_coords)})
        try:
            gpu.state.line_width_set(2.0)
        except:
            pass
        batch_lines.draw(shader)

    def get_unit_multiplier(self, context):
        unit_settings = context.scene.unit_settings
        if unit_settings.system == 'NONE': return 1.0
        multiplier = 1.0
        length_unit = unit_settings.length_unit
        if length_unit == 'KILOMETERS': multiplier = 1000.0
        elif length_unit == 'METERS': multiplier = 1.0
        elif length_unit == 'CENTIMETERS': multiplier = 0.01
        elif length_unit == 'MILLIMETERS': multiplier = 0.001
        elif length_unit == 'MICROMETERS': multiplier = 0.000001
        elif length_unit == 'MILES': multiplier = 1609.344
        elif length_unit == 'FEET': multiplier = 0.3048
        elif length_unit == 'INCHES': multiplier = 0.0254
        elif length_unit == 'THOU': multiplier = 0.0000254
        return multiplier * unit_settings.scale_length

    def get_unit_symbol(self, context):
        unit_settings = context.scene.unit_settings
        if unit_settings.system == 'NONE': return "Units"
        symbols = {
            'KILOMETERS': 'km', 'METERS': 'm', 'CENTIMETERS': 'cm', 
            'MILLIMETERS': 'mm', 'MICROMETERS': 'Ã‚Âµm', 'MILES': 'mi', 
            'FEET': 'ft', 'INCHES': 'in', 'THOU': 'thou'
        }
        return symbols.get(unit_settings.length_unit, 'm')

    def get_selection_center(self):
        all_objs = self.selected_objs + [self.active_obj] if self.active_obj else []
        if not all_objs: return Vector((0, 0, 0))
        return sum([obj.matrix_world.translation for obj in all_objs], Vector()) / len(all_objs)

    def get_dynamic_scale(self, context, origin_3d, desired_pixels=60.0):
        region = context.region
        rv3d = context.region_data
        loc_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, origin_3d)
        if not loc_2d: 
            cam_dist = (origin_3d - rv3d.view_matrix.inverted().translation).length
            return cam_dist * 0.1
        loc_3d_offset = view3d_utils.region_2d_to_location_3d(region, rv3d, loc_2d + Vector((100.0, 0.0)), origin_3d)
        scale_per_100px = (loc_3d_offset - origin_3d).length
        return scale_per_100px * (desired_pixels / 100.0)

    def raycast_select(self, context, event):
        region = context.region
        rv3d = context.region_data
        coord = (event.mouse_region_x, event.mouse_region_y)
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        
        hit, location, normal, index, hit_obj, matrix = context.scene.ray_cast(
            context.view_layer.depsgraph, ray_origin, view_vector
        )
        
        if hit and hit_obj:
            hit_obj.select_set(not hit_obj.select_get())
            if hit_obj.select_get():
                context.view_layer.objects.active = hit_obj
            else:
                if hit_obj == context.active_object:
                    sel = context.selected_objects
                    context.view_layer.objects.active = sel[-1] if sel else None
                    
            self.active_obj = context.active_object
            self.selected_objs = [o for o in context.selected_objects if o != self.active_obj]

    def update_preview_distance(self, context):
        if self.tool_mode == 'DISTRIBUTE' and self.hovered_axis is not None and self.hovered_align_mode == 'CENTER':
            all_objs = self.selected_objs + [self.active_obj]
            if len(all_objs) >= 2:
                axis_idx = self.hovered_axis
                vals = [obj.matrix_world.translation[axis_idx] for obj in all_objs]
                min_val = min(vals)
                max_val = max(vals)
                step_internal = (max_val - min_val) / (len(all_objs) - 1)
                
                multiplier = self.get_unit_multiplier(context)
                step_display = step_internal / multiplier if multiplier != 0 else step_internal
                unit_sym = self.get_unit_symbol(context)
                self.current_preview_distance_str = f"{step_display:.2f} {unit_sym}"
            else:
                self.current_preview_distance_str = ""
        else:
            self.current_preview_distance_str = ""

    def execute_snap(self, context, is_copy, is_mirror=False):
        all_objs = self.selected_objs + [self.active_obj]
        target_objs = []
        if is_copy:
            for obj in all_objs:
                new_obj = obj.copy() 
                context.collection.objects.link(new_obj)
                target_objs.append(new_obj)
        else:
            target_objs = all_objs 
        
        if is_mirror:
            if self.current_auto_mode == 'FACE':
                plane_point = self.snap_target
                plane_normal = self.snap_normal
                undo_message = "Copy & Mirror Across Face" if is_copy else "Mirror Across Face"
            elif self.current_auto_mode == 'EDGE':
                plane_point = self.snap_target
                plane_normal = self.snap_edge_dir
                undo_message = "Copy & Mirror Across Edge Midpoint Plane" if is_copy else "Mirror Across Edge Midpoint Plane"
            else:
                plane_point = None
                plane_normal = None
                undo_message = None

            if plane_point is not None and plane_normal is not None:
                for obj in target_objs:
                    obj.matrix_world = self.mirror_matrix_across_plane(obj.matrix_world.copy(), plane_point, plane_normal)
                bpy.ops.ed.undo_push(message=undo_message)

        elif self.current_auto_mode == 'FACE':
            for i, obj in enumerate(all_objs): 
                bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                distances = [(corner - self.snap_target).dot(self.snap_normal) for corner in bbox_corners]
                center_pt = sum(bbox_corners, Vector()) / 8.0
                center_dist = (center_pt - self.snap_target).dot(self.snap_normal)
                
                if center_dist >= 0: dist_to_move = min(distances)
                else: dist_to_move = max(distances)
                target_objs[i].matrix_world.translation -= (self.snap_normal * dist_to_move)
            bpy.ops.ed.undo_push(message="Instance & Stamp to Plane" if is_copy else "Absolute Snap to Plane")
        
        elif self.current_auto_mode == 'EDGE':
            for i, obj in enumerate(all_objs):
                bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                center_pt = sum(bbox_corners, Vector((0,0,0))) / 8.0
                vec_center_to_midpoint = self.snap_target - center_pt
                translation_vec = vec_center_to_midpoint.dot(self.snap_edge_dir) * self.snap_edge_dir
                target_objs[i].matrix_world.translation += translation_vec
            bpy.ops.ed.undo_push(message="Instance & Slide to Edge" if is_copy else "Snap Objects to Edge")

        if is_copy and target_objs:
            for obj in context.selected_objects:
                obj.select_set(False)

            for obj in target_objs:
                obj.select_set(True)

            new_active = target_objs[-1] if self.active_obj else target_objs[0]
            context.view_layer.objects.active = new_active
            self.active_obj = new_active
            self.selected_objs = [obj for obj in target_objs if obj != new_active]

        self.update_status_text(context)

    def update_mode_logic(self, context):
        total_selected = len(context.selected_objects)
        
        if total_selected > 1:
            self.base_mode = 'DISTRIBUTE'
        else:
            self.base_mode = 'SNAP'
            
        if self.is_tab_pressed:
            self.tool_mode = 'SNAP'
        else:
            self.tool_mode = self.base_mode

        if self.is_shift_pressed:
            self.show_axes = False
            self.snap_target = None
            self.hovered_axis = None
            self.current_preview_distance_str = ""
            self.draw_highlight_verts.clear()
        else:
            if self.tool_mode == 'DISTRIBUTE':
                self.show_axes = True
                self.snap_target = None
                self.draw_highlight_verts.clear()
                self.hovered_axis, self.hovered_align_mode = self.get_hovered_axis(context)
                self.update_preview_distance(context)
            else:
                self.show_axes = False
                self.hovered_axis = None
                self.current_preview_distance_str = ""
                self.find_snap_target(context)
        self.update_status_text(context)

    def modal(self, context, event):
        try:
            context.area.tag_redraw()

            if context.active_object:
                self.active_obj = context.active_object
                self.selected_objs = [obj for obj in context.selected_objects if obj != self.active_obj]
            else:
                self.active_obj = None
                self.selected_objs = []

            if event.type == 'Z' and event.value == 'PRESS' and (event.ctrl or event.oskey):
                try:
                    if event.shift:
                        bpy.ops.ed.redo()
                        self.report({'INFO'}, "Redo: BÃ†Â°Ã¡Â»â€ºc tiÃ¡ÂºÂ¿p theo")
                    else:
                        bpy.ops.ed.undo()
                        self.report({'INFO'}, "Undo: Ã„ÂÃƒÂ£ lÃƒÂ¹i lÃ¡ÂºÂ¡i 1 bÃ†Â°Ã¡Â»â€ºc")
                except Exception as e: pass

                try:
                    self.active_obj = bpy.context.active_object
                    if self.active_obj:
                        self.selected_objs = [obj for obj in bpy.context.selected_objects if obj != self.active_obj]
                    else:
                        self.selected_objs = []
                except ReferenceError: pass
                return {'RUNNING_MODAL'}

            if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'}:
                return {'PASS_THROUGH'}

            if event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
                return {'RUNNING_MODAL'}

            if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT', 'RIGHT_ALT'}:
                self.is_shift_pressed = event.shift
                self.is_ctrl_pressed = event.ctrl
                self.is_alt_pressed = event.alt
                self.update_mode_logic(context)
                return {'RUNNING_MODAL'}

            if event.type == 'TAB':
                if event.value == 'PRESS':
                    self.is_tab_pressed = True
                elif event.value == 'RELEASE':
                    self.is_tab_pressed = False
                self.update_mode_logic(context)
                return {'RUNNING_MODAL'}

            if self.is_typing and event.value == 'PRESS':
                if event.type in {'RET', 'NUMPAD_ENTER'}:
                    self.is_typing = False
                    self.update_status_text(context)
                    return {'RUNNING_MODAL'}
                elif event.type == 'BACK_SPACE':
                    self.input_distance = self.input_distance[:-1]
                    self.apply_exact_distance(context)
                    self.update_status_text(context)
                    return {'RUNNING_MODAL'}
                elif event.unicode.isdigit() or event.unicode in {'.', '-'}:
                    self.input_distance += event.unicode
                    self.apply_exact_distance(context)
                    self.update_status_text(context)
                    return {'RUNNING_MODAL'}

            if event.type == 'MOUSEMOVE':
                new_pos = (event.mouse_region_x, event.mouse_region_y)
                if abs(new_pos[0] - self.mouse_pos[0]) > 2 or abs(new_pos[1] - self.mouse_pos[1]) > 2:
                    self.mouse_pos = new_pos
                    self.update_mode_logic(context)
                return {'RUNNING_MODAL'} 

            if event.type in {'ESC'} and event.value == 'PRESS':
                self.cleanup(context)
                return {'CANCELLED'}

            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                if event.shift:
                    self.raycast_select(context, event)
                    self.update_mode_logic(context)
                    return {'RUNNING_MODAL'}

                if self.tool_mode == 'SNAP':
                    if self.snap_target is not None:
                        self.execute_snap(context, is_copy=event.ctrl, is_mirror=event.alt) 
                        return {'RUNNING_MODAL'}

                elif self.tool_mode == 'DISTRIBUTE':
                    if self.hovered_axis is not None:
                        if self.hovered_align_mode in {'MIN', 'MAX'}:
                            if len(context.selected_objects) > 0:
                                self.align_objects(self.hovered_axis, self.hovered_align_mode)
                                bpy.ops.ed.undo_push(message=f"Align objects to {self.hovered_align_mode}")
                        else:
                            if len(context.selected_objects) > 1:
                                self.distribute_objects_evenly(self.hovered_axis)
                                self.distribute_axis = self.hovered_axis
                                self.is_typing = True 
                                self.input_distance = ""
                                bpy.ops.ed.undo_push(message="Distribute evenly")
                        return {'RUNNING_MODAL'}

                return {'PASS_THROUGH'}

            return {'RUNNING_MODAL'} 


        except Exception as e:
            print(f"Super Align Fatal Error: {e}")
            self.cleanup(context)
            return {'CANCELLED'}

    def find_snap_target(self, context):
        region = context.region
        rv3d = context.region_data
        coord = self.mouse_pos
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

        hit, location, normal, index, obj, matrix = context.scene.ray_cast(
            context.view_layer.depsgraph, ray_origin, view_vector
        )

        self.draw_highlight_verts.clear()
        self.snap_target = None
        self.current_auto_mode = None

        if hit and obj.type == 'MESH':
            mesh = obj.data
            poly = mesh.polygons[index]
            matrix_world = obj.matrix_world
            verts = poly.vertices
            
            best_edge = None
            best_edge_dir = None
            min_dist_2d = 12.0 
            edge_midpoint = None
            
            mouse_vec_2d = Vector((coord[0], coord[1]))
            face_verts_3d = []
            
            for i in range(len(verts)):
                v1_idx = verts[i]
                v2_idx = verts[(i + 1) % len(verts)]
                v1 = matrix_world @ mesh.vertices[v1_idx].co
                v2 = matrix_world @ mesh.vertices[v2_idx].co
                
                face_verts_3d.extend([v1, v2]) 
                
                proj_pt, _ = geometry.intersect_point_line(location, v1, v2)
                vec_edge = v2 - v1
                vec_len = vec_edge.length
                
                if vec_len > 0:
                    vec_dir = vec_edge / vec_len
                    proj_t = (proj_pt - v1).dot(vec_dir)
                    if 0 <= proj_t <= vec_len:
                        proj_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, proj_pt)
                        if proj_2d:
                            dist_2d = (mouse_vec_2d - proj_2d).length
                            if dist_2d < min_dist_2d:
                                min_dist_2d = dist_2d
                                best_edge = (v1, v2)
                                best_edge_dir = vec_dir
                                edge_midpoint = (v1 + v2) / 2.0

            if best_edge:
                self.current_auto_mode = 'EDGE'
                self.snap_target = edge_midpoint
                self.snap_edge_dir = best_edge_dir
                self.draw_highlight_verts.extend([best_edge[0], best_edge[1]])
            else:
                self.current_auto_mode = 'FACE'
                self.snap_target = location
                self.snap_normal = normal
                self.draw_highlight_verts.extend(face_verts_3d)

    def align_objects(self, axis_index, mode):
        all_objs = self.selected_objs + [self.active_obj]
        if mode == 'MIN':
            target_val = min([obj.matrix_world.translation[axis_index] for obj in all_objs])
        elif mode == 'MAX':
            target_val = max([obj.matrix_world.translation[axis_index] for obj in all_objs])
            
        for obj in all_objs:
            loc = obj.matrix_world.translation.copy()
            loc[axis_index] = target_val
            obj.matrix_world.translation = loc
        bpy.context.view_layer.update()

    def distribute_objects_evenly(self, axis_index):
        all_objs = self.selected_objs + [self.active_obj]
        all_objs.sort(key=lambda obj: obj.matrix_world.translation[axis_index])
        min_val = all_objs[0].matrix_world.translation[axis_index]
        max_val = all_objs[-1].matrix_world.translation[axis_index]
        step = (max_val - min_val) / (len(all_objs) - 1)
        for i, obj in enumerate(all_objs):
            loc = obj.matrix_world.translation.copy()
            loc[axis_index] = min_val + (i * step)
            obj.matrix_world.translation = loc
        bpy.context.view_layer.update()

    def apply_exact_distance(self, context):
        try: dist_input = float(self.input_distance)
        except ValueError: return 
        
        multiplier = self.get_unit_multiplier(context)
        dist_internal = dist_input * multiplier
        
        axis_index = self.distribute_axis
        all_objs = self.selected_objs + [self.active_obj]
        all_objs.sort(key=lambda obj: obj.matrix_world.translation[axis_index])
        
        center_val = sum(obj.matrix_world.translation[axis_index] for obj in all_objs) / len(all_objs)
        total_width = dist_internal * (len(all_objs) - 1)
        start_val = center_val - (total_width / 2.0)
        
        for i, obj in enumerate(all_objs):
            loc = obj.matrix_world.translation.copy()
            loc[axis_index] = start_val + (i * dist_internal)
            obj.matrix_world.translation = loc
            
        bpy.context.view_layer.update()

    # --- THUÃ¡ÂºÂ¬T TOÃƒÂN MÃ¡Â»Å¡I: TÃƒÂNH TOÃƒÂN CHIÃ¡Â»â‚¬U DÃƒâ‚¬I TRÃ¡Â»Â¤C THEO BOUNDING VÃƒâ‚¬ VÃƒâ„¢NG HOVER CÃ¡Â»Â Ã„ÂÃ¡Â»Å NH ---
    def get_hovered_axis(self, context):
        if not getattr(self, "active_obj", None): return None, 'CENTER'
        
        region = context.region
        rv3d = context.region_data
        origin_3d = self.get_selection_center()
        
        # ThÃƒÂªm lÃ¡Â»Â (margin) 40 pixels khÃƒÂ´ng gian mÃƒÂ n hÃƒÂ¬nh vÃƒÂ o Ã„â€˜uÃƒÂ´i trÃ¡Â»Â¥c Ã¡ÂºÂ£o
        margin_3d = self.get_dynamic_scale(context, origin_3d, 40.0) 
        mouse_vec = Vector((self.mouse_pos[0], self.mouse_pos[1]))
        
        best_axis = None
        best_mode = 'CENTER'
        min_dist = 25.0 
        
        axes = [Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1))]
        all_objs = self.selected_objs + [self.active_obj]
        
        for i, axis in enumerate(axes):
            # TÃƒÂ­nh giÃ¡Â»â€ºi hÃ¡ÂºÂ¡n toÃ¡ÂºÂ¡ Ã„â€˜Ã¡Â»â„¢ theo trÃ¡Â»Â¥c
            min_val = min(obj.matrix_world.translation[i] for obj in all_objs)
            max_val = max(obj.matrix_world.translation[i] for obj in all_objs)
            
            # Ã„ÂÃ¡ÂºÂ£m bÃ¡ÂºÂ£o trÃ¡Â»Â¥c khÃƒÂ´ng bÃ¡Â»â€¹ biÃ¡ÂºÂ¿n mÃ¡ÂºÂ¥t nÃ¡ÂºÂ¿u cÃƒÂ¡c vÃ¡ÂºÂ­t thÃ¡Â»Æ’ trÃƒÂ¹ng nhau
            if max_val - min_val < margin_3d:
                start_val = origin_3d[i] - margin_3d
                end_val = origin_3d[i] + margin_3d
            else:
                start_val = min_val - margin_3d
                end_val = max_val + margin_3d
                
            start_3d = origin_3d.copy()
            start_3d[i] = start_val
            end_3d = origin_3d.copy()
            end_3d[i] = end_val
            
            start_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, start_3d)
            end_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, end_3d)
            if not start_2d or not end_2d: continue
            
            line_vec = end_2d - start_2d
            line_len = line_vec.length
            if line_len == 0: continue
            
            line_dir = line_vec / line_len
            proj = (mouse_vec - start_2d).dot(line_dir) 
            
            if 0 <= proj <= line_len:
                closest_point = start_2d + line_dir * proj
                dist = (mouse_vec - closest_point).length
                if dist < min_dist:
                    min_dist = dist
                    best_axis = i
                    
                    # GiÃ¡Â»â€ºi hÃ¡ÂºÂ¡n Ã„â€˜Ã¡Â»â„¢ lÃ¡Â»â€ºn vÃƒÂ¹ng Hover cÃ¡Â»â€˜ Ã„â€˜Ã¡Â»â€¹nh 30 pixels Ã¡Â»Å¸ 2 mÃƒÂºt
                    hover_zone_px = 30.0 
                    
                    # NÃ¡ÂºÂ¿u trÃ¡Â»Â¥c trÃƒÂªn mÃƒÂ n hÃƒÂ¬nh quÃƒÂ¡ ngÃ¡ÂºÂ¯n, chia tÃ¡Â»Â· lÃ¡Â»â€¡ 15% / 70% / 15%
                    if line_len < hover_zone_px * 2.5:
                        if proj < line_len * 0.15: best_mode = 'MIN'
                        elif proj > line_len * 0.85: best_mode = 'MAX'
                        else: best_mode = 'CENTER'
                    # NÃ¡ÂºÂ¿u trÃ¡Â»Â¥c Ã„â€˜Ã¡Â»Â§ dÃƒÂ i, khÃƒÂ³a chÃ¡ÂºÂ¿t 30 pixels Ã¡Â»Å¸ mÃƒÂ©p
                    else:
                        if proj < hover_zone_px: best_mode = 'MIN'
                        elif proj > line_len - hover_zone_px: best_mode = 'MAX'
                        else: best_mode = 'CENTER'
                        
        return best_axis, best_mode

    def draw_3d(self, context):
        try:
            if not getattr(self, "active_obj", None): return
            origin = self.get_selection_center() 
            shader = get_shader()
            if not shader: return
            
            if self.tool_mode == 'SNAP' and self.snap_target is not None and not self.is_shift_pressed:
                hl_color = (0.0, 1.0, 0.0, 1.0) if self.is_ctrl_pressed else (0.0, 1.0, 1.0, 1.0)
                if self.current_auto_mode == 'EDGE':
                    hl_color = (0.0, 1.0, 0.0, 1.0) if self.is_ctrl_pressed else (1.0, 0.5, 0.0, 1.0)
                
                if self.draw_highlight_verts:
                    colors = [hl_color] * len(self.draw_highlight_verts)
                    batch_lines = batch_for_shader(shader, 'LINES', {"pos": self.draw_highlight_verts, "color": colors})
                    gpu.state.depth_test_set('NONE')
                    gpu.state.blend_set('ALPHA')
                    try: gpu.state.line_width_set(4.0)
                    except: pass
                    shader.bind()
                    batch_lines.draw(shader)
                    
                    if self.is_alt_pressed:
                        plane_normal = self.snap_normal if self.current_auto_mode == 'FACE' else self.snap_edge_dir
                        plane_normal = plane_normal.normalized()
                        ref_axis = Vector((0, 0, 1)) if abs(plane_normal.dot(Vector((0, 0, 1)))) < 0.9 else Vector((0, 1, 0))
                        plane_u = plane_normal.cross(ref_axis).normalized()
                        plane_v = plane_normal.cross(plane_u).normalized()
                        s = self.get_dynamic_scale(context, self.snap_target, 16.0)
                        plane_corners = [
                            self.snap_target + (-plane_u - plane_v) * s,
                            self.snap_target + (plane_u - plane_v) * s,
                            self.snap_target + (plane_u + plane_v) * s,
                            self.snap_target + (-plane_u + plane_v) * s,
                        ]
                        plane_fill = [plane_corners[0], plane_corners[1], plane_corners[2], plane_corners[0], plane_corners[2], plane_corners[3]]
                        plane_outline = [
                            plane_corners[0], plane_corners[1],
                            plane_corners[1], plane_corners[2],
                            plane_corners[2], plane_corners[3],
                            plane_corners[3], plane_corners[0],
                        ]
                        batch_plane_fill = batch_for_shader(shader, 'TRIS', {"pos": plane_fill, "color": [(1.0, 0.45, 0.15, 0.18)] * len(plane_fill)})
                        batch_plane_outline = batch_for_shader(shader, 'LINES', {"pos": plane_outline, "color": [(1.0, 0.7, 0.25, 1.0)] * len(plane_outline)})
                        batch_plane_fill.draw(shader)
                        try: gpu.state.line_width_set(2.0)
                        except: pass
                        batch_plane_outline.draw(shader)
                    elif self.current_auto_mode == 'EDGE':
                        plane_normal = self.snap_edge_dir.normalized()
                        ref_axis = Vector((0, 0, 1)) if abs(plane_normal.dot(Vector((0, 0, 1)))) < 0.9 else Vector((0, 1, 0))
                        plane_u = plane_normal.cross(ref_axis).normalized()
                        plane_v = plane_normal.cross(plane_u).normalized()
                        s = self.get_dynamic_scale(context, self.snap_target, 12.0)
                        plane_corners = [
                            self.snap_target + (-plane_u - plane_v) * s,
                            self.snap_target + (plane_u - plane_v) * s,
                            self.snap_target + (plane_u + plane_v) * s,
                            self.snap_target + (-plane_u + plane_v) * s,
                        ]
                        plane_fill = [plane_corners[0], plane_corners[1], plane_corners[2], plane_corners[0], plane_corners[2], plane_corners[3]]
                        plane_outline = [
                            plane_corners[0], plane_corners[1],
                            plane_corners[1], plane_corners[2],
                            plane_corners[2], plane_corners[3],
                            plane_corners[3], plane_corners[0],
                        ]
                        batch_plane_fill = batch_for_shader(shader, 'TRIS', {"pos": plane_fill, "color": [(1.0, 0.95, 0.25, 0.18)] * len(plane_fill)})
                        batch_plane_outline = batch_for_shader(shader, 'LINES', {"pos": plane_outline, "color": [(1.0, 1.0, 0.35, 1.0)] * len(plane_outline)})
                        batch_plane_fill.draw(shader)
                        try: gpu.state.line_width_set(2.0)
                        except: pass
                        batch_plane_outline.draw(shader)

                    preview_items = self.get_snap_preview_matrices()
                    self.draw_preview_bboxes(shader, preview_items)
                    
                    gpu.state.blend_set('NONE')
                    gpu.state.depth_test_set('LESS_EQUAL')
                return

            if self.show_axes and not self.is_shift_pressed:
                margin_3d = self.get_dynamic_scale(context, origin, 40.0)
                all_objs = self.selected_objs + [self.active_obj]
                
                coords = []
                base_colors = [(1.0, 0.2, 0.2), (0.2, 1.0, 0.2), (0.2, 0.5, 1.0)]
                colors = []
                
                # VÃ¡ÂºÂ½ lÃ¡ÂºÂ¡i cÃƒÂ¡c Ã„â€˜oÃ¡ÂºÂ¡n trÃ¡Â»Â¥c co giÃƒÂ£n theo toÃ¡ÂºÂ¡ Ã„â€˜Ã¡Â»â„¢
                for i in range(3):
                    min_val = min(obj.matrix_world.translation[i] for obj in all_objs)
                    max_val = max(obj.matrix_world.translation[i] for obj in all_objs)
                    
                    if max_val - min_val < margin_3d:
                        start_val = origin[i] - margin_3d
                        end_val = origin[i] + margin_3d
                    else:
                        start_val = min_val - margin_3d
                        end_val = max_val + margin_3d
                        
                    start_3d = origin.copy()
                    start_3d[i] = start_val
                    end_3d = origin.copy()
                    end_3d[i] = end_val
                    
                    coords.extend([start_3d, end_3d])
                    alpha = 1.0 if self.hovered_axis == i else 0.3
                    colors.extend([(base_colors[i][0], base_colors[i][1], base_colors[i][2], alpha)] * 2)

                batch = batch_for_shader(shader, 'LINES', {"pos": coords, "color": colors})

                gpu.state.depth_test_set('NONE')
                gpu.state.blend_set('ALPHA') 
                try: gpu.state.line_width_set(4.0)
                except: pass 
                shader.bind()
                batch.draw(shader)
                
                # --- VÃ¡ÂºÂ¼ DIMENSION LINES ---
                if self.hovered_axis is not None and self.hovered_align_mode == 'CENTER' and len(all_objs) >= 2:
                    axis_idx = self.hovered_axis
                    axis_vec = [Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1))][axis_idx]
                    sorted_objs = sorted(all_objs, key=lambda obj: obj.matrix_world.translation[axis_idx])
                    
                    rv3d = context.region_data
                    cam_vec = rv3d.view_matrix.inverted().col[2].xyz
                    tick_vec = axis_vec.cross(cam_vec).normalized()
                    if tick_vec.length == 0: 
                        tick_vec = Vector((0,1,0)) if axis_idx != 1 else Vector((1,0,0))
                        
                    tick_size = self.get_dynamic_scale(context, origin, 8.0) 
                    dim_lines = []
                    tick_lines = []
                    
                    for i in range(len(sorted_objs) - 1):
                        p1 = origin.copy()
                        p1[axis_idx] = sorted_objs[i].matrix_world.translation[axis_idx]
                        p2 = origin.copy()
                        p2[axis_idx] = sorted_objs[i+1].matrix_world.translation[axis_idx]
                        
                        dim_lines.extend([p1, p2])
                        tick_lines.extend([p1 - tick_vec*tick_size, p1 + tick_vec*tick_size])
                        tick_lines.extend([p2 - tick_vec*tick_size, p2 + tick_vec*tick_size])

                    color = (base_colors[axis_idx][0], base_colors[axis_idx][1], base_colors[axis_idx][2], 0.7)
                    if dim_lines:
                        batch_dim = batch_for_shader(shader, 'LINES', {"pos": dim_lines, "color": [color]*len(dim_lines)})
                        try: gpu.state.line_width_set(2.0)
                        except: pass
                        batch_dim.draw(shader)
                        
                    if tick_lines:
                        batch_tick = batch_for_shader(shader, 'LINES', {"pos": tick_lines, "color": [(1, 1, 1, 0.6)]*len(tick_lines)})
                        try: gpu.state.line_width_set(1.0)
                        except: pass
                        batch_tick.draw(shader)

                # --- VÃ¡ÂºÂ¼ NGÃƒâ€I SAO ALIGN Ã¡Â»Å¾ MIN/MAX TÃ†Â¯Ã†Â NG Ã¡Â»Â¨NG MÃ¡Â»Å¡I ---
                if self.hovered_axis is not None and self.hovered_align_mode in {'MIN', 'MAX'}:
                    axis_idx = self.hovered_axis
                    min_val = min(obj.matrix_world.translation[axis_idx] for obj in all_objs)
                    max_val = max(obj.matrix_world.translation[axis_idx] for obj in all_objs)
                    
                    if max_val - min_val < margin_3d:
                        start_val = origin[axis_idx] - margin_3d
                        end_val = origin[axis_idx] + margin_3d
                    else:
                        start_val = min_val - margin_3d
                        end_val = max_val + margin_3d
                        
                    point_3d = origin.copy()
                    if self.hovered_align_mode == 'MIN':
                        point_3d[axis_idx] = start_val
                    else:
                        point_3d[axis_idx] = end_val
                        
                    s = self.get_dynamic_scale(context, point_3d, 10.0)
                    plane_axes = [
                        (Vector((0, 1, 0)), Vector((0, 0, 1))),
                        (Vector((1, 0, 0)), Vector((0, 0, 1))),
                        (Vector((1, 0, 0)), Vector((0, 1, 0))),
                    ]
                    plane_u, plane_v = plane_axes[axis_idx]
                    corners = [
                        point_3d + (-plane_u - plane_v) * s,
                        point_3d + (plane_u - plane_v) * s,
                        point_3d + (plane_u + plane_v) * s,
                        point_3d + (-plane_u + plane_v) * s,
                    ]
                    plane_fill = [corners[0], corners[1], corners[2], corners[0], corners[2], corners[3]]
                    plane_outline = [
                        corners[0], corners[1],
                        corners[1], corners[2],
                        corners[2], corners[3],
                        corners[3], corners[0],
                    ]
                    fill_color = [(1.0, 0.9, 0.2, 0.18)] * len(plane_fill)
                    outline_color = [(1.0, 0.95, 0.35, 0.95)] * len(plane_outline)
                    batch_plane_fill = batch_for_shader(shader, 'TRIS', {"pos": plane_fill, "color": fill_color})
                    batch_plane_outline = batch_for_shader(shader, 'LINES', {"pos": plane_outline, "color": outline_color})
                    batch_plane_fill.draw(shader)
                    try: gpu.state.line_width_set(2.5)
                    except: pass
                    batch_plane_outline.draw(shader)

                gpu.state.blend_set('NONE')
                gpu.state.depth_test_set('LESS_EQUAL')
            
        except Exception as e:
            pass

    def draw_2d(self, context):
        font_id = 0
        all_objs = self.selected_objs + [self.active_obj]
        
        if self.tool_mode == 'DISTRIBUTE' and self.hovered_axis is not None and self.hovered_align_mode == 'CENTER' and len(all_objs) >= 2 and not self.is_shift_pressed:
            axis_idx = self.hovered_axis
            origin = self.get_selection_center()
            sorted_objs = sorted(all_objs, key=lambda obj: obj.matrix_world.translation[axis_idx])
            multiplier = self.get_unit_multiplier(context)
            unit_sym = self.get_unit_symbol(context)
            
            for i in range(len(sorted_objs) - 1):
                p1 = origin.copy()
                p1[axis_idx] = sorted_objs[i].matrix_world.translation[axis_idx]
                p2 = origin.copy()
                p2[axis_idx] = sorted_objs[i+1].matrix_world.translation[axis_idx]
                
                mid_pt = (p1 + p2) / 2.0
                mid_2d = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, mid_pt)
                
                if mid_2d:
                    dist = abs(p2[axis_idx] - p1[axis_idx])
                    display_dist = dist / multiplier if multiplier != 0 else dist
                    dist_str = f"{display_dist:.2f} {unit_sym}"
                    
                    blf.position(font_id, mid_2d.x - 20, mid_2d.y + 10, 0)
                    blf.size(font_id, 14)
                    blf.color(font_id, 0.0, 1.0, 1.0, 1.0) 
                    blf.enable(font_id, blf.SHADOW)
                    blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.8)
                    blf.shadow_offset(font_id, 1, -1)
                    blf.draw(font_id, dist_str)
                    blf.disable(font_id, blf.SHADOW)

    def cleanup(self, context):
        OBJECT_OT_super_quick_align._is_running = False
        try:
            if getattr(self, "draw_handle_3d", None):
                bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle_3d, 'WINDOW')
                self.draw_handle_3d = None
            if getattr(self, "draw_handle_2d", None):
                bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle_2d, 'WINDOW')
                self.draw_handle_2d = None
        except Exception:
            pass
        try:
            context.workspace.status_text_set(None)
        except Exception:
            pass
        context.area.tag_redraw()
