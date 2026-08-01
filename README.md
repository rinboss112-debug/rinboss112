# Amazon Product Scraper

Web app Streamlit tiếng Việt để chạy tuần tự nhiều ngách Amazon, theo dõi log trực tiếp, lưu CSV sau từng ngách và đồng bộ kết quả lên Google Drive.

> Workspace ban đầu không có `amazon_scraper.py` gốc. Project này dùng scraper `requests` + Beautiful Soup, tách riêng khỏi giao diện để có thể thay backend sau này.

## Tính năng

- Nhập ZIP Code, tải TXT hoặc nhập ngách trực tiếp; tự bỏ dòng trùng.
- Xem trước danh sách ngách trước khi chạy.
- Cào rộng mọi thẻ sản phẩm đọc được trong số trang/sản phẩm đã chọn; không loại
  trước theo giá, tiền tệ, brand, Prime, Fresh hoặc điều kiện giao hàng.
- Worker nền, log/progress trực tiếp, ETA và dừng sau ngách hiện tại.
- Mỗi phiên có `run_id` và thư mục riêng, không ghi chung giữa các phiên.
- Lưu CSV riêng từng ngách và cập nhật file gộp theo ngách đầu tiên, ví dụ `snack_all_products.csv`, ngay lập tức.
- Chuẩn hóa link sản phẩm thành `https://www.amazon.com/dp/ASIN` và bỏ tham số tracking.
- Lấy link ảnh gốc, tự bỏ mã resize Amazon như `._AC_UL320_`.
- Chỉ đọc dữ liệu ngay trên các thẻ của trang kết quả Amazon, không mở trang
  chi tiết sản phẩm và không lấy biến thể; nhờ vậy số request thấp hơn.
- Giữ cả sản phẩm thiếu giá hoặc thiếu thông tin ship; trường chưa đọc được được
  ghi rõ để có thể lọc lại trên giao diện.
- Bảng và CSV chỉ hiển thị cột thời gian giao, ví dụ `Today 2 PM - 6 PM`,
  `Tomorrow, Aug 1`, `Overnight 4 AM - 6 AM` hoặc
  `Sun, Aug 2 | Thu, Aug 6`. Cột thông tin ship dài được giữ nội bộ để lọc
  Prime/Fresh/free shipping nhưng không xuất ra bảng hoặc CSV.
- Bộ lọc kết quả gồm tên sản phẩm, ngách, tiền tệ, khoảng giá, đánh giá, Prime,
  Fresh, free/fast shipping, trạng thái giao hàng và thời gian Today/Tomorrow/Overnight.
- Có hai nút tải riêng: CSV đúng phần đang lọc và CSV toàn bộ dữ liệu gốc.
- Có bộ đọc dự phòng khi Amazon đổi class HTML giao hàng; thông tin ship được
  lấy trực tiếp từ từng thẻ kết quả và sản phẩm thiếu ship vẫn được giữ.
- Đồng bộ CSV lên Google Drive ngay sau từng ngách.
- Cuối phiên tạo `manifest.json` và ZIP, đồng bộ cả hai lên Drive.
- Lịch sử phiên chạy, biểu đồ theo ngách/giá/vận chuyển.
- Chạy lại riêng các ngách lỗi.
- Tải CSV đang lọc, CSV gộp hoặc toàn bộ phiên dạng ZIP.
- Mật khẩu bảo vệ app tùy chọn.
- Trang `/admin` ẩn để thêm/xóa/khóa người dùng, khóa khẩn cấp việc cào và duyệt ngách.
- Mỗi ngách hoàn tất được đưa vào danh sách chờ duyệt; chỉ ngách admin công khai mới hiện trên trang chủ.
- Admin có thể tạo category và page tùy chỉnh; page công khai tự xuất hiện trên menu trang web theo đúng category.
- Giao diện RinBoss Commerce dùng bảng màu bán hàng cam đất, kem ấm, xanh navy và xanh lá; đồng bộ giữa trang cào, page dữ liệu và `/admin`.
- Mỗi page có bảng sửa trực tiếp như Excel: sửa ô, thêm/xóa hàng, thêm/xóa/đổi tên cột và nhập CSV/XLSX.
- Có thể gắn các ngách/file đã cào vào page bất kỳ để người dùng mở nhanh dữ liệu trên Google Drive.
- Category, page và toàn bộ bảng tùy chỉnh được lưu trong `custom_pages.json` trên Google Drive.
- Quota riêng theo mã truy cập: lượt/ngày, ngách/lượt, trang/ngách và sản phẩm/ngách.
- Đồng bộ chính sách truy cập dạng băm lên Google Drive; không lưu mã người dùng dạng rõ.
- Thông báo hoàn tất qua Telegram và email tùy chọn.
- Kiểm tra kết nối Amazon và Google Drive ngay trên sidebar.
- Nếu CSV bị Excel khóa, tự chuyển sang tên timestamp.
- Trang /tiktok-shop-us dành cho admin để chuẩn bị sản phẩm và xuất Excel TikTok Shop US.
- Tự tính giá bán theo công thức (giá gốc × 2 + 12) ÷ 0.8, đồng thời cho phép sửa giá cuối cùng.
- Có bảng kiểm tra SKU, tên, mô tả, brand, ảnh, tồn kho, cân nặng, kích thước và GTIN/UPC trước khi xuất.
- Hỗ trợ tải template XLSX chính thức của từng category TikTok, tự gợi ý ánh xạ cột và điền dữ liệu mà không thêm hoặc xóa cột của template.

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

