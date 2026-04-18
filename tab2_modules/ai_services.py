import os
import time
import requests
import json
import random
import re # [MỚI] Bùa móc JSON chống AI nói nhảm
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def _normalize_text(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def _format_timeline_text(segments):
    lines = []
    for item in segments:
        text = _normalize_text(item.get("text", ""))
        if not text:
            continue
        start = round(float(item.get("start", 0.0)), 2)
        end = round(float(item.get("end", start)), 2)
        lines.append(f"[{start}s - {end}s]: {text}")
    return "\n".join(lines) + ("\n" if lines else "")


def _parse_timeline_text(raw_voice_text):
    items = []
    pattern = re.compile(r'\[\s*([0-9]+(?:\.[0-9]+)?)s\s*-\s*([0-9]+(?:\.[0-9]+)?)s\s*\]:\s*(.+)')
    for line in (raw_voice_text or "").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        start, end, text = match.groups()
        text = _normalize_text(text)
        if not text:
            continue
        items.append({"start": float(start), "end": float(end), "text": text})
    return items


def _segments_related(text_a, text_b):
    a = _normalize_text(text_a).lower()
    b = _normalize_text(text_b).lower()
    if not a or not b:
        return True

    if a.endswith((",", ":", ";", "-", "–", "...")):
        return True

    connectors = [
        "và", "rồi", "nhưng", "nên", "để", "khi", "vì", "còn",
        "thì", "là", "với", "hay", "hoặc", "sau đó", "đồng thời"
    ]
    if any(b == c or b.startswith(c + " ") for c in connectors):
        return True

    tokens_a = {w for w in re.findall(r'\w+', a, flags=re.UNICODE) if len(w) > 1}
    tokens_b = {w for w in re.findall(r'\w+', b, flags=re.UNICODE) if len(w) > 1}
    if tokens_a & tokens_b:
        return True

    return len(tokens_a) <= 4 or len(tokens_b) <= 4


def _merge_related_short_segments(segments, target_min=4.0, target_max=6.0):
    if not segments:
        return []

    merged = []
    i = 0
    while i < len(segments):
        current = {
            "start": float(segments[i].get("start", 0.0)),
            "end": float(segments[i].get("end", 0.0)),
            "text": _normalize_text(segments[i].get("text", ""))
        }

        while i + 1 < len(segments):
            nxt = {
                "start": float(segments[i + 1].get("start", current["end"])),
                "end": float(segments[i + 1].get("end", current["end"])),
                "text": _normalize_text(segments[i + 1].get("text", ""))
            }
            if not nxt["text"]:
                i += 1
                continue

            current_dur = current["end"] - current["start"]
            combined_dur = nxt["end"] - current["start"]
            gap = max(0.0, nxt["start"] - current["end"])

            if gap > 1.2:
                break

            should_merge = False
            if current_dur < target_min and combined_dur <= target_max + 0.8 and _segments_related(current["text"], nxt["text"]):
                should_merge = True
            elif len(current["text"].split()) <= 6 and combined_dur <= target_max and _segments_related(current["text"], nxt["text"]):
                should_merge = True

            if not should_merge:
                break

            current["end"] = nxt["end"]
            current["text"] = _normalize_text(current["text"].rstrip(", ") + " " + nxt["text"])
            i += 1

            if (current["end"] - current["start"]) >= target_min and current["text"].endswith((".", "!", "?")):
                break

        merged.append(current)
        i += 1

    return merged


def _words_to_base_segments(words_list):
    segments = []
    chunk = []

    for word_data in words_list:
        word = _normalize_text(word_data.get('word', ''))
        if word in ['<start>', '<end>', '']:
            continue

        chunk.append({
            "start": float(word_data.get('start_time', 0.0)),
            "end": float(word_data.get('end_time', 0.0)),
            "text": word
        })

        chunk_dur = chunk[-1]["end"] - chunk[0]["start"]
        is_sentence_end = any(word.endswith(p) for p in ['.', '?', '!', ';', ':'])

        if is_sentence_end or chunk_dur >= 5.2 or len(chunk) >= 14:
            segments.append({
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
                "text": " ".join(item["text"] for item in chunk)
            })
            chunk = []

    if chunk:
        segments.append({
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
            "text": " ".join(item["text"] for item in chunk)
        })

    return segments


def get_drive_service(client_secret_path, base_path):
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    creds = None
    
    token_path = os.path.join(base_path, 'token.json')
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

def get_transcription(voice_path, voice_name, mode, config, log_cb):
    if mode == "groq":
        log_cb(f"[{voice_name}] Bắt đầu: Gọi Groq bóc băng...")
        url_groq = "https://api.groq.com/openai/v1/audio/transcriptions"
        with open(voice_path, "rb") as f:
            res_groq = requests.post(
                url_groq, 
                headers={"Authorization": f"Bearer {config.get('groq_key')}"}, 
                files={"file": ("v.mp3", f)}, 
                data={"model": "whisper-large-v3", "language": "vi", "response_format": "verbose_json"}, 
                timeout=180
            )
        if res_groq.status_code != 200: raise Exception(f"Lỗi Groq: {res_groq.text}")
        raw_segments = res_groq.json().get("segments", [])
        base_segments = [
            {
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", 0.0)),
                "text": _normalize_text(s.get("text", ""))
            }
            for s in raw_segments if _normalize_text(s.get("text", ""))
        ]
        merged_segments = _merge_related_short_segments(base_segments, target_min=4.0, target_max=6.0)
        return _format_timeline_text(merged_segments)

    elif mode == "ohfree":
        # =================================================================
        # [ĐÃ SỬA] DÙNG LA BÀN TÌM ĐÚNG FILE CLIENT_SECRET CẠNH CỤC EXE
        # =================================================================
        base_path = config.get("app_base_path", os.getcwd())
        client_secret = os.path.join(base_path, "client_secret.json")
        
        cookie = config.get("ohfree_cookie", "")
        if not os.path.exists(client_secret): 
            raise Exception(f"Chưa cấu hình client_secret.json! Hãy để file này cạnh file .exe nhé. (Đang tìm tại: {client_secret})")
        if not cookie: 
            raise Exception("Chưa cấu hình Cookie OhFree!")

        log_cb(f"[{voice_name}] Đang bơm lên Drive (OhFree Mode)...")
        # Truyền thêm base_path vào để nó lưu token
        drive_service = get_drive_service(client_secret, base_path)
        
        file_metadata = {'name': f"auto_{int(time.time())}.mp3", 'parents': ["1K3iG8kCf8BEGYps9Q1pXWShuukGsEgas"]} # Sửa ID thư mục Drive của bác nếu cần
        media = MediaFileUpload(voice_path, mimetype='audio/mpeg')
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        file_id = file.get('id')
        
        try:
            drive_service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
            drive_link = f"https://drive.google.com/file/d/{file_id}/view?usp=drive_link"
            log_cb(f"[{voice_name}] Đang bắn link cho OhFree bóc băng...")
            res = requests.post("https://tts.ohfree.me/api/mp3-to-text", headers={"User-Agent": "Mozilla/5.0", "Cookie": cookie}, files={'url': (None, drive_link)}, timeout=300)
            if res.status_code != 200: raise Exception(f"OhFree từ chối: {res.text[:100]}")
            
            words_list = res.json().get('data', {}).get('words', [])
            if not words_list: raise Exception("OhFree không trả về text!")
            base_segments = _words_to_base_segments(words_list)
            merged_segments = _merge_related_short_segments(base_segments, target_min=4.0, target_max=6.0)
            return _format_timeline_text(merged_segments)
        finally:
            try: drive_service.files().delete(fileId=file_id).execute()
            except: pass

def get_director_timeline(voice_text, broll_text, config, log_cb, voice_name):
    import time
    import requests
    import json
    import re
    
    # 👉 [SẾP THÊM ĐÚNG DÒNG NÀY VÀO ĐÂY NHÉ] 
    # Gọi AI Vòng 0 để "Gom câu chống giật" trước khi Đạo diễn Vòng 1 làm việc:
    voice_text = optimize_voice_timeline_by_ai(voice_text, config, log_cb, voice_name)
    
    # =========================================================
    # Hàm Bóc Vỏ JSON & Sửa Lỗi Vặt (Trailing Commas)
    # =========================================================
    def extract_json_array(text):
        json_str = ""
        # ... (các đoạn code bên dưới của sếp giữ nguyên 100%) ...
        json_str = ""
        match = re.search(r'```json\s*(\[.*?\])\s*```', text, re.DOTALL | re.IGNORECASE)
        if match: json_str = match.group(1)
        else:
            match = re.search(r'```\s*(\[.*?\])\s*```', text, re.DOTALL)
            if match: json_str = match.group(1)
            else:
                match = re.search(r'\[.*\]', text, re.DOTALL)
                if match: json_str = match.group(0)
                else: raise ValueError("Không thể tìm thấy mảng JSON hợp lệ!")
                
        # [BÙA MỚI] Xóa dấu phẩy thừa ở cuối mảng/object (Lỗi AI hay mắc nhất)
        json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
        return json.loads(json_str)

    url_kie = "https://api.kie.ai/gemini-2.5-flash/v1/chat/completions"
    headers = {"Authorization": f"Bearer {config.get('kie_key')}", "Content-Type": "application/json"}

    # =========================================================
    # VÒNG 1: TRỢ LÝ AI (CÓ CƠ CHẾ THỬ LẠI 3 LẦN)
    # =========================================================
    log_cb(f"[{voice_name}] Đạo diễn AI Vòng 1: Đang lọc rổ video ứng viên...")
    
    prompt_1 = f"""Dưới đây là Kho video có kèm theo MÔ TẢ CHI TIẾT và [SỐ LẦN ĐÃ DÙNG] của từng cảnh:
{broll_text}

Nội dung Voice (Giọng đọc):
{voice_text}

VÒNG 1 - TÌM KIẾM ỨNG VIÊN:
1. Đọc kỹ từng câu thoại.
2. Chọn ra TỪ 3 ĐẾN 5 VIDEO ỨNG VIÊN phù hợp nhất về mặt ngữ nghĩa cho câu thoại đó.
3. Ưu tiên nhặt những video có "Đã dùng: 0 lần" hoặc số lần dùng thấp.
4. BẮT BUỘC trả về ĐÚNG CÚ PHÁP JSON (có dấu ngoặc kép ở các key):
[ {{"start": 0.0, "end": 2.5, "text": "...", "candidates": ["vid1.mp4", "vid2.mp4"]}} ]"""
            
    payload_1 = {"model": "gemini-2.5-flash", "messages": [{"role": "user", "content": prompt_1}], "temperature": 0.5}
    
    raw_timeline = []
    for attempt in range(3): # Vòng lặp tái sinh
        try:
            time.sleep(2)
            res_1 = requests.post(url_kie, headers=headers, json=payload_1, timeout=180)
            if res_1.status_code != 200: raise Exception(f"Lỗi API Vòng 1: {res_1.text}")
            
            raw_text_1 = res_1.json()["choices"][0]["message"]["content"]
            raw_timeline = extract_json_array(raw_text_1)
            break # Nếu thành công thì thoát vòng lặp ngay
        except Exception as e:
            if attempt == 2: raise Exception(f"Lỗi Vòng 1 (Đã thử 3 lần vẫn hỏng JSON): {str(e)}")
            log_cb(f"[{voice_name}] ⚠️ Vòng 1 AI viết sai chính tả JSON, đang ép AI viết lại (Lần {attempt+2}/3)...")

    # =========================================================
    # VÒNG 2: TỔNG ĐẠO DIỄN AI (CÓ CƠ CHẾ THỬ LẠI 3 LẦN)
    # =========================================================
    log_cb(f"[{voice_name}] Đạo diễn AI Vòng 2: Đo đạc thời lượng & Ghép chuỗi cảnh...")
    
    candidates_json_str = json.dumps(raw_timeline, ensure_ascii=False, indent=2)
    
    prompt_2 = f"""Dưới đây là Kịch bản nháp (gồm start/end của câu thoại) và danh sách Video Ứng Viên:
{candidates_json_str}

Thông tin chi tiết (Độ dài giây, Mô tả, Số lần dùng) của toàn bộ kho:
{broll_text}

VÒNG 2 - CHỐT HẠ CHUỖI VIDEO:
1. Tính Thời lượng câu thoại (end - start).
2. Chọn video từ mảng 'candidates' ưu tiên Số lần dùng thấp nhất.
3. CHIẾN LƯỢC NỐI CẢNH: 
   - Nếu video ngắn hơn thời lượng thoại -> CHỌN THÊM video từ rổ ứng viên ghép vào.
   - Tổng độ dài các video được chọn phải lớn hơn hoặc bằng thời lượng thoại.
   - TUYỆT ĐỐI KHÔNG chọn lặp lại 1 video 2 lần trong cùng 1 câu thoại.
4. BẮT BUỘC trả về ĐÚNG CÚ PHÁP JSON (có dấu ngoặc kép ở các key):
[ {{"start": 0.0, "end": 4.5, "text": "...", "video_files": ["vid_1.mp4", "vid_2.mp4"]}} ]"""

    payload_2 = {"model": "gemini-2.5-flash", "messages": [{"role": "user", "content": prompt_2}], "temperature": 0.2}
    
    final_timeline = []
    for attempt in range(3): # Vòng lặp tái sinh
        try:
            time.sleep(2)
            res_2 = requests.post(url_kie, headers=headers, json=payload_2, timeout=180)
            if res_2.status_code != 200: raise Exception(f"Lỗi API Vòng 2: {res_2.text}")
            
            raw_text_2 = res_2.json()["choices"][0]["message"]["content"]
            final_timeline = extract_json_array(raw_text_2)
            break # Thành công thì thoát
        except Exception as e:
            if attempt == 2: raise Exception(f"Lỗi Vòng 2 (Đã thử 3 lần vẫn hỏng JSON): {str(e)}")
            log_cb(f"[{voice_name}] ⚠️ Vòng 2 AI viết sai chính tả JSON, đang ép AI viết lại (Lần {attempt+2}/3)...")

    # =========================================================
    # KIỂM TRA BẢO HIỂM LẦN CUỐI (SAFETY NET)
    # =========================================================
    for item in final_timeline:
        if "video_files" not in item or not isinstance(item["video_files"], list) or len(item["video_files"]) == 0:
            item["video_files"] = []
            for raw_item in raw_timeline:
                if raw_item.get("text") == item.get("text") and raw_item.get("candidates"):
                    item["video_files"] = [raw_item["candidates"][0]]
                    break
            if not item.get("video_files"):
                item["video_files"] = []

    # =========================================================
    # [MỚI] KIỂM TRA & NGĂN VIDEO LẶP GIỮA CÁC CÂU THOẠI
    # =========================================================
    def prevent_duplicate_videos(timeline, candidates_map):
        """Quét timeline và thay thế video lặp bằng ứng viên khác"""
        global_used = set()
        
        for idx, row in enumerate(timeline):
            row_text = row.get("text", "")
            candidates = candidates_map.get(row_text, [])
            current_vids = row.get("video_files", [])
            new_vids = []
            
            for vid in current_vids:
                if vid not in global_used:
                    # Video này chưa dùng, nhận cho câu này
                    new_vids.append(vid)
                    global_used.add(vid)
                else:
                    # Video này đã dùng, tìm video thay thế từ ứng viên
                    replaced = False
                    for candidate in candidates:
                        if candidate not in global_used and candidate not in new_vids:
                            new_vids.append(candidate)
                            global_used.add(candidate)
                            replaced = True
                            log_cb(f"[{voice_name}] ⚠️ Video '{vid}' bị lặp, đã thay bằng '{candidate}'.")
                            break
                    
                    if not replaced:
                        # Không tìm được ứng viên mới, cảnh báo nhưng vẫn giữ lại
                        log_cb(f"[{voice_name}] ⚠️ Video '{vid}' bị lặp, không tìm được thay thế, tạm giữ lại.")
                        new_vids.append(vid)
            
            row["video_files"] = new_vids if new_vids else current_vids
        
        return timeline
    
    # Build candidates map từ raw_timeline
    candidates_map = {item.get("text", ""): item.get("candidates", []) for item in raw_timeline}
    final_timeline = prevent_duplicate_videos(final_timeline, candidates_map)
    log_cb(f"[{voice_name}] ✅ Kiểm tra xong - Video trong video không bị lặp.")

    return final_timeline


def optimize_voice_timeline_by_ai(raw_voice_text, config, log_cb, voice_name):
    import time
    import requests
    import json
    import re
    
    # Hàm bóc vỏ JSON (Tái sử dụng lại cho chắc cú)
    def extract_json_array(text):
        json_str = ""
        match = re.search(r'```json\s*(\[.*?\])\s*```', text, re.DOTALL | re.IGNORECASE)
        if match: json_str = match.group(1)
        else:
            match = re.search(r'```\s*(\[.*?\])\s*```', text, re.DOTALL)
            if match: json_str = match.group(1)
            else:
                match = re.search(r'\[.*\]', text, re.DOTALL)
                if match: json_str = match.group(0)
                else: raise ValueError("Không tìm thấy mảng JSON!")
        json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
        return json.loads(json_str)

    parsed_items = _parse_timeline_text(raw_voice_text)
    if parsed_items:
        raw_voice_text = _format_timeline_text(_merge_related_short_segments(parsed_items, target_min=4.0, target_max=6.0))

    log_cb(f"[{voice_name}] VÒNG 0: Đang nhờ AI Biên Tập gom các câu ngắn lại cho mượt...")
    
    prompt_0 = f"""Dưới đây là kịch bản giọng đọc dạng Text kèm thời gian (start - end) bị ngắt quá vụn vặt:
{raw_voice_text}

NHIỆM VỤ CỦA BẠN:
1. Đọc, hiểu ngữ cảnh và GHÉP các từ/câu ngắn liên tiếp lại thành các câu dài hơn, có ý nghĩa trọn vẹn và ngữ pháp chuẩn.
2. TỐI ƯU THỜI LƯỢNG: Ưu tiên ghép sao cho mỗi câu sau khi gộp dài khoảng 4 ĐẾN 6 GIÂY là đẹp nhất.
3. Nếu câu vẫn quá ngắn nhưng cùng ý rõ ràng với câu kế bên thì tiếp tục ghép; nếu khác ý thì giữ riêng.
4. TÍNH TOÁN THỜI GIAN: 'start' là thời gian của phần tử đầu tiên, 'end' là thời gian của phần tử cuối cùng trong nhóm được ghép.
5. Không được tạo thêm nội dung mới, chỉ được nối và làm mượt câu gốc.
6. BẮT BUỘC trả về ĐÚNG CÚ PHÁP JSON (có dấu ngoặc kép ở các key):
[ {{"start": 0.0, "end": 4.5, "text": "Nội dung câu đã được ghép mượt mà..."}}, ... ]"""

    payload_0 = {"model": "gemini-2.5-flash", "messages": [{"role": "user", "content": prompt_0}], "temperature": 0.2}
    url_kie = "https://api.kie.ai/gemini-2.5-flash/v1/chat/completions"
    headers = {"Authorization": f"Bearer {config.get('kie_key')}", "Content-Type": "application/json"}

    optimized_text = ""
    for attempt in range(3):
        try:
            time.sleep(1)
            res = requests.post(url_kie, headers=headers, json=payload_0, timeout=180)
            if res.status_code != 200: raise Exception(f"Lỗi API Vòng 0: {res.text}")
            
            raw_out = res.json()["choices"][0]["message"]["content"]
            final_json = extract_json_array(raw_out)
            final_json = _merge_related_short_segments(final_json, target_min=4.0, target_max=6.0)
            optimized_text = _format_timeline_text(final_json)
            break
        except Exception as e:
            if attempt == 2:
                log_cb(f"[{voice_name}] ⚠️ Vòng 0 thất bại. Bỏ qua và dùng kịch bản gốc.")
                return raw_voice_text # Lỗi thì trả về kịch bản gốc, không làm gián đoạn
            log_cb(f"[{voice_name}] ⚠️ Vòng 0 AI gom câu bị vấp, đang thử lại (Lần {attempt+2}/3)...")

    return optimized_text if optimized_text else raw_voice_text