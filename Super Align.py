bl_info = {
    "name": "Super Quick Align Pro",
    "author": "Bạn và AI",
    "version": (2, 5, 0),
    "blender": (4, 0, 0), 
    "location": "View3D > Toolbar (Phím T) hoặc Right Click Context Menu",
    "description": "Tích hợp Toolbar | Absolute Snap | Align | Distribute | Live Undo",
    "warning": "",
    "doc_url": "",
    "category": "Object",
}

import bpy
import gpu
import blf
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, geometry
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

    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'
    
    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        self.draw_handle_3d = None
        self.draw_handle_2d = None
        self.mouse_pos = (0, 0)
        
        if not context.active_object and len(context.selected_objects) >= 1:
            context.view_layer.objects.active = context.selected_objects[0]

        if getattr(context, "active_object", None) is None:
            self.report({'WARNING'}, "LỖI: Bạn phải chọn ít nhất 1 vật thể!")
            return {'CANCELLED'}

        self.active_obj = context.active_object
        self.selected_objs = [obj for obj in context.selected_objects if obj != self.active_obj]
        
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
        
        self.is_ctrl_pressed = False 
        self.is_alt_pressed = False
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
        return sum([obj.location for obj in all_objs], Vector()) / len(all_objs)

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
                    
                target_objs[i].location -= (self.snap_normal * dist_to_move)
                
            bpy.ops.ed.undo_push(message="Copy & Stamp to Plane" if is_copy else "Absolute Snap to Plane")
        
        elif self.current_auto_mode == 'EDGE':
            for i, obj in enumerate(all_objs):
                bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                center_pt = sum(bbox_corners, Vector((0,0,0))) / 8.0
                vec_center_to_midpoint = self.snap_target - center_pt
                translation_vec = vec_center_to_midpoint.dot(self.snap_edge_dir) * self.snap_edge_dir
                target_objs[i].location += translation_vec
            bpy.ops.ed.undo_push(message="Copy & Slide to Edge" if is_copy else "Snap Objects to Edge")

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type == 'Z' and event.value == 'PRESS' and (event.ctrl or event.oskey):
            try:
                if event.shift:
                    bpy.ops.ed.redo()
                    self.report({'INFO'}, "Redo: Bước tiếp theo")
                else:
                    bpy.ops.ed.undo()
                    self.report({'INFO'}, "Undo: Đã lùi lại 1 bước")
            except Exception as e:
                pass
                
            try:
                self.active_obj = bpy.context.active_object
                if self.active_obj:
                    self.selected_objs = [obj for obj in bpy.context.selected_objects if obj != self.active_obj]
                else:
                    self.selected_objs = []
            except ReferenceError:
                pass
                
            return {'RUNNING_MODAL'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}
        
        if event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
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

        if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_ALT', 'RIGHT_ALT', 'LEFT_CTRL', 'RIGHT_CTRL'}:
            self.is_shift_pressed = event.shift
            self.is_alt_pressed = event.alt
            self.is_ctrl_pressed = event.ctrl
            
            if event.shift or event.alt:
                self.show_axes = True
                self.snap_target = None
                self.draw_highlight_verts.clear()
                self.hovered_axis, self.hovered_align_mode = self.get_hovered_axis(context)
            else:
                self.show_axes = False
                self.hovered_axis = None
                self.find_snap_target(context)
                
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            self.mouse_pos = (event.mouse_region_x, event.mouse_region_y)
            self.is_ctrl_pressed = event.ctrl 
            self.is_alt_pressed = event.alt
            self.is_shift_pressed = event.shift
            
            if event.shift or event.alt:
                self.show_axes = True
                self.snap_target = None
                self.draw_highlight_verts.clear()
                self.hovered_axis, self.hovered_align_mode = self.get_hovered_axis(context)
            else:
                self.show_axes = False
                self.hovered_axis = None
                self.find_snap_target(context) 

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self.cleanup(context)
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if event.shift:
                if self.hovered_axis is not None:
                    if len(self.selected_objs) < 1:
                        self.report({'WARNING'}, "Cần chọn ít nhất 2 vật thể để Align!")
                    else:
                        self.align_objects(self.hovered_axis)
                        bpy.ops.ed.undo_push(message=f"Align objects to {self.hovered_align_mode}")
                        
            elif event.alt:
                if self.hovered_axis is not None:
                    if len(self.selected_objs) < 2:
                        self.report({'WARNING'}, "Cần chọn ít nhất 3 vật thể để Distribute!")
                    else:
                        self.distribute_objects_evenly(self.hovered_axis)
                        self.distribute_axis = self.hovered_axis
                        self.is_typing = True 
                        self.input_distance = ""
                        bpy.ops.ed.undo_push(message="Distribute evenly")

            elif not event.shift and not event.alt:
                if self.snap_target is not None:
                    self.execute_snap(context, is_copy=event.ctrl)

        return {'RUNNING_MODAL'} 

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

    def align_objects(self, axis_index):
        all_objs = self.selected_objs + [self.active_obj]
        if self.hovered_align_mode == 'MIN':
            target_val = min([obj.location[axis_index] for obj in all_objs])
        elif self.hovered_align_mode == 'MAX':
            target_val = max([obj.location[axis_index] for obj in all_objs])
        else: 
            target_val = self.get_selection_center()[axis_index]
            
        for obj in all_objs:
            obj.location[axis_index] = target_val
        bpy.context.view_layer.update()

    def distribute_objects_evenly(self, axis_index):
        all_objs = self.selected_objs + [self.active_obj]
        all_objs.sort(key=lambda obj: obj.location[axis_index])
        min_val = all_objs[0].location[axis_index]
        max_val = all_objs[-1].location[axis_index]
        step = (max_val - min_val) / (len(all_objs) - 1)
        for i, obj in enumerate(all_objs):
            obj.location[axis_index] = min_val + (i * step)
        bpy.context.view_layer.update()

    def apply_exact_distance(self, context):
        try: dist_input = float(self.input_distance)
        except ValueError: return 
        
        multiplier = self.get_unit_multiplier(context)
        dist_internal = dist_input * multiplier
        
        axis_index = self.distribute_axis
        all_objs = self.selected_objs + [self.active_obj]
        all_objs.sort(key=lambda obj: obj.location[axis_index])
        start_val = all_objs[0].location[axis_index]
        
        for i, obj in enumerate(all_objs):
            obj.location[axis_index] = start_val + (i * dist_internal)
        bpy.context.view_layer.update()

    def get_hovered_axis(self, context):
        if not getattr(self, "active_obj", None): return None, 'CENTER'
        
        region = context.region
        rv3d = context.region_data
        origin_3d = self.get_selection_center()
        
        dynamic_len = self.get_dynamic_scale(context, origin_3d, 60.0)
        mouse_vec = Vector((self.mouse_pos[0], self.mouse_pos[1]))
        
        best_axis = None
        best_mode = 'CENTER'
        min_dist = 25.0 
        
        axes = [Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1))]
        for i, axis in enumerate(axes):
            start_3d = origin_3d - (axis * dynamic_len)
            end_3d = origin_3d + (axis * dynamic_len)
            
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
                    if proj < line_len * 0.3: best_mode = 'MIN'
                    elif proj > line_len * 0.7: best_mode = 'MAX'
                    else: best_mode = 'CENTER'
                        
        return best_axis, best_mode

    def draw_3d(self, context):
        try:
            if not getattr(self, "active_obj", None): return
            origin = self.get_selection_center() 
            shader = get_shader()
            if not shader: return
            
            if not self.show_axes and self.snap_target is not None:
                if self.current_auto_mode == 'FACE':
                    hl_color = (0.0, 1.0, 0.0, 1.0) if self.is_ctrl_pressed else (0.0, 1.0, 1.0, 1.0)
                else:
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

            if self.show_axes:
                dynamic_len = self.get_dynamic_scale(context, origin, 60.0)
                
                coords = [
                    origin - Vector((dynamic_len, 0, 0)), origin + Vector((dynamic_len, 0, 0)), 
                    origin - Vector((0, dynamic_len, 0)), origin + Vector((0, dynamic_len, 0)), 
                    origin - Vector((0, 0, dynamic_len)), origin + Vector((0, 0, dynamic_len))  
                ]
                base_colors = [(1.0, 0.2, 0.2), (0.2, 1.0, 0.2), (0.2, 0.5, 1.0)]
                colors = []
                for i in range(3):
                    alpha = 1.0 if self.hovered_axis == i else 0.3
                    colors.extend([(base_colors[i][0], base_colors[i][1], base_colors[i][2], alpha)] * 2)

                batch = batch_for_shader(shader, 'LINES', {"pos": coords, "color": colors})

                gpu.state.depth_test_set('NONE')
                gpu.state.blend_set('ALPHA') 
                try: gpu.state.line_width_set(4.0)
                except: pass 
                shader.bind()
                batch.draw(shader)
                
                if self.is_shift_pressed and self.hovered_axis is not None:
                    point_3d = origin
                    axis_vec = [Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1))][self.hovered_axis]
                    
                    if self.hovered_align_mode == 'MIN': point_3d = origin - (axis_vec * dynamic_len)
                    elif self.hovered_align_mode == 'MAX': point_3d = origin + (axis_vec * dynamic_len)
                        
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
        
        if self.is_typing:
            blf.position(font_id, 30, 110, 0)
            blf.size(font_id, 24)
            blf.color(font_id, 0.0, 1.0, 0.0, 1.0)
            unit_sym = self.get_unit_symbol(context)
            blf.draw(font_id, f"Khoảng cách Distribute: {self.input_distance} {unit_sym} (Nhấn Enter chốt)")
            
        blf.position(font_id, 30, 80, 0)
        blf.size(font_id, 26)
        
        if self.is_shift_pressed:
            blf.color(font_id, 1.0, 0.8, 0.0, 1.0) 
            blf.draw(font_id, "[CHẾ ĐỘ: ALIGN TRỤC ẢO]")
        elif self.is_alt_pressed:
            blf.color(font_id, 0.0, 0.8, 1.0, 1.0) 
            blf.draw(font_id, "[CHẾ ĐỘ: DISTRIBUTE (Giãn đều)]")
        else:
            blf.color(font_id, 0.0, 1.0, 0.8, 1.0) 
            blf.draw(font_id, "[CHẾ ĐỘ: SMART SNAP]")
            
        blf.position(font_id, 30, 50, 0)
        blf.size(font_id, 18)
        
        if self.is_shift_pressed:
            if self.hovered_axis is not None:
                m_str = "TÂM" if self.hovered_align_mode == 'CENTER' else ("MIN (-)" if self.hovered_align_mode == 'MIN' else "MAX (+)")
                blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
                blf.draw(font_id, f"Căn dồn về phía {m_str}")
            else:
                blf.color(font_id, 0.7, 0.7, 0.7, 1.0)
                blf.draw(font_id, "Rê chuột lên trục cần căn gióng...")
                
        elif self.is_alt_pressed:
            if self.hovered_axis is not None:
                blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
                blf.draw(font_id, "Click vào trục để chia đều khoảng cách!")
            else:
                blf.color(font_id, 0.7, 0.7, 0.7, 1.0)
                blf.draw(font_id, "Rê chuột lên trục cần giãn cách...")
                
        else: 
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

        blf.position(font_id, 30, 25, 0)
        blf.size(font_id, 14)
        blf.color(font_id, 0.8, 0.8, 0.8, 1.0)
        blf.draw(font_id, "Không giữ: Snap | [SHIFT] Align | [ALT] Distribute | [CTRL] Copy | [CTRL+Z] Undo")

    def cleanup(self, context):
        if self.draw_handle_3d:
            bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle_3d, 'WINDOW')
            self.draw_handle_3d = None
        if self.draw_handle_2d:
            bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle_2d, 'WINDOW')
            self.draw_handle_2d = None
        context.area.tag_redraw()

