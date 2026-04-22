# Script kiểm tra xem AI Soi có được lưu vào file không

import json
import sys
from pathlib import Path

# Đường dẫn đến workspace data
WORKSPACE = Path(r"C:\Users\Binh\Desktop\EditVideo_Pro\Workspace_Data")

def check_project_descriptions(project_id):
    """Kiểm tra descriptions trong project_data.json"""
    project_file = WORKSPACE / project_id / "project_data.json"
    
    if not project_file.exists():
        print(f"❌ File không tồn tại: {project_file}")
        return
    
    print(f"📂 Đọc file: {project_file}")
    print()
    
    with open(project_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    videos = data.get('videos', {})
    
    if not videos:
        print("⚠️ Không có video nào trong project")
        return
    
    print(f"📊 Tổng số video: {len(videos)}")
    print()
    
    has_desc = []
    no_desc = []
    
    for name, meta in videos.items():
        desc = meta.get('description', '')
        if desc and desc.strip():
            has_desc.append((name, desc))
        else:
            no_desc.append(name)
    
    # Hiển thị kết quả
    print(f"✅ Video có mô tả: {len(has_desc)}/{len(videos)}")
    if has_desc:
        print()
        for name, desc in has_desc[:10]:  # Hiển thị tối đa 10
            print(f"   📝 {name}")
            print(f"      {desc[:100]}...")
            print()
    
    if no_desc:
        print(f"⚠️ Video chưa có mô tả: {len(no_desc)}/{len(videos)}")
        for name in no_desc[:5]:  # Hiển thị tối đa 5
            print(f"   - {name}")
        if len(no_desc) > 5:
            print(f"   ... và {len(no_desc) - 5} video khác")

if __name__ == "__main__":
    # Liệt kê các project
    if len(sys.argv) > 1:
        project_id = sys.argv[1]
        check_project_descriptions(project_id)
    else:
        print("📁 Các project có sẵn:")
        print()
        projects = [p for p in WORKSPACE.iterdir() if p.is_dir() and not p.name.startswith('.')]
        projects.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        
        for i, project in enumerate(projects[:10], 1):
            project_file = project / "project_data.json"
            if project_file.exists():
                with open(project_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                video_count = len(data.get('videos', {}))
                print(f"{i}. {project.name} ({video_count} videos)")
        
        print()
        print("Cách dùng:")
        print(f"  python {sys.argv[0]} <project_id>")
        print()
        print("Ví dụ:")
        if projects:
            print(f"  python {sys.argv[0]} {projects[0].name}")