## Thiết lập trang `/admin`

Thêm phần sau vào Streamlit **App settings → Secrets**:

```toml
[admin]
password = "MAT_KHAU_ADMIN_RAT_MANH"
enable_access_control = true
```

Sau khi Save và reboot app, mở:

```text
https://TEN-APP-CUA-BAN.streamlit.app/admin
```

Đăng nhập bằng `admin.password`, sau đó:

1. Thêm người dùng và tạo mã truy cập riêng.
2. Đặt số lượt/người/ngày, số ngách/lượt, trang/ngách và sản phẩm/ngách.
3. Bật **Cho phép người dùng bắt đầu cào**.
4. Gửi riêng mã truy cập cho từng người.

Admin có thể khóa/mở khóa, xóa người dùng, đặt lại lượt hôm nay hoặc đóng toàn bộ quyền bắt đầu phiên mới. Admin cũng có thể công khai, ẩn hoặc xóa ngách trong mục **Duyệt ngách đã cào**. Ngách đã công khai xuất hiện trên trang chủ cho thành viên xem. Nhấn **Quét các phiên cũ từ Google Drive** một lần để nhập cả những ngách đã cào trước khi tính năng danh mục được thêm vào.

Trong mục **Category, page và bảng dữ liệu**:

1. Tạo category để nhóm nội dung, ví dụ `Snack`, `Nhà bếp`, `Thú cưng`.
2. Tạo page và chọn category tương ứng.
3. Nhập file CSV/XLSX hoặc sửa bảng trực tiếp; nút `+` trong bảng dùng để thêm hàng.
4. Mở **Quản lý cột** để thêm, đổi tên hoặc xóa cột.
5. Chọn các ngách đã cào để gắn link dữ liệu Google Drive vào page.
6. Bật **Công khai page trên menu trang web** và nhấn **Lưu page và bảng dữ liệu**.

Page công khai có URL riêng và tự xuất hiện trong menu phía trên, được nhóm theo category. Người xem có thể tìm trong bảng và tải CSV nhưng không thể chỉnh sửa; chỉ admin mới có quyền sửa.

Khi Google Drive đã cấu hình, chính sách nằm trong `access_control.json`, danh mục duyệt nằm trong `niche_catalog.json`, còn page/category nằm trong `custom_pages.json` trên Drive; mã truy cập chỉ được lưu dưới dạng băm có salt. Không chia sẻ mật khẩu admin.

Nếu `enable_access_control = false` hoặc không khai báo, app tiếp tục dùng mật khẩu `[app]` cũ để tương thích.

## Xuất Excel cho TikTok Shop US

Mở đường dẫn /tiktok-shop-us trên app và đăng nhập bằng mật khẩu admin.