# --- 1. LỚP ĐĂNG KÝ TOOL VÀO THANH TOOLBAR (PHÍM T) ---
class VIEW3D_WST_super_align(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    
    bl_idname = "tool.super_quick_align"
    bl_label = "Super Align"
    bl_description = "Công cụ thông minh: Align, Distribute, và Snap"
    bl_icon = "ops.transform.translate" # Icon mũi tên di chuyển
    
    bl_widget = None
    
    # Gán thao tác chuột trái để kích hoạt lệnh Modal của chúng ta
    bl_keymap = (
        ("object.super_quick_align", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
    )

def menu_func(self, context):
    self.layout.separator()
    self.layout.operator_context = 'INVOKE_DEFAULT' 
    self.layout.operator(OBJECT_OT_super_quick_align.bl_idname, icon='ALIGN_CENTER')

# --- 2. CẬP NHẬT HÀM REGISTER/UNREGISTER ---
def register():
    bpy.utils.register_class(OBJECT_OT_super_quick_align)
    bpy.types.VIEW3D_MT_object_context_menu.append(menu_func)
    # Đăng ký Tool vào thanh bên trái
    bpy.utils.register_tool(VIEW3D_WST_super_align, separator=True)

def unregister():
    bpy.utils.unregister_class(OBJECT_OT_super_quick_align)
    bpy.types.VIEW3D_MT_object_context_menu.remove(menu_func)
    # Xóa Tool khỏi thanh bên trái
    bpy.utils.unregister_tool(VIEW3D_WST_super_align)

if __name__ == "__main__":
    register()