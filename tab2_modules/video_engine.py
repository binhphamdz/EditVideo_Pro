import os
import random
import subprocess
import csv
import json
import threading # [MỚI] IMPORT THƯ VIỆN KHÓA
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# =======================================================
# [MỚI] TẠO Ổ KHÓA TOÀN CỤC BẢO VỆ FILE EXCEL (CSV)
# =======================================================
csv_write_lock = threading.Lock()

SAFE_XFADE_TRANSITIONS = {
    'fade', 'slideleft', 'slideright', 'slideup', 'slidedown',
    'wipeleft', 'wiperight', 'hlslice', 'zoomin'
}

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
    whoosh_sfx_path = os.path.join(os.getcwd(), "whoosh.mp3") 
    
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
        available_trans = [trans_mapping.get(t, "fade") for t in selected_trans_keys if t in trans_mapping]
        
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

    log_cb(f"[{voice_name}] Đang bốc ngẫu nhiên 1 frame làm ảnh bìa...")
    safe_max_time = max(1.0, voice_dur - 1.0)
    random_t = random.uniform(1.0, safe_max_time)
    
    temp_frame_jpg = os.path.join(out_dir, f"temp_frame_{os.path.splitext(voice_name)[0]}.jpg")
    subprocess.run(['ffmpeg', '-y', '-ss', f"{random_t:.2f}", '-i', temp_main_mp4, '-frames:v', '1', '-update', '1', temp_frame_jpg], capture_output=True, creationflags=creation_flags)
    
    temp_cover_png = os.path.join(out_dir, f"temp_cover_{os.path.splitext(voice_name)[0]}.png")
    with Image.open(temp_frame_jpg).convert("RGBA") as img:
        draw = ImageDraw.Draw(img)
        img_w, img_h = img.size
        clean_proj_name = proj_name.replace("_", " ").upper()
        words = clean_proj_name.split()
        if len(words) > 2:
            mid = len(words) // 2
            display_text = " ".join(words[:mid]) + "\n" + " ".join(words[mid:])
        else: display_text = clean_proj_name

        font_size = 200
        def get_font_and_fit(f_size):
            f = ImageFont.truetype(custom_font if (custom_font and os.path.exists(custom_font)) else "arial.ttf", f_size)
            bbox = draw.multiline_textbbox((img_w/2, img_h/2), display_text, font=f, anchor="mm", align="center")
            return bbox[2] - bbox[0], f
        
        txt_w, font = get_font_and_fit(font_size)
        while txt_w > img_w * 0.9 and font_size > 20:
            font_size -= 5
            txt_w, font = get_font_and_fit(font_size)

        stroke_w = int(font_size * 0.12)
        draw.multiline_text((img_w/2, img_h/2), display_text, font=font, fill="white", align="center", anchor="mm", stroke_width=stroke_w, stroke_fill="black")
        img.convert("RGB").save(temp_cover_png)

    ffmpeg_concat_cmd = [
        "ffmpeg", "-y", "-loop", "1", "-t", "0.1", "-i", temp_cover_png, "-i", temp_main_mp4,
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "1:a",
        "-c:v", "h264_nvenc", "-preset", "p1", "-b:v", "8000k", "-c:a", "copy", out_file
    ]
    subprocess.run(ffmpeg_concat_cmd, capture_output=True, text=True, errors='ignore', creationflags=creation_flags)

    for f_path in [filter_script_path, temp_main_mp4, temp_frame_jpg, temp_cover_png]:
        if os.path.exists(f_path):
            try: os.remove(f_path)
            except: pass

    with csv_write_lock:
        with open(excel_log_file, 'a', encoding='utf-8-sig', newline='') as f:
            csv.writer(f).writerow([datetime.now().strftime('%d/%m/%Y %H:%M'), proj_name, voice_name, out_file, "Chưa chuyển"])