# Đóng góp cho Vision Bot

Cảm ơn bạn đã quan tâm đến việc đóng góp cho dự án Vision Bot! Sự tham gia của bạn sẽ giúp dự án ngày càng hoàn thiện hơn.

## Quy trình đóng góp

1. **Fork** repository này về tài khoản GitHub của bạn.
2. **Clone** repository đã fork về máy.
3. Tạo nhánh (branch) mới cho tính năng hoặc sửa lỗi của bạn (`git checkout -b feature/tinh-nang-moi`).
4. **Commit** các thay đổi (`git commit -m 'Thêm tính năng X'`).
5. **Push** lên nhánh đã tạo (`git push origin feature/tinh-nang-moi`).
6. Mở **Pull Request** trên repository gốc.

## Thiết lập môi trường phát triển

1. Đảm bảo bạn đã cài đặt Python 3.8 trở lên.
2. Cài đặt các thư viện yêu cầu:
   ```bash
   pip install -r requirements.txt
   ```
3. Cài đặt thư viện hỗ trợ kiểm tra code (Linting):
   ```bash
   pip install ruff
   ```

## Tiêu chuẩn Code (Coding Standards)

- Dự án sử dụng `ruff` để kiểm tra chuẩn định dạng và chất lượng code. Trước khi commit, vui lòng chạy lệnh sau ở thư mục gốc:
  ```bash
  ruff check .
  ```
- Nếu có lỗi, hãy sửa chúng trước khi push code lên. (Bạn có thể cấu hình file `ruff.toml` để xem các luật được bỏ qua).

## Kiểm thử (Testing)

Dự án có độ phủ test khá tốt. Bạn hãy đảm bảo việc chạy qua toàn bộ Unit Test trước khi mở Pull Request:
```bash
python -m pytest tests/
```
Nếu bạn bổ sung thêm chức năng, vui lòng viết kèm Unit Test trong thư mục `tests/`.

Cảm ơn sự đóng góp của bạn!
