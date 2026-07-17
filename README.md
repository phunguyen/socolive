# socolive-crawler

Lấy danh sách trận **đang trực tiếp** trên Socolive + link stream HLS (`.m3u8`),
sinh `socolive.m3u`, chạy định kỳ bằng GitHub Actions và publish qua GitHub Pages.

## Cách hoạt động

Các frontend web của Socolive (socolivef.cv, socoliveaus.co, …) đổi domain liên
tục và đứng sau Cloudflare — Cloudflare chặn IP datacenter (GitHub Actions) ở
trang xem. Nhưng tất cả đều đọc từ **một API JSON tĩnh trên CDN cố định**:

```
https://json.vnres.co/all_live_rooms.json         # danh sách trận + phòng đang live (JSONP)
https://json.vnres.co/room/<roomNum>/detail.json  # stream URL của phòng đó
```

Nên `main.py` gọi thẳng API bằng HTTP (pure stdlib, **không cần trình duyệt**):
nhanh, không dính bot-challenge, và không còn phải lo domain xoay.

## Chạy local

```bash
python3 main.py            # → output/socolive.m3u  (+ index.html)
```

Không cần cài gì (chỉ dùng thư viện chuẩn của Python 3). Mở `output/socolive.m3u`
bằng VLC / IINA / OTT Navigator.

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `SOCOLIVE_API` | `https://json.vnres.co` | Host API JSON. Đổi nếu CDN này chết. |
| `SOCOLIVE_REF` | `https://socoliveaus.co/` | Referer ghi vào m3u (pull host check Referer). |
| `SOCOLIVE_MAX` | `150` | Số phòng lấy stream tối đa. |
| `SOCOLIVE_OUT` | `output` | Thư mục xuất (CI dùng `public`). |
| `SOCOLIVE_INSECURE` | – | `1` = bỏ verify TLS (chỉ dùng khi máy local có proxy MITM). |

## Deploy lên GitHub + Pages

1. Repo **public** (Actions free không giới hạn phút).
2. Push code lên `main`.
3. **Settings → Pages → Source: GitHub Actions**.
4. **Settings → Actions → General → Workflow permissions → Read and write**.
5. Tab **Actions** → chạy workflow một lần (hoặc đợi cron).

Playlist: `https://<user>.github.io/<repo>/socolive.m3u`

> Cron `*/5` của GitHub là best-effort (hay delay/skip). Muốn đúng 5 phút thì
> dùng cron ngoài (cron-job.org) gọi API `workflow_dispatch` — xem bên dưới.

## Chạy đúng 5 phút bằng external trigger

GitHub scheduled cron không đảm bảo đúng giờ. Cách chắc ăn: cron-job.org POST tới
`https://api.github.com/repos/<user>/<repo>/actions/workflows/crawl.yml/dispatches`
mỗi 5 phút, body `{"ref":"main"}`, header `Authorization: Bearer <token>`
(fine-grained PAT, quyền *Actions: Read and write* trên repo này).

## Cảnh báo tự động

- **API chết/chặn** → job fail (exit 1) → GitHub gửi email. Khi fail, m3u cũ
  **không bị ghi đè** (giữ playlist gần nhất). Nếu `json.vnres.co` chết hẳn, đổi
  `SOCOLIVE_API` sang host mới trong `crawl.yml`.
- **Hết 60 ngày** → `keepalive.yml` tự commit hàng tuần để scheduled workflow
  không bị GitHub tự tắt.

> 0 trận đang live **không** phải lỗi (exit 0) — chỉ là hiện không có trận nào phát.
> Link `.m3u8` có `auth_key`/`txSecret` hết hạn sau ~vài giờ nên cần chạy định kỳ.
