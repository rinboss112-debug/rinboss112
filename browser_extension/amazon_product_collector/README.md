# RinBoss Amazon Collector 1.2.1

Chrome Extension Manifest V3 đọc các thẻ sản phẩm đang hiển thị trên trang kết quả
Amazon. Phiên hàng loạt chạy trong tab Amazon do người dùng chọn và vẫn tiếp tục khi
popup extension đóng.

## Cài đặt

1. Mở `chrome://extensions`.
2. Bật **Developer mode**.
3. Chọn **Load unpacked**.
4. Chọn đúng thư mục `amazon_product_collector` đã giải nén.
5. Ghim **RinBoss Amazon Collector** lên thanh công cụ.

## Chạy nhiều ngách từ TXT

1. Tạo file `.txt`, mỗi dòng là một ngách, ví dụ:

   ```text
   Snack Food Gifts
   acne pimple patches
   kitchen organizer
   ```

2. Mở `https://www.amazon.com` và đặt ZIP giao hàng cần kiểm tra.
3. Mở extension, bấm **Nhập TXT** hoặc dán danh sách vào ô.
4. Chọn từ 1–10 trang/ngách và thời gian nghỉ từ 8–120 giây.
5. Bấm **Bắt đầu cào danh sách**. Không đóng tab Amazon được extension sử dụng.
6. Có thể đóng popup; mở lại để xem tiến độ hoặc bấm **Dừng sau trang hiện tại**.
7. Khi hoàn tất, lọc theo tiêu đề/ngách/ASIN, khoảng giá hoặc điều kiện giao hàng.
8. Bấm **CSV đã lọc** để chỉ tải các dòng phù hợp, hoặc **CSV toàn bộ** để tải dữ liệu gốc.

Extension tự bỏ dòng trống, gộp ngách trùng, chỉ chạy 50 ngách đầu và gộp sản phẩm
theo ASIN. Nếu một trang không còn thẻ kết quả, extension chuyển sang ngách tiếp theo.
Bộ lọc giá không xóa sản phẩm đã lưu nên có thể đổi khoảng giá và xuất lại nhiều lần.
Tiêu đề được lấy từ liên kết sản phẩm khớp ASIN; khi Amazon đặt brand ở dòng đầu,
extension ưu tiên dòng mô tả sản phẩm thay vì ghi nhầm brand vào cột `title`.

## Quyền sử dụng

- `amazon.com`: mở trang tìm kiếm và đọc các thẻ sản phẩm trong tab đang chạy.
- `tabs` và `scripting`: chuyển trang rồi chạy bộ đọc sau khi trang tải xong.
- `storage` và `unlimitedStorage`: lưu hàng đợi, thiết lập và sản phẩm ngay trên máy khi danh sách lớn.
- `alarms`: giữ khoảng nghỉ giữa các trang khi popup đã đóng.

Extension không đọc mật khẩu, không giải CAPTCHA, không đổi IP và không che giấu trình
duyệt. Khi Amazon hiện CAPTCHA/Robot Check, phiên tự dừng. Hãy xử lý thủ công, nghỉ một
thời gian và chỉ chạy lại khi trang kết quả hoạt động bình thường.
