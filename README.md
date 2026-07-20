# Amazon Product Scraper

Web app Streamlit tiếng Việt để chạy tuần tự nhiều ngách Amazon, theo dõi log và tiến trình trực tiếp, lưu ngay CSV của từng ngách và cập nhật file gộp sau mỗi ngách.

> Lưu ý: workspace được cung cấp không có file `amazon_scraper.py` gốc. Vì vậy project này chứa một scraper dùng `requests` + Beautiful Soup được tách biệt khỏi giao diện. Nếu bạn có logic scraper cũ (ví dụ Playwright và `browser_profile/`), có thể giữ phần phân tích sản phẩm cũ và chỉ cần duy trì giao diện hàm `scrape_keyword(...)` hiện có.

## Tính năng

- Nhập ZIP Code, tải file TXT hoặc nhập ngách trực tiếp.
- Giới hạn giá, số trang và số sản phẩm cho từng ngách.
- Tùy chọn chỉ lấy sản phẩm giao được đến ZIP hoặc có giá USD.
- Chạy trong worker riêng nên giao diện vẫn cập nhật mỗi giây.
- Nút dừng an toàn sau khi hoàn tất và lưu ngách hiện tại.
- Một lỗi ngách không làm dừng toàn bộ danh sách; chi tiết được ghi vào `output/errors.log`.
- Lưu riêng từng ngách và cập nhật `output/all_products.csv` ngay sau ngách đó.
- Nếu CSV đang mở trong Excel, tự chuyển sang tên có timestamp và hiện cảnh báo.
- Bộ lọc theo ngách, khoảng giá, free shipping, fast shipping và khả năng giao hàng.
- Bảng có ảnh, giá, đánh giá, trạng thái vận chuyển và link mở Amazon.
- Tải CSV đang lọc hoặc toàn bộ kết quả gộp.

## Cài đặt trên Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Chạy web app

```powershell
python -m streamlit run app.py
```

Streamlit sẽ mở địa chỉ mặc định `http://localhost:8501`.

## Chạy bằng CLI (không dùng `input()`)

```powershell
python amazon_scraper.py --niches niches.txt --zip-code 92704 --max-pages 2 --max-products 50 --only-usd
```

Thêm `--only-deliverable` để chỉ lấy sản phẩm được đánh dấu giao được, hoặc `--timestamp-existing` để không ghi đè file cũ.

## Cấu trúc project

```text
amazon_streamlit_scraper/
├── .streamlit/
│   └── config.toml
├── output/
│   └── .gitkeep
├── .gitignore
├── amazon_scraper.py
├── app.py
├── niches.txt
├── README.md
└── requirements.txt
```

Sau khi chạy, `output/` có dạng:

```text
output/
├── halloween_outdoor_decorations.csv
├── kitchen_organizer.csv
├── pet_grooming_tools.csv
├── all_products.csv
└── errors.log                 # chỉ xuất hiện khi một ngách lỗi
```

## Quy tắc dữ liệu và file

- `slugify_filename()` chuyển chữ thường, bỏ dấu, đổi nhóm ký tự không an toàn thành `_`, xử lý tên thiết bị Windows như `CON`, `NUL`, `COM1`.
- CSV dùng UTF-8 có BOM (`utf-8-sig`) để Excel hiển thị tiếng Việt đúng.
- Ghi CSV qua file tạm rồi thay thế đích để giảm nguy cơ file dở dang.
- Trong chế độ ghi đè, nếu file đích bị Excel khóa, bản mới được lưu tự động với timestamp.
- `all_products.csv` đại diện cho kết quả gộp của phiên chạy hiện tại. Trong chế độ timestamp, nếu file gộp cũ tồn tại thì phiên mới dùng một file gộp có timestamp.

## Lưu ý khi cào Amazon

Amazon có thể thay đổi HTML, giới hạn lưu lượng hoặc yêu cầu CAPTCHA. Khi gặp xác minh tự động, scraper ghi lỗi cho ngách và tiếp tục ngách kế tiếp. Hãy chạy với số trang hợp lý, tuân thủ điều khoản sử dụng và các quy định áp dụng cho dữ liệu bạn thu thập.