1. Tải CSV/XLSX kết quả scraper hoặc dùng kết quả của phiên cào đang mở.
2. Bổ sung mô tả, brand, tồn kho, thông tin đóng gói, GTIN/UPC và biến thể.
3. Kiểm tra giá tính tự động theo công thức (giá gốc × 2 + 12) ÷ 0.8.
4. Tải bảng chuẩn bị nội bộ để kiểm tra.
5. Trong TikTok Seller Center, chọn đúng category và tải template Excel chính thức.
6. Upload template đó vào app, kiểm tra sheet, dòng tiêu đề và ánh xạ cột.
7. Tạo rồi tải file TikTok đã điền.

Template TikTok thay đổi theo category nên app không tự tạo một template chung để
upload thẳng. Không dùng Amazon để giao trực tiếp đơn TikTok, không dùng hình ảnh
hoặc thương hiệu khi chưa có quyền, và không chọn No brand cho sản phẩm rõ ràng
có thương hiệu.

## Bổ sung 5 ảnh cho CSV Amazon

Mở đường dẫn `/amazon-images` và đăng nhập bằng mật khẩu admin:

1. Tải lên CSV có cột `asin` hoặc `product_url`.
2. Chọn lô nhỏ, khuyến nghị 10 sản phẩm và nghỉ ít nhất 2 giây giữa mỗi sản phẩm.
3. Nhấn **Lấy tối đa 5 ảnh**.
4. Tải CSV mới xuống sau mỗi lô để giữ tiến độ.
5. Có thể tải chính file mới đó lên và tiếp tục lô kế tiếp.

Tool giữ nguyên các cột cũ và thêm `image_url_1` đến `image_url_5` cùng cột
`image_gallery_status`. Link ảnh được chuẩn hóa về ảnh gốc, bỏ các đoạn resize như
`._AC_UL320_`. Nếu sản phẩm có ít hơn 5 ảnh thì trạng thái là `partial`; nếu Amazon
trả CAPTCHA, HTTP 429 hoặc 503 thì lô dừng sớm để hạn chế chặn kết nối.

## Giới hạn khi cào Amazon trên Streamlit Cloud

Thông tin giao hàng phụ thuộc ZIP, thời điểm, cookie và phiên Amazon. Streamlit
Cloud dùng IP máy chủ dùng chung, không dùng phiên Chrome trên máy của người dùng.
Nếu Amazon trả `Robot Check`, `Sorry! Something went wrong!`, HTTP 429/503 hoặc
trang trung gian không có ASIN, app sẽ báo lỗi chẩn đoán và dừng các ngách còn lại
thay vì ghi hàng loạt CSV rỗng.

Khi Amazon trả đúng thẻ kết quả, cột `delivery_options` chỉ chứa các mốc giao
hàng, giữ tất cả mốc đọc được theo đúng thứ tự:

- `Today 2 PM - 6 PM`
- `Tomorrow, August 1`
- `Overnight 7 AM - 11 AM`
- `Sun, Aug 2`
- `Tomorrow, Aug 1 | Wed, Aug 5`

Để lấy ngày giao ổn định hơn, nên chạy scraper từ kết nối tại Mỹ hoặc một worker
cục bộ có phiên trình duyệt và ZIP phù hợp, sau đó đồng bộ CSV lên Google Drive.
Phần Streamlit Cloud phù hợp hơn cho quản lý, duyệt và tải dữ liệu đã đồng bộ.

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
├── access_control.json
├── niche_catalog.json
├── custom_pages.json
└── runs/
    └── run_20260720_153000_a1b2c3/
        ├── halloween_outdoor_decorations.csv
        ├── kitchen_organizer.csv
        ├── halloween_outdoor_decorations_all_products.csv
        ├── errors.log
        ├── manifest.json
        └── halloween_outdoor_decorations_run_20260720_153000_a1b2c3.zip
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
feature/tiktok-shop-us-export → bản thử xuất Excel TikTok Shop US
```

Deploy app thử nghiệm từ branch `dev`. Chỉ merge sang `main` sau khi kiểm tra Amazon, Drive, ZIP và thông báo.

## Lưu ý Amazon

Amazon có thể thay đổi HTML, giới hạn lưu lượng hoặc yêu cầu CAPTCHA, đặc biệt với IP cloud. Scraper ghi lỗi theo từng ngách và tiếp tục danh sách. Hãy tuân thủ điều khoản sử dụng và quy định áp dụng cho dữ liệu bạn thu thập.
