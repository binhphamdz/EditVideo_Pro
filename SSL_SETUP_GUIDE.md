# Hướng dẫn cài SSL + bỏ port :8080

## 📋 Tổng quan
Script sẽ tự động:
- ✅ Cài Nginx làm reverse proxy
- ✅ Xin SSL certificate miễn phí từ Let's Encrypt
- ✅ Cấu hình HTTPS + HTTP→HTTPS redirect
- ✅ Mở port 80 và 443
- ✅ Tự động gia hạn SSL mỗi 90 ngày

Sau khi cài xong:
- **HTTP**: http://editvideopro.online → tự động redirect sang HTTPS
- **HTTPS**: https://editvideopro.online (không cần port :8080)

---

## 🚀 Các bước thực hiện

### Bước 1: Upload script lên VPS

**Trên Windows PowerShell:**
```powershell
# Copy script lên VPS
scp C:\Users\Binh\Desktop\EditVideo_Pro\install_nginx_ssl.sh root@160.25.81.240:/root/
```

**Nhập password VPS khi được hỏi**

---

### Bước 2: SSH vào VPS và chạy script

**SSH vào VPS:**
```powershell
ssh root@160.25.81.240
```

**Chạy script cài đặt:**
```bash
cd /root
chmod +x install_nginx_ssl.sh
sudo bash install_nginx_ssl.sh
```

**Script sẽ tự động:**
1. Cài Nginx
2. Cài Certbot
3. Mở port 80, 443
4. Cấu hình Nginx reverse proxy
5. Xin SSL certificate từ Let's Encrypt
6. Bật HTTPS + redirect

⏱️ **Thời gian**: Khoảng 2-3 phút

---

### Bước 3: Kiểm tra

**Sau khi script chạy xong, test:**

1. **Trên trình duyệt:**
   - Truy cập: https://editvideopro.online
   - Kiểm tra: ✅ Có icon ổ khóa (🔒) bên cạnh URL
   - Test: Upload file thử để đảm bảo hoạt động bình thường

2. **Trên PowerShell (Windows):**
```powershell
# Test HTTPS
Invoke-WebRequest -Uri "https://editvideopro.online/" -TimeoutSec 10

# Kết quả mong đợi: StatusCode: 200
```

---

## 🔧 Quản lý sau khi cài

### Xem logs Nginx
```bash
# Trên VPS
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Reload Nginx (sau khi sửa config)
```bash
sudo nginx -t                    # Test cấu hình
sudo systemctl reload nginx      # Reload nếu test OK
```

### Gia hạn SSL thủ công (không cần thiết, tự động rồi)
```bash
sudo certbot renew
```

### Kiểm tra SSL certificate
```bash
sudo certbot certificates
```

---

## 🏗️ Kiến trúc hệ thống sau khi cài SSL

```
Internet
    ↓
https://editvideopro.online (port 443)
    ↓
[VPS] Nginx (SSL termination)
    ↓
[VPS] FRP Server (port 8080)
    ↓
[VPS] FRP Tunnel
    ↓
[Windows] FRP Client
    ↓
[Windows] FastAPI Server (port 8000)
```

---

## ⚙️ Chi tiết cấu hình

### Nginx sẽ làm gì?
- **Port 80 (HTTP)**: Redirect tất cả request sang HTTPS
- **Port 443 (HTTPS)**: 
  - Nhận request từ browser
  - Decrypt SSL
  - Proxy sang FRP (port 8080)
  - FRP tunnel sang Windows server

### SSL Certificate
- **Nhà cung cấp**: Let's Encrypt (miễn phí)
- **Thời hạn**: 90 ngày
- **Tự động gia hạn**: Có (cron job)
- **Email nhận thông báo**: binhpvp2k3@gmail.com

---

## 🛠️ Troubleshooting

### Lỗi: Port 80 hoặc 443 đã được sử dụng
```bash
# Kiểm tra process đang dùng port
sudo lsof -i :80
sudo lsof -i :443

# Nếu có Apache hoặc service khác, stop nó
sudo systemctl stop apache2
```

### Lỗi: DNS chưa trỏ về VPS
```bash
# Test DNS
nslookup editvideopro.online

# Phải trả về: 160.25.81.240
```

### Lỗi: Certbot không thể verify domain
**Nguyên nhân**: DNS chưa propagate hoặc port 80 bị block

**Giải pháp**:
```bash
# Đợi 5-10 phút cho DNS propagate
# Kiểm tra lại
curl http://editvideopro.online
```

### Lỗi: HTTPS hoạt động nhưng upload file bị lỗi
**Nguyên nhân**: Timeout hoặc size limit

**Giải pháp**: Đã cấu hình sẵn trong script:
- `client_max_body_size 0;` - Không giới hạn size
- `proxy_*_timeout 300s;` - Timeout 5 phút

---

## 📞 Hỗ trợ

Nếu gặp lỗi, check:
1. **FRP client trên Windows**: Có đang chạy không?
   ```powershell
   # Trên Windows
   Get-Job
   ```

2. **FRP server trên VPS**: 
   ```bash
   sudo systemctl status frps
   sudo tail -f /var/log/frp/frps.log
   ```

3. **Nginx trên VPS**:
   ```bash
   sudo systemctl status nginx
   sudo tail -f /var/log/nginx/error.log
   ```

---

## 🎯 Kết quả cuối cùng

✅ Website: https://editvideopro.online (không cần port)
✅ SSL: Có icon ổ khóa 🔒
✅ Auto-redirect: HTTP → HTTPS
✅ Upload: Hoạt động bình thường
✅ SSL auto-renew: Mỗi 90 ngày

**Chúc mừng! Website của bạn đã có SSL và domain đẹp! 🎉**
