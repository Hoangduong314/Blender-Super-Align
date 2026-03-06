bl_info = {
    "name": "Super Quick Align Pro",
    "author": "Bạn và AI",
    "version": (3, 2, 0),
    "blender": (4, 0, 0), 
    "location": "View3D > Toolbar (Phím T)",
    "description": "Trục ảo tự co giãn theo vật thể | Thu hẹp vùng Hover 2 đầu mút",
    "warning": "",
    "doc_url": "",
    "category": "Object",
}

import bpy
import gpu
import blf
import os
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, geometry
from bpy_extras import view3d_utils
import bpy.utils.previews

custom_icons = None
addon_keymaps = []

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

        self.draw_handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_3d, (context,), 'WINDOW', 'POST_VIEW'
        )
        self.draw_handle_2d = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_2d, (context,), 'WINDOW', 'POST_PIXEL'
        )
        
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

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
            'MILLIMETERS': 'mm', 'MICROMETERS': 'µm', 'MILES': 'mi', 
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

    def execute_snap(self, context, is_copy):
        all_objs = self.selected_objs + [self.active_obj]
        target_objs = []
        if is_copy:
            for obj in all_objs:
                new_obj = obj.copy() 
                if obj.data: new_obj.data = obj.data.copy() 
                context.collection.objects.link(new_obj)
                target_objs.append(new_obj)
        else:
            target_objs = all_objs 
        
        if self.current_auto_mode == 'FACE':
            for i, obj in enumerate(all_objs): 
                bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                distances = [(corner - self.snap_target).dot(self.snap_normal) for corner in bbox_corners]
                center_pt = sum(bbox_corners, Vector()) / 8.0
                center_dist = (center_pt - self.snap_target).dot(self.snap_normal)
                
                if center_dist >= 0: dist_to_move = min(distances)
                else: dist_to_move = max(distances)
                target_objs[i].matrix_world.translation -= (self.snap_normal * dist_to_move)
            bpy.ops.ed.undo_push(message="Copy & Stamp to Plane" if is_copy else "Absolute Snap to Plane")
        
        elif self.current_auto_mode == 'EDGE':
            for i, obj in enumerate(all_objs):
                bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                center_pt = sum(bbox_corners, Vector((0,0,0))) / 8.0
                vec_center_to_midpoint = self.snap_target - center_pt
                translation_vec = vec_center_to_midpoint.dot(self.snap_edge_dir) * self.snap_edge_dir
                target_objs[i].matrix_world.translation += translation_vec
            bpy.ops.ed.undo_push(message="Copy & Slide to Edge" if is_copy else "Snap Objects to Edge")

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
                        self.report({'INFO'}, "Redo: Bước tiếp theo")
                    else:
                        bpy.ops.ed.undo()
                        self.report({'INFO'}, "Undo: Đã lùi lại 1 bước")
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

            if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL'}:
                self.is_shift_pressed = event.shift
                self.is_ctrl_pressed = event.ctrl
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
                    return {'RUNNING_MODAL'}
                elif event.type == 'BACK_SPACE':
                    self.input_distance = self.input_distance[:-1]
                    self.apply_exact_distance(context)
                    return {'RUNNING_MODAL'}
                elif event.unicode.isdigit() or event.unicode in {'.', '-'}:
                    self.input_distance += event.unicode
                    self.apply_exact_distance(context)
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
                        self.execute_snap(context, is_copy=event.ctrl) 
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

    # --- THUẬT TOÁN MỚI: TÍNH TOÁN CHIỀU DÀI TRỤC THEO BOUNDING VÀ VÙNG HOVER CỐ ĐỊNH ---
    def get_hovered_axis(self, context):
        if not getattr(self, "active_obj", None): return None, 'CENTER'
        
        region = context.region
        rv3d = context.region_data
        origin_3d = self.get_selection_center()
        
        # Thêm lề (margin) 40 pixels không gian màn hình vào đuôi trục ảo
        margin_3d = self.get_dynamic_scale(context, origin_3d, 40.0) 
        mouse_vec = Vector((self.mouse_pos[0], self.mouse_pos[1]))
        
        best_axis = None
        best_mode = 'CENTER'
        min_dist = 25.0 
        
        axes = [Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1))]
        all_objs = self.selected_objs + [self.active_obj]
        
        for i, axis in enumerate(axes):
            # Tính giới hạn toạ độ theo trục
            min_val = min(obj.matrix_world.translation[i] for obj in all_objs)
            max_val = max(obj.matrix_world.translation[i] for obj in all_objs)
            
            # Đảm bảo trục không bị biến mất nếu các vật thể trùng nhau
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
                    
                    # Giới hạn độ lớn vùng Hover cố định 30 pixels ở 2 mút
                    hover_zone_px = 30.0 
                    
                    # Nếu trục trên màn hình quá ngắn, chia tỷ lệ 15% / 70% / 15%
                    if line_len < hover_zone_px * 2.5:
                        if proj < line_len * 0.15: best_mode = 'MIN'
                        elif proj > line_len * 0.85: best_mode = 'MAX'
                        else: best_mode = 'CENTER'
                    # Nếu trục đủ dài, khóa chết 30 pixels ở mép
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
                    
                    if self.current_auto_mode == 'EDGE':
                        s = self.get_dynamic_scale(context, self.snap_target, 15.0) 
                        cross_verts = [
                            self.snap_target - Vector((s,0,0)), self.snap_target + Vector((s,0,0)),
                            self.snap_target - Vector((0,s,0)), self.snap_target + Vector((0,s,0)),
                            self.snap_target - Vector((0,0,s)), self.snap_target + Vector((0,0,s))
                        ]
                        cross_colors = [(1.0, 1.0, 0.0, 1.0)] * 6
                        batch_cross = batch_for_shader(shader, 'LINES', {"pos": cross_verts, "color": cross_colors})
                        batch_cross.draw(shader)
                        
                    gpu.state.blend_set('NONE')
                    gpu.state.depth_test_set('LESS_EQUAL')
                return

            if self.show_axes and not self.is_shift_pressed:
                margin_3d = self.get_dynamic_scale(context, origin, 40.0)
                all_objs = self.selected_objs + [self.active_obj]
                
                coords = []
                base_colors = [(1.0, 0.2, 0.2), (0.2, 1.0, 0.2), (0.2, 0.5, 1.0)]
                colors = []
                
                # Vẽ lại các đoạn trục co giãn theo toạ độ
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
                
                # --- VẼ DIMENSION LINES ---
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

                # --- VẼ NGÔI SAO ALIGN Ở MIN/MAX TƯƠNG ỨNG MỚI ---
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
                        
                    s = self.get_dynamic_scale(context, point_3d, 12.0) 
                    pt_verts = [
                        point_3d - Vector((s,0,0)), point_3d + Vector((s,0,0)),
                        point_3d - Vector((0,s,0)), point_3d + Vector((0,s,0)),
                        point_3d - Vector((0,0,s)), point_3d + Vector((0,0,s))
                    ]
                    pt_colors = [(1.0, 1.0, 0.0, 1.0)] * 6 
                    batch_pt = batch_for_shader(shader, 'LINES', {"pos": pt_verts, "color": pt_colors})
                    try: gpu.state.line_width_set(8.0) 
                    except: pass
                    batch_pt.draw(shader)

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

        if self.is_typing:
            blf.position(font_id, 30, 110, 0)
            blf.size(font_id, 24)
            blf.color(font_id, 0.0, 1.0, 0.0, 1.0)
            unit_sym = self.get_unit_symbol(context)
            blf.draw(font_id, f"Giãn cách: {self.input_distance} {unit_sym} (Nhấn Enter để chốt)")
            
        blf.position(font_id, 30, 80, 0)
        blf.size(font_id, 26)
        
        total_selected = len(context.selected_objects)
        
        if self.is_shift_pressed:
            blf.color(font_id, 1.0, 1.0, 1.0, 1.0) 
            blf.draw(font_id, "[CHẾ ĐỘ: CHỌN VẬT THỂ]")
        elif self.is_tab_pressed:
            blf.color(font_id, 1.0, 0.5, 0.0, 1.0) 
            blf.draw(font_id, "[ÉP CHẾ ĐỘ: SMART SNAP]")
        elif total_selected <= 1:
            blf.color(font_id, 0.0, 1.0, 0.8, 1.0) 
            blf.draw(font_id, "[CHẾ ĐỘ: SMART SNAP (1 Vật thể)]")
        else:
            blf.color(font_id, 0.0, 0.8, 1.0, 1.0) 
            blf.draw(font_id, f"[CHẾ ĐỘ: DISTRIBUTE ({total_selected} Vật thể)]")
            
        blf.position(font_id, 30, 50, 0)
        blf.size(font_id, 18)
        
        if self.is_shift_pressed:
            blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
            blf.draw(font_id, "Click vào các vật thể khác để chọn thêm hoặc loại bỏ...")
        else:
            if self.tool_mode == 'SNAP':
                if self.current_auto_mode == 'FACE':
                    blf.color(font_id, 0.0, 1.0, 0.0, 1.0) if self.is_ctrl_pressed else blf.color(font_id, 0.0, 1.0, 1.0, 1.0)
                    txt = "[COPY] Đóng dấu vật thể vào mặt" if self.is_ctrl_pressed else "Bắn vật thể chạm mặt (Tuyệt đối 2 chiều)"
                    blf.draw(font_id, txt)
                elif self.current_auto_mode == 'EDGE':
                    blf.color(font_id, 0.0, 1.0, 0.0, 1.0) if self.is_ctrl_pressed else blf.color(font_id, 1.0, 0.5, 0.0, 1.0)
                    txt = "[COPY] Trượt copy dọc theo viền" if self.is_ctrl_pressed else "Trượt vật thể song song theo viền"
                    blf.draw(font_id, txt)
                else:
                    blf.color(font_id, 0.5, 0.5, 0.5, 1.0)
                    blf.draw(font_id, "Rê chuột lên bề mặt hoặc mép cạnh để bắt điểm...")
                        
            elif self.tool_mode == 'DISTRIBUTE':
                if self.hovered_axis is not None:
                    if self.hovered_align_mode in {'MIN', 'MAX'}:
                        m_str = "MIN (-)" if self.hovered_align_mode == 'MIN' else "MAX (+)"
                        blf.color(font_id, 1.0, 0.8, 0.0, 1.0)
                        blf.draw(font_id, f"Click để Dồn toàn bộ {total_selected} vật thể về {m_str}")
                    else:
                        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
                        blf.draw(font_id, "Click giữa trục để Giãn đều. Nhập '0' để Gom vào tâm!")
                else:
                    blf.color(font_id, 0.7, 0.7, 0.7, 1.0)
                    blf.draw(font_id, "Rê chuột vào Trục: Khúc giữa -> Giãn | Hai đầu (30px) -> Dồn (Align)")

        blf.position(font_id, 30, 25, 0)
        blf.size(font_id, 14)
        blf.color(font_id, 0.8, 0.8, 0.8, 1.0)
        
        if total_selected > 1 and not self.is_tab_pressed:
            blf.draw(font_id, "Tự động phân tích nhiều vật thể | [GIỮ TAB] Ép xài Snap | [SHIFT] Chọn thêm")
        else:
            blf.draw(font_id, "Chỉ 1 vật thể: Snap | [CTRL] Copy Snap | [SHIFT] Click Chọn thêm vật thể")

    def cleanup(self, context):
        OBJECT_OT_super_quick_align._is_running = False
        try:
            if getattr(self, "draw_handle_3d", None):
                bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle_3d, 'WINDOW')
                self.draw_handle_3d = None
            if getattr(self, "draw_handle_2d", None):
                bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle_2d, 'WINDOW')
                self.draw_handle_2d = None
        except Exception: pass
        context.area.tag_redraw()

