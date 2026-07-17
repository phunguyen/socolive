# socolive-crawler

Cào lịch trận Socolive → trích link HLS (`.m3u8`) thật → sinh `socolive.m3u`,
tự chạy 5 phút/lần bằng GitHub Actions và publish qua GitHub Pages.

## Chạy local

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python main.py                 # → output/socolive.m3u  (+ index.html)
SOCOLIVE_HEADLESS=0 python main.py   # xem trình duyệt (debug)
```

Mở `output/socolive.m3u` bằng VLC / IINA / OTT Navigator.

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `SOCOLIVE_BASE` | (đọc `base.txt`) | Danh sách domain, phân tách bằng dấu phẩy. Ưu tiên hơn `base.txt`. |
| `SOCOLIVE_MAX` | `40` | Số trận vào chi tiết tối đa. |
| `SOCOLIVE_OUT` | `output` | Thư mục xuất (CI dùng `public`). |
| `SOCOLIVE_HEADLESS` | `1` | `0` = mở trình duyệt. |

## Deploy lên GitHub + Pages

1. Tạo repo **public** (Actions không giới hạn phút cho repo public; cứ 5 phút/lần
   sẽ vượt quota free của repo private).
2. Push toàn bộ code lên nhánh `main`.
3. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. **Settings → Actions → General → Workflow permissions → Read and write**.
5. Vào tab **Actions**, chạy workflow "Crawl & publish M3U" một lần (hoặc đợi cron).

Playlist sẽ ở: `https://<user>.github.io/<repo>/socolive.m3u`
(trang liệt kê: `https://<user>.github.io/<repo>/`).

> Cron `*/5` là mốc **tối thiểu** của GitHub — lúc tải cao có thể trễ/gộp run.
> Link `.m3u8` có `auth_key` hết hạn sau ~vài giờ, nên chạy định kỳ là cần thiết.

## Khi domain đổi (cập nhật nhanh)

Domain Socolive xoay liên tục. Crawler đã:
- thử lần lượt các domain trong `base.txt` cho tới khi có domain vào được;
- tự đi theo redirect tới domain sống.

Chỉ khi **tất cả** domain trong `base.txt` chết mới cần sửa tay:

1. Trên GitHub, mở `base.txt` → nút bút chì (Edit).
2. Thêm domain mới vào **dòng đầu**, commit.
3. Workflow có trigger `push` trên `base.txt` → **chạy lại ngay lập tức**, không cần đợi cron.

Không cần đụng Secrets/Variables — `base.txt` là nguồn cấu hình duy nhất.
