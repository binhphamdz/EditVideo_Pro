import os
import random
import subprocess
import csv
import json
import shutil
import threading # [MỚI] IMPORT THƯ VIỆN KHÓA
import time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from shopee_export import export_rendered_video_to_shopee_files, is_shopee_out_of_stock_project
from paths import BASE_PATH, resource_path

# =======================================================
# [MỚI] TẠO Ổ KHÓA TOÀN CỤC BẢO VỆ FILE EXCEL (CSV)
# =======================================================
csv_write_lock = threading.Lock()

SAFE_XFADE_TRANSITIONS = {
    'fade', 'slideleft', 'slideright', 'slideup', 'slidedown',
    'wipeleft', 'wiperight', 'hlslice', 'zoomin'
}


def _load_cover_font(custom_font, font_size):
    font_candidates = []
    if custom_font and os.path.exists(custom_font):
        font_candidates.append(custom_font)
    font_candidates.extend(["arial.ttf", "DejaVuSans-Bold.ttf"])

    for font_path in font_candidates:
        try:
            return ImageFont.truetype(font_path, font_size)
        except OSError:
            continue

    return ImageFont.load_default()


def _iter_cover_line_layouts(words, line_count):
    total_words = len(words)
    if line_count <= 1 or total_words <= 1:
        yield [" ".join(words)]
        return

    def _walk(start_index, lines_left, current_lines):
        remaining_words = total_words - start_index
        if lines_left == 1:
            current_lines.append(" ".join(words[start_index:]))
            yield list(current_lines)
            current_lines.pop()
            return

        max_chunk = remaining_words - (lines_left - 1)
        for take_count in range(1, max_chunk + 1):
            current_lines.append(" ".join(words[start_index:start_index + take_count]))
            yield from _walk(start_index + take_count, lines_left - 1, current_lines)
            current_lines.pop()

    yield from _walk(0, min(line_count, total_words), [])


def _fit_cover_layout(draw, layout_text, img_w, img_h, custom_font):
    max_text_width = img_w * 0.88
    max_text_height = img_h * 0.42
    low = 24
    high = max(low, int(img_h * 0.16))
    best_fit = None

    while low <= high:
        font_size = (low + high) // 2
        font = _load_cover_font(custom_font, font_size)
        stroke_w = max(2, int(font_size * 0.11))
        line_spacing = max(6, int(font_size * 0.08))
        bbox = draw.multiline_textbbox(
            (0, 0),
            layout_text,
            font=font,
            align="center",
            spacing=line_spacing,
            stroke_width=stroke_w,
        )
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        if text_width <= max_text_width and text_height <= max_text_height:
            best_fit = (font_size, font, stroke_w, line_spacing, text_width, text_height)
            low = font_size + 1
        else:
            high = font_size - 1

    return best_fit


def _choose_cover_layout(draw, source_text, img_w, img_h, custom_font):
    words = source_text.split()
    if not words:
        font = _load_cover_font(custom_font, 72)
        return source_text, font, 8, 8

    if len(words) <= 2:
        max_lines = 1
    elif len(words) <= 6:
        max_lines = 2
    elif len(words) <= 10:
        max_lines = 3
    else:
        max_lines = 4

    best_layout = None
    seen_layouts = set()

    for line_count in range(1, min(max_lines, len(words)) + 1):
        for lines in _iter_cover_line_layouts(words, line_count):
            layout_text = "\n".join(lines)
            if layout_text in seen_layouts:
                continue
            seen_layouts.add(layout_text)

            fit = _fit_cover_layout(draw, layout_text, img_w, img_h, custom_font)
            if not fit:
                continue

            font_size, font, stroke_w, line_spacing, text_width, _ = fit
            line_lengths = [len(line) for line in lines if line.strip()]
            balance_score = max(line_lengths) - min(line_lengths) if len(line_lengths) > 1 else 0
            candidate = (
                font_size,
                -balance_score,
                -len(lines),
                -(text_width / max(img_w, 1)),
                layout_text,
                font,
                stroke_w,
                line_spacing,
            )

            if best_layout is None or candidate > best_layout:
                best_layout = candidate

    if best_layout is not None:
        return best_layout[4], best_layout[5], best_layout[6], best_layout[7]

    fallback_font = _load_cover_font(custom_font, 24)
    return source_text, fallback_font, 3, 6


