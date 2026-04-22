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
from ai_model_registry import (
    DEFAULT_AI_MODEL,
    DEFAULT_AI_PROVIDER,
    get_kie_endpoint,
    normalize_ai_model,
    normalize_ai_provider,
    supports_provider,
    to_openrouter_model,
)

# ========================================================================
# ✨ AI PROVIDER WITH AUTO-FALLBACK (kie.ai → openrouter.ai)
# ========================================================================
def _call_ai_api_with_fallback(model, messages, temperature, config, log_cb, voice_name, retry_delays=[3, 10, 30]):
    """
    Gọi AI API với cơ chế fallback từ kie.ai sang openrouter.ai
    
    Args:
        model: Tên model (vd: "gemini-2.5-flash" hoặc "google/gemma-4-31b-it:free")
        messages: List of message dicts [{role, content}]
        temperature: Temperature value
        config: Dict cấu hình chứa kie_key, openrouter_key, ai_model
        log_cb: Callback function để log
        voice_name: Tên voice cho logging
        retry_delays: List delay giữa các lần retry
    
    Returns:
        str: Content từ AI response
    
    Raises:
        Exception: Nếu cả 2 provider đều thất bại
    """
    kie_key = str(config.get('kie_key') or '').strip()
    openrouter_key = str(config.get('openrouter_key') or '').strip()
    
    # Lấy provider preference và model từ config theo registry chung
    ai_provider = normalize_ai_provider(str(config.get('ai_provider') or DEFAULT_AI_PROVIDER).strip().lower())
    selected_model = normalize_ai_model(str(config.get('ai_model') or model or DEFAULT_AI_MODEL).strip(), ai_provider)
    
    # Log để debug
    if log_cb:
        log_cb(f"🔧 AI Config: Provider={ai_provider}, Model={selected_model}")
    
    # Danh sách providers để thử (theo thứ tự ưu tiên)
    providers = []
    
    # Build providers list dựa theo user preference
    if ai_provider == 'auto':
        # Chế độ auto: Kie.ai -> OpenRouter fallback
        if kie_key and kie_key.lower() != 'dummy' and supports_provider(selected_model, 'kie'):
            kie_endpoint = get_kie_endpoint(selected_model)
            if kie_endpoint:
                providers.append({
                    'name': 'kie.ai',
                    'url': kie_endpoint,
                    'headers': {
                        'Authorization': f'Bearer {kie_key}',
                        'Content-Type': 'application/json'
                    },
                    'model': selected_model
                })
        if openrouter_key and openrouter_key.lower() != 'dummy' and supports_provider(selected_model, 'openrouter'):
            providers.append({
                'name': 'openrouter.ai',
                'url': 'https://openrouter.ai/api/v1/chat/completions',
                'headers': {
                    'Authorization': f'Bearer {openrouter_key}',
                    'Content-Type': 'application/json',
                    'HTTP-Referer': 'https://editvideopro.online',
                    'X-OpenRouter-Title': 'EditVideo Pro'
                },
                'model': to_openrouter_model(selected_model)
            })
    elif ai_provider == 'kie':
        # Chỉ dùng Kie.ai
        if kie_key and kie_key.lower() != 'dummy' and supports_provider(selected_model, 'kie'):
            kie_endpoint = get_kie_endpoint(selected_model)
            if kie_endpoint:
                providers.append({
                    'name': 'kie.ai',
                    'url': kie_endpoint,
                    'headers': {
                        'Authorization': f'Bearer {kie_key}',
                        'Content-Type': 'application/json'
                    },
                    'model': selected_model
                })
    elif ai_provider == 'openrouter':
        # Chỉ dùng OpenRouter
        if openrouter_key and openrouter_key.lower() != 'dummy' and supports_provider(selected_model, 'openrouter'):
            providers.append({
                'name': 'openrouter.ai',
                'url': 'https://openrouter.ai/api/v1/chat/completions',
                'headers': {
                    'Authorization': f'Bearer {openrouter_key}',
                    'Content-Type': 'application/json',
                    'HTTP-Referer': 'https://editvideopro.online',
                    'X-OpenRouter-Title': 'EditVideo Pro'
                },
                'model': to_openrouter_model(selected_model)
            })
    
    if not providers:
        raise Exception(f"Không thể chạy model '{selected_model}' với provider '{ai_provider}'. Kiểm tra lại API key hoặc chọn model phù hợp.")
    
    last_error = None
    
    # Thử từng provider
    for provider_idx, provider in enumerate(providers):
        provider_name = provider['name']
        
        # Retry logic cho mỗi provider
        for attempt in range(3):
            try:
                if attempt > 0:
                    delay = retry_delays[attempt - 1]
                    log_cb(f"[{voice_name}] ⏳ [{provider_name}] Đợi {delay}s trước khi thử lại...")
                    time.sleep(delay)
                
                payload = {
                    'model': provider['model'],
                    'messages': messages,
                    'temperature': temperature
                }
                
                res = requests.post(provider['url'], headers=provider['headers'], json=payload, timeout=180)
                
                # Kiểm tra response có phải JSON không
                try:
                    resp_data = res.json()
                except:
                    raise Exception(f"API trả về HTML/text thay vì JSON (bị block/cloudflare). Response: {res.text[:200]}")
                
                # Kiểm tra lỗi maintenance từ server
                if resp_data.get('code') == 500:
                    maintenance_msg = resp_data.get('msg', 'Server error')
                    raise Exception(f"Server đang bảo trì: {maintenance_msg}")
                
                if res.status_code != 200:
                    raise Exception(f"HTTP {res.status_code}: {json.dumps(resp_data, ensure_ascii=False)[:200]}")
                
                choices = resp_data.get('choices')
                if not choices:
                    raise Exception(f"API trả về không có 'choices': {json.dumps(resp_data, ensure_ascii=False)[:300]}")
                
                content = choices[0]['message']['content']
                log_cb(f"[{voice_name}] ✅ [{provider_name}] Model: {provider['model']} - API call thành công!")
                return content
                
            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                
                # Nếu là lỗi bảo trì hoặc lỗi server, chuyển provider ngay
                is_server_error = ('500' in error_msg or 'bảo trì' in error_msg.lower() or 
                                  'maintenance' in error_msg.lower() or 'HTML' in error_msg)
                
                if is_server_error and provider_idx < len(providers) - 1:
                    log_cb(f"[{voice_name}] ⚠️ [{provider_name}] Lỗi server: {error_msg[:150]}")
                    log_cb(f"[{voice_name}] 🔄 Chuyển sang provider tiếp theo...")
                    break  # Thoát vòng retry, chuyển sang provider khác
                
                if attempt == 2:
                    # Hết số lần retry cho provider này
                    if provider_idx < len(providers) - 1:
                        log_cb(f"[{voice_name}] ⚠️ [{provider_name}] Thất bại sau 3 lần thử: {error_msg[:150]}")
                        log_cb(f"[{voice_name}] 🔄 Chuyển sang provider tiếp theo...")
                        break  # Chuyển sang provider khác
                    else:
                        # Đã hết providers
                        raise Exception(f"Tất cả providers đều thất bại. Lỗi cuối: {error_msg}")
                
                log_cb(f"[{voice_name}] ⚠️ [{provider_name}] Thất bại (Lần {attempt+1}/3): {error_msg[:150]}")
    
    # Nếu chạy đến đây là đã thử hết providers
    raise Exception(f"Tất cả AI providers đều thất bại. Lỗi cuối: {last_error}")

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

    # =========================================================
    # VÒNG 1: TRỢ LÝ AI (CÓ CƠ CHẾ AUTO-FALLBACK kie.ai → openrouter.ai)
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
    
    raw_timeline = []
    try:
        raw_text_1 = _call_ai_api_with_fallback(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": prompt_1}],
            temperature=0.5,
            config=config,
            log_cb=log_cb,
            voice_name=voice_name
        )
        raw_timeline = extract_json_array(raw_text_1)
    except Exception as e:
        raise Exception(f"Lỗi Vòng 1: {str(e)}")

    # =========================================================
    # VÒNG 2: TỔNG ĐẠO DIỄN AI (CÓ AUTO-FALLBACK kie.ai → openrouter.ai)
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

    final_timeline = []
    try:
        raw_text_2 = _call_ai_api_with_fallback(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": prompt_2}],
            temperature=0.2,
            config=config,
            log_cb=log_cb,
            voice_name=voice_name
        )
        final_timeline = extract_json_array(raw_text_2)
    except Exception as e:
        raise Exception(f"Lỗi Vòng 2: {str(e)}")

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
    import os
    import hashlib

    # --- Cache Vòng 0 (tránh gọi API lại cho cùng một đoạn voice) ---
    def _v0_cache_path():
        base = config.get('app_base_path', '')
        return os.path.join(base, 'Workspace_Data', 'v0_cache.json') if base else ''

    def _load_v0_cache():
        p = _v0_cache_path()
        if p and os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_v0_cache(cache):
        p = _v0_cache_path()
        if p:
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, 'w', encoding='utf-8') as f:
                    json.dump(cache, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    cache_key = hashlib.md5(raw_voice_text.strip().encode('utf-8')).hexdigest()
    _v0_cache = _load_v0_cache()
    if cache_key in _v0_cache:
        log_cb(f"[{voice_name}] ✅ Vòng 0: Đã có cache, bỏ qua API tiết kiệm credit.")
        return _v0_cache[cache_key]

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

    # Kiểm tra xem có API key nào không
    kie_key = str(config.get('kie_key') or '').strip()
    openrouter_key = str(config.get('openrouter_key') or '').strip()
    
    if (not kie_key or kie_key.lower() == 'dummy') and (not openrouter_key or openrouter_key.lower() == 'dummy'):
        log_cb(f"[{voice_name}] ⚠️ Chưa cấu hình API key, bỏ qua Vòng 0.")
        return raw_voice_text

    optimized_text = ""
    try:
        raw_out = _call_ai_api_with_fallback(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": prompt_0}],
            temperature=0.2,
            config=config,
            log_cb=log_cb,
            voice_name=voice_name
        )
        final_json = extract_json_array(raw_out)
        final_json = _merge_related_short_segments(final_json, target_min=4.0, target_max=6.0)
        optimized_text = _format_timeline_text(final_json)
        # Lưu cache để lần sau bỏ qua API
        _v0_cache[cache_key] = optimized_text
        _save_v0_cache(_v0_cache)
    except Exception as e:
        error_msg = str(e)
        log_cb(f"[{voice_name}] ⚠️ Vòng 0 thất bại: {error_msg[:150]}. Bỏ qua và dùng kịch bản gốc.")
        return raw_voice_text # Lỗi thì trả về kịch bản gốc, không làm gián đoạn

    return optimized_text if optimized_text else raw_voice_text