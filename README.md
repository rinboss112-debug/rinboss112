# Amazon Product Scraper

Web app Streamlit tiếng Việt để chạy tuần tự nhiều ngách Amazon, theo dõi log trực tiếp, lưu CSV sau từng ngách và đồng bộ kết quả lên Google Drive.

> Workspace ban đầu không có `amazon_scraper.py` gốc. Project này dùng scraper `requests` + Beautiful Soup, tách riêng khỏi giao diện để có thể thay backend sau này.

## Tính năng

- Nhập ZIP Code, tải TXT hoặc nhập ngách trực tiếp; tự bỏ dòng trùng.
- Xem trước danh sách ngách trước khi chạy.
- Lọc theo giá, số trang, số sản phẩm, delivery và tiền tệ USD.
- Worker nền, log/progress trực tiếp, ETA và dừng sau ngách hiện tại.
- Mỗi phiên có `run_id` và thư mục riêng, không ghi chung giữa các phiên.
- Lưu CSV riêng từng ngách và cập nhật `all_products.csv` ngay lập tức.
- Chuẩn hóa link sản phẩm thành `https://www.amazon.com/dp/ASIN` và bỏ tham số tracking.
- Lấy link ảnh gốc, tự bỏ mã resize Amazon như `._AC_UL320_`.
- Liệt kê và lọc riêng tốc độ giao hàng `Today`, `Tomorrow`, `Overnight`.
- Đồng bộ CSV lên Google Drive ngay sau từng ngách.
- Cuối phiên tạo `manifest.json` và ZIP, đồng bộ cả hai lên Drive.
- Lịch sử phiên chạy, biểu đồ theo ngách/giá/vận chuyển.
- Chạy lại riêng các ngách lỗi.
- Tải CSV đang lọc, CSV gộp hoặc toàn bộ phiên dạng ZIP.
- Mật khẩu bảo vệ app tùy chọn.
- Thông báo hoàn tất qua Telegram và email tùy chọn.
- Kiểm tra kết nối Amazon và Google Drive ngay trên sidebar.
- Nếu CSV bị Excel khóa, tự chuyển sang tên timestamp.

## Cài đặt local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Thiết lập Google Drive cho Gmail cá nhân

App sử dụng OAuth của chính tài khoản Google, không dùng service account. Cách này cho phép file được tạo trong My Drive của bạn và tránh vấn đề service account không có dung lượng sở hữu file.

### 1. Tạo OAuth client trên Google Cloud

1. Mở [Google Cloud Console](https://console.cloud.google.com/).
2. Tạo hoặc chọn một project.
3. Vào **APIs & Services → Library**.
4. Tìm **Google Drive API** và nhấn **Enable**.
5. Vào **Google Auth Platform → Branding/Audience** và cấu hình OAuth consent screen.
6. Nếu app ở chế độ Testing, thêm địa chỉ Gmail của bạn vào **Test users**.
7. Vào **APIs & Services → Credentials**.
8. Chọn **Create credentials → OAuth client ID**.
9. Chọn loại **Desktop app**.
10. Tải file JSON và đổi tên thành `client_secret.json` trong thư mục project.

Không commit `client_secret.json` lên GitHub; file này đã được chặn trong `.gitignore`.

### 2. Tạo refresh token

Sau khi cài dependencies, chạy:

```powershell
python setup_google_drive.py --client-secrets client_secret.json
```

Trình duyệt sẽ mở trang Google. Đăng nhập tài khoản Drive, chấp thuận quyền, rồi quay lại terminal. Script tạo file:

```text
drive_secrets.toml
```

File này chứa khóa bí mật và cũng đã được chặn trong `.gitignore`.

### 3. Thêm vào Streamlit Community Cloud

1. Mở app tại `share.streamlit.io`.
2. Chọn **Manage app → Settings → Secrets**.
3. Mở `drive_secrets.toml`, sao chép toàn bộ nội dung vào ô Secrets.
4. Nếu muốn khóa app, thêm phía trên:

```toml
[app]
password = "MAT_KHAU_CUA_BAN"
```

5. Nhấn **Save** và reboot app nếu cần.

Sau khi app chạy lại, sidebar sẽ hiện **Google Drive đã cấu hình**. Nhấn **Kiểm tra Google Drive**; app tự tạo thư mục `Amazon Product Scraper` trong My Drive.

Nếu Google báo `invalid_grant`, refresh token đã hết hiệu lực hoặc bị thu hồi; chạy lại `setup_google_drive.py` và cập nhật Secrets.

## Secrets đầy đủ

File mẫu nằm tại `.streamlit/secrets.example.toml`. Chỉ sao chép những phần bạn cần. Không commit `.streamlit/secrets.toml`, `drive_secrets.toml`, OAuth JSON, refresh token, bot token hoặc mật khẩu email.

### Telegram tùy chọn

```toml
[telegram]
bot_token = "BOT_TOKEN"
chat_id = "CHAT_ID"
```

### Email tùy chọn

```toml
[email]
host = "smtp.gmail.com"
port = 465
use_ssl = true
username = "you@gmail.com"
password = "GOOGLE_APP_PASSWORD"
sender = "you@gmail.com"
recipient = "you@gmail.com"
```

Với Gmail, dùng App Password thay vì mật khẩu tài khoản chính.

## Cấu trúc dữ liệu

```text
output/
└── runs/
    └── run_20260720_153000_a1b2c3/
        ├── halloween_outdoor_decorations.csv
        ├── kitchen_organizer.csv
        ├── all_products.csv
        ├── errors.log
        ├── manifest.json
        └── run_20260720_153000_a1b2c3.zip
```

Streamlit Community Cloud không đảm bảo lưu bền file local. Khi Drive được cấu hình, mỗi phiên sẽ có một thư mục tương ứng trên Drive và CSV được tải lên ngay sau từng ngách.

## Chạy CLI

```powershell
python amazon_scraper.py --niches niches.txt --zip-code 92704 --max-pages 2 --max-products 50 --only-usd
```

## Quy trình Git an toàn

```text
main → bản ổn định đang chạy thật
dev  → bản nâng cấp để kiểm thử
```

Deploy app thử nghiệm từ branch `dev`. Chỉ merge sang `main` sau khi kiểm tra Amazon, Drive, ZIP và thông báo.

## Lưu ý Amazon

Amazon có thể thay đổi HTML, giới hạn lưu lượng hoặc yêu cầu CAPTCHA, đặc biệt với IP cloud. Scraper ghi lỗi theo từng ngách và tiếp tục danh sách. Hãy tuân thủ điều khoản sử dụng và quy định áp dụng cho dữ liệu bạn thu thập.
