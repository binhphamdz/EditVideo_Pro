# Hướng Dẫn Cấu Hình VPS cho FRP

## 📋 Yêu Cầu
- VPS IP: **160.25.81.240**
- Domain: **editvideopro.online** (A record trỏ về IP VPS)
- SSH access vào VPS

---

## 1️⃣ Kết nối SSH vào VPS

```bash
ssh root@160.25.81.240
```

---

## 2️⃣ Tải và Cài Đặt FRP Server

```bash
# Di chuyển vào thư mục /opt
cd /opt

# Tải FRP v0.56.0 (Linux AMD64)
wget https://github.com/fatedier/frp/releases/download/v0.56.0/frp_0.56.0_linux_amd64.tar.gz

# Giải nén
tar -xzf frp_0.56.0_linux_amd64.tar.gz

# Đổi tên thư mục
mv frp_0.56.0_linux_amd64 frp

# Di chuyển vào thư mục FRP
cd frp
```

---

## 3️⃣ Tạo File Cấu Hình FRP Server

Tạo file `frps.toml`:

```bash
nano frps.toml
```

Nội dung file:

```toml
# FRP Server Configuration for EditVideo Pro

# Port để FRP client kết nối
bindPort = 7000

# Port cho HTTP virtual hosting
vhostHTTPPort = 8080

# Log settings
log.to = "/var/log/frp/frps.log"
log.level = "info"
log.maxDays = 3

# Dashboard (tùy chọn - để quản lý)
webServer.addr = "0.0.0.0"
webServer.port = 7500
webServer.user = "admin"
webServer.password = "your_secure_password_here"

# Authentication (tùy chọn - bảo mật)
auth.method = "token"
auth.token = "your_secret_token_here"
```

**Lưu file:** Nhấn `Ctrl+X`, sau đó `Y`, rồi `Enter`

---

## 4️⃣ Tạo Thư Mục Log

```bash
mkdir -p /var/log/frp
```

---

## 5️⃣ Mở Firewall Ports

### Nếu dùng UFW (Ubuntu/Debian):

```bash
# Mở port 7000 (FRP client connection)
ufw allow 7000/tcp

# Mở port 8080 (HTTP access)
ufw allow 8080/tcp

# Mở port 7500 (FRP dashboard - tùy chọn)
ufw allow 7500/tcp

# Reload firewall
ufw reload

# Kiểm tra status
ufw status
```

### Nếu dùng Firewalld (CentOS/RHEL):

```bash
firewall-cmd --permanent --add-port=7000/tcp
firewall-cmd --permanent --add-port=8080/tcp
firewall-cmd --permanent --add-port=7500/tcp
firewall-cmd --reload
```

---

## 6️⃣ Tạo Systemd Service (Auto-start)

Tạo file service:

```bash
nano /etc/systemd/system/frps.service
```

Nội dung:

```ini
[Unit]
Description=FRP Server Service
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
Restart=on-failure
RestartSec=5s
ExecStart=/opt/frp/frps -c /opt/frp/frps.toml
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
```

**Lưu file:** `Ctrl+X` → `Y` → `Enter`

Enable và start service:

```bash
# Reload systemd
systemctl daemon-reload

# Enable auto-start
systemctl enable frps

# Start service
systemctl start frps

# Kiểm tra status
systemctl status frps
```

---

## 7️⃣ Kiểm Tra Logs

```bash
# Xem logs realtime
tail -f /var/log/frp/frps.log

# Hoặc xem service logs
journalctl -u frps -f
```

**Logs thành công sẽ có dòng:**
```
[I] frps started successfully
[I] start frps success
```

---

## 8️⃣ Kiểm Tra DNS

Đảm bảo domain trỏ đúng IP:

```bash
# Trên VPS hoặc máy local
nslookup editvideopro.online

# Hoặc
dig editvideopro.online +short
```

**Kết quả phải là:** `160.25.81.240`

Nếu chưa đúng, vào quản lý DNS (Cloudflare/GoDaddy/...) và thêm:
- **Type:** A
- **Name:** @ (hoặc editvideopro.online)
- **Value:** 160.25.81.240
- **TTL:** 300

---

## 9️⃣ Cập Nhật FRP Client Config (Nếu dùng Authentication)

Nếu bạn bật `auth.token` ở bước 3, cần thêm token vào `frpc.toml` trên máy Windows:

**File:** `c:\frp\frpc.toml`

```toml
serverAddr = "160.25.81.240"
serverPort = 7000
auth.method = "token"
auth.token = "your_secret_token_here"  # ⬅️ Thêm dòng này

[[proxies]]
name = "editvideo_tool"
type = "http"
localIP = "127.0.0.1"
localPort = 8000
customDomains = ["editvideopro.online"]
```

---

## 🧪 10. Test Kết Nối

### Test 1: Kiểm tra port 8080 từ bên ngoài

Từ máy local (Windows):

```powershell
Test-NetConnection -ComputerName 160.25.81.240 -Port 8080
```

**Kết quả thành công:**
```
TcpTestSucceeded : True
```

### Test 2: Truy cập qua domain

Mở browser và vào:
```
http://editvideopro.online:8080
```

Nếu thấy trang login EditVideo Pro → **Thành công!** 🎉

---

## 🔍 Troubleshooting

### Lỗi: Connection refused

**Nguyên nhân:**
- FRP server chưa chạy
- Firewall block port

**Giải pháp:**
```bash
# Kiểm tra FRP server
systemctl status frps

# Kiểm tra port đang listen
netstat -tulpn | grep 7000
netstat -tulpn | grep 8080

# Restart service
systemctl restart frps
```

### Lỗi: Timeout khi truy cập domain

**Nguyên nhân:**
- DNS chưa trỏ đúng
- Firewall VPS chặn port 8080

**Giải pháp:**
```bash
# Kiểm tra DNS
dig editvideopro.online +short

# Kiểm tra firewall
ufw status
# hoặc
firewall-cmd --list-all
```

### Lỗi: FRP client không kết nối được

**Kiểm tra logs trên VPS:**
```bash
tail -f /var/log/frp/frps.log
```

**Kiểm tra logs trên Windows:**
```powershell
Receive-Job 1
```

---

## 📊 Các Commands Hữu Ích

```bash
# Start FRP server
systemctl start frps

# Stop FRP server
systemctl stop frps

# Restart FRP server
systemctl restart frps

# Xem status
systemctl status frps

# Xem logs realtime
journalctl -u frps -f

# Kiểm tra connections
netstat -an | grep 7000
```

---

## ✅ Checklist Hoàn Thành

- [ ] FRP Server đã cài đặt trên VPS
- [ ] File `frps.toml` đã cấu hình đúng
- [ ] Firewall đã mở ports 7000, 8080
- [ ] Systemd service đã enable và start
- [ ] DNS A record trỏ về IP VPS
- [ ] FRP logs hiện "started successfully"
- [ ] Test port 8080 từ bên ngoài thành công
- [ ] Truy cập http://editvideopro.online:8080 thành công

---

## 📞 Hỗ Trợ

Nếu gặp vấn đề, gửi cho tôi:
1. Output của: `systemctl status frps`
2. Logs: `tail -n 50 /var/log/frp/frps.log`
3. Firewall status: `ufw status` hoặc `firewall-cmd --list-all`
