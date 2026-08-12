# RinBoss Product Image Collector 1.1.0

Extension riêng để bổ sung ảnh gallery cho CSV Amazon hoặc Temu bằng trình duyệt của người dùng.

## Cách sử dụng

1. Tải ZIP từ trang `/image-extension`, giải nén và cài bằng **Load unpacked** tại `chrome://extensions`.
2. Mở extension và chọn một trong hai cách nhập:
   - dán trực tiếp 1–10 link sản phẩm, mỗi dòng một link, rồi bấm **Nạp danh sách link**; hoặc
   - chọn CSV có một trong các cột `product_url`, `amazon_url`, `temu_url`, `url`, `link`; CSV Amazon cũng có thể chỉ cần cột `asin`.
3. Chọn số ảnh (mặc định 5), thời gian nghỉ rồi bấm **Bắt đầu lấy ảnh**. Nên chạy 3–10 link và nghỉ 8–15 giây giữa sản phẩm.
4. Extension mở một tab nền và lần lượt đọc từng trang sản phẩm. Có thể đóng popup; tiến trình vẫn tiếp tục.
5. Khi hoàn tất, bấm **Tải CSV có ảnh**. File giữ nguyên cột cũ và thêm `image_url_1...`, `image_gallery_count`, `image_gallery_status`.

Extension không đọc cookie/token/mật khẩu, không vượt CAPTCHA, không đổi IP và không che giấu trình duyệt. Nếu Amazon hoặc Temu yêu cầu xác minh, phiên tự dừng và giữ tab bị chặn để người dùng kiểm tra.