def menu_func(self, context):
    self.layout.separator()
    self.layout.operator_context = 'INVOKE_DEFAULT' 
    icon_id = custom_icons["custom_icon"].icon_id if custom_icons and "custom_icon" in custom_icons else 0
    if icon_id:
        self.layout.operator(OBJECT_OT_super_quick_align.bl_idname, text="Super Align Pro", icon_value=icon_id)
    else:
        self.layout.operator(OBJECT_OT_super_quick_align.bl_idname, text="Super Align Pro", icon='ALIGN_CENTER')

def register():
    global custom_icons
    custom_icons = bpy.utils.previews.new()
    import os
    
    # Tìm file icon an toàn dựa vào context của Text Editor
    try:
        current_dir = os.path.dirname(__file__)
    except NameError:
        current_dir = r"g:\My Drive\Libraries\Blender\Blender-Super-Align"
        for text in bpy.data.texts:
            if text.name == "Super Align.py" and text.filepath:
                current_dir = os.path.dirname(text.filepath)
                break
                
    icon_path = os.path.join(current_dir, "icon.png")
    if os.path.exists(icon_path):
        custom_icons.load("custom_icon", icon_path, 'IMAGE')

    bpy.utils.register_class(OBJECT_OT_super_quick_align)
    bpy.types.VIEW3D_MT_object_context_menu.append(menu_func)
    
    # Đăng ký phím tắt Ctrl + Shift + A cho Object Mode
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Object Mode', space_type='EMPTY')
        kmi = km.keymap_items.new(OBJECT_OT_super_quick_align.bl_idname, 'A', 'PRESS', ctrl=True, shift=True)
        addon_keymaps.append((km, kmi))

def unregister():
    global custom_icons
    if custom_icons is not None:
        bpy.utils.previews.remove(custom_icons)
        custom_icons = None

    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    bpy.utils.unregister_class(OBJECT_OT_super_quick_align)
    bpy.types.VIEW3D_MT_object_context_menu.remove(menu_func)

if __name__ == "__main__":
    register()