# socolive-crawler

Lấy danh sách trận **đang trực tiếp** trên Socolive + link stream HLS (`.m3u8`),
sinh `socolive.m3u`, chạy định kỳ trên máy (launchd) và publish lên GitHub Pages.

## Cách hoạt động

Các frontend web của Socolive đổi domain liên tục và đứng sau Cloudflare. Nhưng
tất cả đọc từ **một API JSON tĩnh trên CDN cố định**:

```
https://json.vnres.co/all_live_rooms.json         # trận + phòng đang live (JSONP)
https://json.vnres.co/room/<roomNum>/detail.json  # stream URL của phòng đó
```

`main.py` gọi thẳng API bằng HTTP (pure stdlib, **không cần trình duyệt**).

> ⚠️ **Vì sao phải chạy local, không dùng GitHub Actions:** `json.vnres.co` chặn
> theo **quốc gia** (Cloudflare error 1009) — chỉ cho IP trong khu vực (VN). Runner
> GitHub (IP Mỹ) và cả Cloudflare Worker đều bị chặn. Máy bạn ở VN thì gọi được.
> Nên crawl chạy trên Mac; GitHub chỉ dùng để **host** file qua Pages.

## Chạy thử

```bash
python3 main.py            # → output/socolive.m3u  (+ index.html)
```

Không cần cài gì (chỉ thư viện chuẩn Python 3). Mở `output/socolive.m3u` bằng
VLC / IINA / OTT Navigator.

## Cài đặt chạy tự động (local + GitHub Pages)

**1. Tạo nhánh `pages` + worktree (chạy 1 lần):**
```bash
bash setup-local.sh
```

**2. Bật GitHub Pages từ nhánh `pages`:**
Settings → Pages → Source: **Deploy from a branch** → Branch: **`pages`** / **`/ (root)`**.

**3. Chạy thử deploy 1 lần:**
```bash
bash deploy.sh          # crawl → push lên nhánh pages
```
→ mở `https://<user>.github.io/<repo>/socolive.m3u`

**4. Cài launchd chạy mỗi 5 phút:**
```bash
cp com.socolive.crawler.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.socolive.crawler.plist
```
Gỡ: `launchctl unload ~/Library/LaunchAgents/com.socolive.crawler.plist`
Log chạy: `deploy.log` trong thư mục repo.

> `deploy.sh` push **1 commit cuộn** (force-push, `--amend`) lên nhánh `pages` nên
> lịch sử không phình dù chạy 5 phút/lần. Nếu crawl fail (API chặn/đổi), `main.py`
> exit ≠ 0 → `deploy.sh` dừng, **không ghi đè** playlist cũ đang publish.

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `SOCOLIVE_API` | `https://json.vnres.co` | Host API JSON. Đổi nếu CDN này chết. |
| `SOCOLIVE_REF` | `https://socoliveaus.co/` | Referer ghi vào m3u (pull host check Referer). |
| `SOCOLIVE_MAX` | `150` | Số phòng lấy stream tối đa. |
| `SOCOLIVE_OUT` | `output` | Thư mục xuất (`deploy.sh` dùng `public`). |
| `SOCOLIVE_INSECURE` | – | `1` = bỏ verify TLS (chỉ khi máy có proxy MITM). |

## Lưu ý

- Yêu cầu: máy phải **bật** lúc muốn cập nhật; đang ở **khu vực không bị chặn** (VN).
- Cần cấu hình SSH push sẵn (đã push tay được là ổn). launchd chạy dưới user của
  bạn; nếu push lỗi auth, thêm `UseKeychain yes` + `AddKeysToAgent yes` vào `~/.ssh/config`.
- Link `.m3u8` có `auth_key`/`txSecret` hết hạn sau ~vài giờ → cần chạy định kỳ.
- 0 trận đang live không phải lỗi (exit 0) — chỉ là hiện không có trận nào phát.