def _resolve_media_asset(*file_names):
    candidates = []
    for file_name in file_names:
        candidates.extend([
            resource_path(file_name),
            os.path.join(BASE_PATH, file_name),
            os.path.join(os.getcwd(), file_name),
        ])

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate

    return ""

def get_vid_info(file_path):
    """Lấy độ dài và kiểm tra xem video có chứa rãnh Audio hay không"""
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', file_path]
        out = subprocess.check_output(cmd, creationflags=0x08000000 if os.name == 'nt' else 0)
        data = json.loads(out)
        dur = float(data.get('format', {}).get('duration', 5.0))
        has_audio = any(s.get('codec_type') == 'audio' for s in data.get('streams', []))
        return dur, has_audio
    except:
        return 5.0, False

def render_faceless_video(voice_name, voice_path, timeline, proj_dir, proj_name, config, out_file, out_dir, excel_log_file, log_cb, broll_data):
    speed_val = config.get("video_speed", 1.0)
    auto_speed_max = config.get("auto_speed_max", 1.4)
    bright_val = config.get("video_bright", 1.0)
    use_trans = config.get("use_trans", True)
    use_sfx = config.get("use_sfx", True)
    broll_vol = config.get("broll_vol", 30) / 100.0 
    custom_font = config.get("font_path", "")
    whoosh_sfx_path = _resolve_media_asset("whoosh.mp3", "whoosh.MP3")
    
    trans_dur = config.get("trans_duration", 0.5)  # [MỚI] Lấy từ config, mặc định 0.5s
    log_cb(f"[{voice_name}] Đang phân tích Timeline & Gắn hiệu ứng (FFmpeg Đa nhân)...")
    
    voice_dur, _ = get_vid_info(voice_path)
    
    all_brolls = [f for f in os.listdir(os.path.join(proj_dir, "Broll")) if f.lower().endswith(('.mp4', '.mov'))]
    if not all_brolls: raise Exception("Không tìm thấy video Broll nào trong project!")

    # =======================================================
    # [BÙA CHỐNG KẸT FFMPEG 1] - XỬ LÝ TIMELINE RỖNG
    # =======================================================
    if not timeline:
        log_cb(f"[{voice_name}] ⚠️ Timeline AI rỗng! Tự động bật chế độ lấp đầy toàn dải...")
        timeline = [{"video_file": "", "start": 0, "end": voice_dur}]

    global_used_vids = set()
    vid_offsets = {} 
    last_vid_name = None
    selected_clips = []
    current_time = 0.0

    # =======================================================
    # BƯỚC 1: TÍNH TOÁN BROLL CẦN THIẾT
    # =======================================================
    for i, row in enumerate(timeline):
        end_time = float(row.get("end", 0))
        if i == len(timeline) - 1: end_time = max(end_time, voice_dur)
        req_duration = end_time - current_time
        if req_duration <= 0: continue

        actual_req_dur = max(req_duration, 1.0) 
        if i == 1 and use_trans: actual_req_dur += trans_dur

        current_dur = 0.0
        fail_safe = 0
        scene_vids = []
        
        # Lấy MẢNG video do AI Đạo Diễn xếp sẵn
        ai_chosen_videos = row.get("video_files", [])
        if isinstance(ai_chosen_videos, str): ai_chosen_videos = [ai_chosen_videos] # Bọc lót nếu json cũ
        
        # Biến mảng này thành một hàng đợi (Queue), kiểm tra xem file có thật trên ổ cứng không
        ai_queue = [v for v in ai_chosen_videos if os.path.exists(os.path.join(proj_dir, "Broll", v))]

        while current_dur < actual_req_dur and fail_safe < 20:
            
            # ƯU TIÊN 1: Rút video từ kịch bản của AI ra dùng trước
            if ai_queue:
                v_n = ai_queue.pop(0)
            else:
                # ƯU TIÊN 2: Nếu AI xếp kịch bản vẫn bị hụt giây, Cực chẳng đã mới phải Random lấp vào
                available = [f for f in all_brolls if f not in global_used_vids]
                if not available: 
                    global_used_vids.clear()
                    available = all_brolls
                if len(available) > 1 and last_vid_name in available: available.remove(last_vid_name)
                v_n = random.choice(available)
            
            v_path = os.path.join(proj_dir, "Broll", v_n)
            dur, has_audio = get_vid_info(v_path)
            
            start_t = vid_offsets.get(v_n, 0.0)
            avail_dur = dur - start_t
            
            if avail_dur < 1.0:
                start_t = 0.0
                avail_dur = dur

            rem = actual_req_dur - current_dur

            if avail_dur >= rem:
                spd = avail_dur / rem
                if spd > auto_speed_max:
                    spd = auto_speed_max
                    consume_dur = rem * auto_speed_max
                else:
                    consume_dur = avail_dur
                
                scene_vids.append({'path': v_path, 'name': v_n, 'start_t': start_t, 'trim': consume_dur, 'speed': spd, 'has_audio': has_audio})
                current_dur += rem
                vid_offsets[v_n] = start_t + consume_dur
                
            else:
                needed_speed = avail_dur / rem
                if needed_speed >= 0.8:
                    scene_vids.append({'path': v_path, 'name': v_n, 'start_t': start_t, 'trim': avail_dur, 'speed': needed_speed, 'has_audio': has_audio})
                    current_dur += rem
                else:
                    scene_vids.append({'path': v_path, 'name': v_n, 'start_t': start_t, 'trim': avail_dur, 'speed': 1.0, 'has_audio': has_audio})
                    current_dur += avail_dur
                    
                vid_offsets[v_n] = start_t + avail_dur

            global_used_vids.add(v_n)
            last_vid_name = v_n
            fail_safe += 1

        if scene_vids:
            selected_clips.append({'vids': scene_vids, 'dur': actual_req_dur})
        current_time = end_time

    # =======================================================
    # [BÙA CHỐNG KẸT FFMPEG 2] - KIỂM TRA TỔNG QUAN
    # =======================================================
    if not selected_clips:
        raise Exception("❌ File Voice quá ngắn hoặc thuật toán không gắp được cảnh nào. Đã tự động hủy để bảo vệ FFmpeg!")

    # =======================================================
    # BƯỚC 2: VIẾT KỊCH BẢN FFMPEG (HÌNH ẢNH + TRỘN ÂM THANH)
    # =======================================================
    log_cb(f"[{voice_name}] Đang căn chỉnh ma trận Audio & Hình ảnh...")
    inputs = []
    v_filters = []
    vid_input_idx = 0
    pre_labels = []
    broll_audio_labels = []
    
    abs_time = 0.0
    next_abs_time = 0.0

    for i, scene in enumerate(selected_clips):
        scene_input_vids = []
        
        if i == 0:
            abs_time = 0.0
            next_abs_time = scene['dur']
        elif i == 1 and use_trans:
            abs_time = selected_clips[0]['dur'] - trans_dur
            next_abs_time = abs_time + scene['dur']
        else:
            abs_time = next_abs_time
            next_abs_time = abs_time + scene['dur']

        clip_time = abs_time

        for j, clip in enumerate(scene['vids']):
            inputs.extend(['-i', clip['path']])
            
            end_t = clip['start_t'] + clip['trim']
            pts_mod = 1.0 / (clip['speed'] * speed_val)
            
            flt_v = (
                f"[{vid_input_idx}:v]trim={clip['start_t']:.3f}:{end_t:.3f},setpts={pts_mod}*(PTS-STARTPTS),"
                f"lutyuv=y=val*{bright_val},"
                f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                f"fps=30,format=yuv420p,setsar=1,eq=contrast=1.0[v_tmp{vid_input_idx}]"
            )
            v_filters.append(flt_v)
            scene_input_vids.append(f"[v_tmp{vid_input_idx}]")
            
            keep_audio = broll_data.get(clip['name'], {}).get('keep_audio', False)
            if keep_audio and clip['has_audio'] and broll_vol > 0:
                speed_factor = clip['speed'] * speed_val
                delay_ms = int(clip_time * 1000)
                atempo_str = f"atempo={speed_factor}," if speed_factor != 1.0 else ""
                
                flt_a = (
                    f"[{vid_input_idx}:a]atrim={clip['start_t']:.3f}:{end_t:.3f},asetpts=PTS-STARTPTS,"
                    f"{atempo_str}aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                    f"volume={broll_vol},adelay={delay_ms}|{delay_ms}[baud_{vid_input_idx}]"
                )
                v_filters.append(flt_a)
                broll_audio_labels.append(f"[baud_{vid_input_idx}]")

            clip_time += clip['trim'] * pts_mod
            vid_input_idx += 1

        # =======================================================
        # [BÙA CHỐNG KẸT FFMPEG 3] - XỬ LÝ CONCAT SCENE
        # =======================================================
        if len(scene_input_vids) > 1:
            raw_scene_label = f"[scenev_raw{i}]"
            scene_label = f"[scenev{i}]"
            concat_sc_flt = "".join(scene_input_vids) + f"concat=n={len(scene_input_vids)}:v=1:a=0{raw_scene_label}"
            v_filters.append(concat_sc_flt)
            v_filters.append(f"{raw_scene_label}settb=AVTB,setpts=PTS-STARTPTS,fps=30{scene_label}")
            pre_labels.append(scene_label)
        elif len(scene_input_vids) == 1:
            scene_label = f"[scenev{i}]"
            v_filters.append(f"{scene_input_vids[0]}settb=AVTB,setpts=PTS-STARTPTS,fps=30{scene_label}")
            pre_labels.append(scene_label)

    inputs.extend(['-i', voice_path])
    voice_idx = vid_input_idx 
    chosen_trans = None
    flt_fade = None
    xfade_fallback_flt = None

    # =======================================================
    # [BÙA CHỐNG KẸT FFMPEG 4] - XỬ LÝ CONCAT FINAL (Vào Lò)
    # =======================================================
    if len(pre_labels) > 1 and use_trans:
        sc_dur = selected_clips[0]['dur']
        fade_offset = sc_dur - trans_dur
        label_fade = "[vfade0]"
        
        # [MỚI] Ánh xạ UI transitions sang FFmpeg transitions
        trans_mapping = {
            "fade": "fade",
            "slide_left": "slideleft",
            "slide_right": "slideright",
            "slide_up": "slideup",
            "slide_down": "slidedown",
            "wipe_left": "wipeleft",
            "wipe_right": "wiperight",
            "hlslice": "hlslice",
            "vsplit": "vsplit",
            "zoom_in": "zoomin",
            "zoom_out": "zoomout",
            "diagonal": "diagonal",
            "cross_fade": "fade",
        }
        
        # Lấy transitions từ config
        selected_trans_keys = config.get("selected_transitions", ["fade"])
        available_trans = [
            trans_mapping[t]
            for t in selected_trans_keys
            if t in trans_mapping and trans_mapping[t] in SAFE_XFADE_TRANSITIONS
        ]
        
        if not available_trans:
            available_trans = ['fade']
        
        chosen_trans = random.choice(available_trans)
        if chosen_trans not in SAFE_XFADE_TRANSITIONS:
            log_cb(f"[{voice_name}] ⚠️ Hiệu ứng '{chosen_trans}' chưa tương thích FFmpeg hiện tại. Tự đổi sang fade để tránh lỗi render.")
            chosen_trans = 'fade'
        
        flt_fade = f"{pre_labels[0]}{pre_labels[1]}xfade=transition={chosen_trans}:duration={trans_dur}:offset={fade_offset},settb=AVTB,setpts=PTS-STARTPTS{label_fade}"
        xfade_fallback_flt = f"{pre_labels[0]}{pre_labels[1]}concat=n=2:v=1:a=0,settb=AVTB,setpts=PTS-STARTPTS{label_fade}"
        v_filters.append(flt_fade)
        
        concat_inputs = [label_fade] + pre_labels[2:]
        if len(concat_inputs) > 1:
            v_filters.append(f"{''.join(concat_inputs)}concat=n={len(concat_inputs)}:v=1:a=0,settb=AVTB,setpts=PTS-STARTPTS[outv]")
            outv_map = "[outv]"
        else:
            outv_map = label_fade
    elif len(pre_labels) > 1:
        v_filters.append(f"{''.join(pre_labels)}concat=n={len(pre_labels)}:v=1:a=0,settb=AVTB,setpts=PTS-STARTPTS[outv]")
        outv_map = "[outv]"
        fade_offset = 0
    elif len(pre_labels) == 1:
        outv_map = pre_labels[0]
        fade_offset = 0
    else:
        raise Exception("❌ Cảnh báo FFmpeg: Không có khung hình nào để render!")

    v_filters.append(f"[{voice_idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[norm_voice]")
    mix_audio_inputs = ["[norm_voice]"] 
    
    if use_trans and use_sfx and os.path.exists(whoosh_sfx_path) and fade_offset > 0:
        inputs.extend(['-i', whoosh_sfx_path])
        sfx_idx = voice_idx + 1 
        
        v_filters.append(
            f"[{sfx_idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"adelay={int(fade_offset * 1000)}|{int(fade_offset * 1000)}[sfx0]"
        )
        mix_audio_inputs.append("[sfx0]")

    mix_audio_inputs.extend(broll_audio_labels)

    num_mix = len(mix_audio_inputs)
    if num_mix > 1:
        mix_str = "".join(mix_audio_inputs)
        mix_flt = f"{mix_str}amix=inputs={num_mix}:duration=first:dropout_transition=0:normalize=0[outa]"
        v_filters.append(mix_flt)
        a_mix_final_map = "[outa]"
    else:
        a_mix_final_map = mix_audio_inputs[0]

    filter_complex = ";\n".join(v_filters)
    filter_script_path = os.path.join(out_dir, f"filter_{os.path.splitext(voice_name)[0]}.txt")
    with open(filter_script_path, 'w', encoding='utf-8') as f: f.write(filter_complex)

    creation_flags = 0x08000000 if os.name == 'nt' else 0
    temp_main_mp4 = os.path.join(out_dir, f"temp_main_{os.path.splitext(voice_name)[0]}.mp4")

    log_cb(f"[{voice_name}] Đang xuất xưởng bằng NVENC siêu tốc...")
    ffmpeg_cmd = [
        'ffmpeg', '-y'
    ] + inputs + [
        '-filter_complex_script', filter_script_path,
        '-map', outv_map,
        '-map', a_mix_final_map,
        '-c:v', 'h264_nvenc', '-preset', 'p1', '-b:v', '8000k',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest',
        temp_main_mp4
    ]

    process = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=creation_flags)
    if process.returncode != 0 and chosen_trans and ("Not yet implemented in FFmpeg" in process.stderr or "Error applying option 'transition'" in process.stderr):
        log_cb(f"[{voice_name}] ⚠️ FFmpeg không hỗ trợ hiệu ứng '{chosen_trans}'. Tự render lại bằng fade...")
        fallback_filter_complex = filter_complex.replace(f"transition={chosen_trans}", "transition=fade", 1)
        with open(filter_script_path, 'w', encoding='utf-8') as f:
            f.write(fallback_filter_complex)
        process = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=creation_flags)
    if process.returncode != 0 and flt_fade and xfade_fallback_flt and ("Parsed_xfade" in process.stderr or "do not match" in process.stderr or "Failed to configure output pad" in process.stderr):
        log_cb(f"[{voice_name}] ⚠️ Xfade bị lệch timebase. Tự render lại không dùng transition để tránh hỏng video...")
        fallback_filter_complex = filter_complex.replace(flt_fade, xfade_fallback_flt, 1)
        with open(filter_script_path, 'w', encoding='utf-8') as f:
            f.write(fallback_filter_complex)
        process = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=creation_flags)

    if process.returncode != 0: raise Exception(f"Lỗi FFmpeg Render Lõi: {process.stderr[-1500:]}")

    safe_stem = os.path.splitext(voice_name)[0]
    temp_token = f"{safe_stem}_{int(time.time() * 1000)}_{threading.get_ident()}"
    temp_frame_jpg = os.path.join(out_dir, f"temp_frame_{temp_token}.jpg")
    temp_cover_png = os.path.join(out_dir, f"temp_cover_{temp_token}.png")

    log_cb(f"[{voice_name}] Đang bốc ngẫu nhiên 1 frame làm ảnh bìa...")
    extract_points = []
    if voice_dur > 0:
        safe_max_time = max(0.0, voice_dur - 0.3)
        if safe_max_time <= 0.0:
            extract_points = [0.0]
        else:
            extract_points = sorted({
                round(min(max(0.0, random.uniform(0.0, safe_max_time)), safe_max_time), 2),
                round(min(0.1, safe_max_time), 2),
                round(min(max(0.0, voice_dur * 0.25), safe_max_time), 2),
                round(min(max(0.0, voice_dur * 0.5), safe_max_time), 2),
            })
    else:
        extract_points = [0.0]

    frame_ready = False
    frame_error = ""
    for point in extract_points:
        frame_result = subprocess.run(
            ['ffmpeg', '-y', '-ss', f"{point:.2f}", '-i', temp_main_mp4, '-frames:v', '1', temp_frame_jpg],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            creationflags=creation_flags,
        )
        if frame_result.returncode == 0 and os.path.exists(temp_frame_jpg) and os.path.getsize(temp_frame_jpg) > 0:
            frame_ready = True
            break
        frame_error = (frame_result.stderr or frame_result.stdout or "Không rõ lỗi")[-400:]

    final_video_ready = False
    if frame_ready:
        try:
            with Image.open(temp_frame_jpg).convert("RGBA") as img:
                draw = ImageDraw.Draw(img)
                img_w, img_h = img.size
                clean_proj_name = " ".join(proj_name.replace("_", " ").split()).upper()
                display_text, font, stroke_w, line_spacing = _choose_cover_layout(
                    draw,
                    clean_proj_name,
                    img_w,
                    img_h,
                    custom_font,
                )
                draw.multiline_text(
                    (img_w / 2, img_h / 2),
                    display_text,
                    font=font,
                    fill="white",
                    align="center",
                    anchor="mm",
                    spacing=line_spacing,
                    stroke_width=stroke_w,
                    stroke_fill="black",
                )
                img.convert("RGB").save(temp_cover_png)

            ffmpeg_concat_cmd = [
                "ffmpeg", "-y", "-loop", "1", "-t", "0.1", "-i", temp_cover_png, "-i", temp_main_mp4,
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "1:a",
                "-c:v", "h264_nvenc", "-preset", "p1", "-b:v", "8000k", "-c:a", "copy", out_file
            ]
            concat_result = subprocess.run(ffmpeg_concat_cmd, capture_output=True, text=True, errors='ignore', creationflags=creation_flags)
            final_video_ready = concat_result.returncode == 0 and os.path.exists(out_file) and os.path.getsize(out_file) > 0

            if not final_video_ready:
                frame_error = (concat_result.stderr or concat_result.stdout or "Ghép ảnh bìa thất bại")[-400:]
        except Exception as cover_error:
            frame_error = str(cover_error)

    if not final_video_ready:
        log_cb(f"[{voice_name}] ⚠️ Không tạo được ảnh bìa tạm, dùng luôn video render gốc. {frame_error[:180]}")
        shutil.copy2(temp_main_mp4, out_file)
        final_video_ready = os.path.exists(out_file) and os.path.getsize(out_file) > 0

    if not final_video_ready:
        raise Exception(f"Không lưu được video đầu ra cho {voice_name}")

    for f_path in [filter_script_path, temp_main_mp4, temp_frame_jpg, temp_cover_png]:
        if os.path.exists(f_path):
            try: os.remove(f_path)
            except: pass

    with csv_write_lock:
        with open(excel_log_file, 'a', encoding='utf-8-sig', newline='') as f:
            csv.writer(f).writerow([datetime.now().strftime('%d/%m/%Y %H:%M'), proj_name, voice_name, out_file, "Chưa chuyển"])

    shopee_out_of_stock = is_shopee_out_of_stock_project(proj_dir)
    exported_to_shopee, shopee_export_path = export_rendered_video_to_shopee_files(proj_dir, out_file, config=config, default_status="Chưa chuyển")
    if shopee_out_of_stock:
        log_cb(f"[{voice_name}] ⏭️ Shopee đang để Hết hàng, bỏ qua ghi file job đăng.")
    elif exported_to_shopee:
        log_cb(f"[{voice_name}] ✅ Đã ghi dữ liệu Shopee vào: {shopee_export_path}")