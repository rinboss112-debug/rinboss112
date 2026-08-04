# RinBoss Marketplace Collector 2.0.1

Extension này độc lập với **RinBoss Amazon Collector 1.2**. Có thể cài cả hai trong
Chrome; chúng dùng tên và vùng lưu dữ liệu khác nhau nên không ghi đè kết quả của nhau.

## Cách dùng

1. Mở `chrome://extensions`, bật **Developer mode** và chọn **Load unpacked**.
2. Chọn thư mục `marketplace_collector` đã giải nén.
3. Chuẩn bị một file TXT, mỗi dòng là một ngách.
4. Chọn **Temu US**, mở `https://www.temu.com`, nhập TXT và chạy.
5. Với Temu, số lượt tương đương số lần cuộn/tải thêm kết quả.
6. Xuất CSV Temu; chuyển sang **Amazon**, mở `https://www.amazon.com`, đặt ZIP và chạy lại cùng TXT.
7. Xuất CSV Amazon và upload hai file vào `/temu-amazon-gap`.

CSV Temu giữ tiêu đề, ảnh, giá, link và tín hiệu bán hàng đang hiển thị như sold,
review, rating hoặc badge. Nếu Temu không hiển thị thì trường đó để trống.

Extension chỉ đọc nội dung đang hiển thị trong tab do người dùng chọn. Nó không đọc
mật khẩu/cookie/token, không gọi API riêng tư, không giải CAPTCHA, không đổi IP và
không che giấu trình duyệt. Khi website yêu cầu xác minh, phiên sẽ tự dừng.

Kết quả ghép chỉ là ứng viên. Luôn xác nhận đúng ảnh, mẫu, size, pack, thương hiệu,
quyền bán và toàn bộ chi phí trước khi mua hoặc đăng bán.
