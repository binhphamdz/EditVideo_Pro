# Hướng Dẫn Chuyển Từ Cloudflare Sang FRP
## ==========================================

## 📋 Yêu Cầu
- FRP Server đã setup trên VPS (DONE ✅)
- FRP Client cho Windows
- Domain trỏ A record về IP VPS

## 🔧 Bước 1: Sửa File frpc.toml
Mở file `frpc.toml` và thay đổi:

```toml
serverAddr = "THAY_BẰNG_IP_VPS_CỦA_BẠN"  # Ví dụ: "185.199.111.133"
serverPort = 7000
```

Nếu FRP server có token bảo mật, uncomment dòng:
```toml
auth.token = "your-secret-token"
```

## 🔧 Bước 2: Download FRP Client Cho Windows
1. Vào: https://github.com/fatedier/frp/releases
2. Tải file: `frp_x.xx.x_windows_amd64.zip` (version 0.56.0 hoặc mới hơn)
3. Giải nén vào folder `c:\frp\`

## 🔧 Bước 3: Copy File Config
Copy file `frpc.toml` vào folder FRP:
```powershell
Copy-Item frpc.toml c:\frp\
```

## 🔧 Bước 4: Chạy FRP Client
Mở PowerShell/CMD và chạy:
```powershell
cd c:\frp
.\frpc.exe -c frpc.toml
```

Nếu thành công, bạn sẽ thấy:
```
[I] [service.go:xxx] [editvideo_tool] proxy added
[I] [proxy.go:xxx] [editvideo_tool] start proxy success
```

## 🔧 Bước 5: Chạy Web Server
Trong terminal khác (trong EditVideo_Pro):
```powershell
python server.py
```

## ✅ Kiểm Tra
1. Mở trình duyệt: `http://editvideopro.online:8080` (hoặc port VPS của bạn)
2. Hoặc nếu đã config Nginx reverse proxy: `http://editvideopro.online`

## 🔄 Auto-Start FRP Client
### Cách 1: Task Scheduler (Windows)
1. Mở Task Scheduler
2. Create Basic Task
3. Trigger: At startup
4. Action: Start a program
5. Program: `c:\frp\frpc.exe`
6. Arguments: `-c c:\frp\frpc.toml`
7. Start in: `c:\frp\`

### Cách 2: NSSM (Recommended)
Download NSSM từ: https://nssm.cc/download
```powershell
nssm install frpc_client "c:\frp\frpc.exe" "-c c:\frp\frpc.toml"
nssm set frpc_client AppDirectory "c:\frp"
nssm start frpc_client
```

## 🐛 Troubleshooting

### Lỗi: "no route found"
- Kiểm tra domain trong frpc.toml khớp với customDomains
- Kiểm tra FRP server logs xem có nhận được kết nối không

### Lỗi: "connection refused"
- Kiểm tra serverAddr và serverPort đúng chưa
- Kiểm tra firewall VPS có mở port 7000 không

### Lỗi: CORS
- Server.py đã được update CORS cho domain mới
- Restart server.py sau khi sửa

## 📝 So Sánh Cloudflare vs FRP

| Feature | Cloudflare Tunnel | FRP |
|---------|------------------|-----|
| Setup | Dễ (cloudflared) | Trung bình |
| Performance | Tốt | Rất tốt (trực tiếp) |
| Security | HTTPS tự động | Cần config Nginx |
| Cost | Free | Free (self-hosted) |
| Upload Speed | Giới hạn | Không giới hạn |

## 🎯 Next Steps
Sau khi FRP hoạt động, nên:
1. Setup Nginx reverse proxy trên VPS (HTTPS với Let's Encrypt)
2. Tắt Cloudflare tunnel nếu không dùng nữa
3. Monitor FRP logs để debug
