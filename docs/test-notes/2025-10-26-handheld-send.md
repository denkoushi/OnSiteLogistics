# 2025-10-26 Handheld send test

## 目的
- ハンディリーダ (OnSiteLogistics) の送信先を `http://raspi-server.local:8501/api/v1/scans` に切り替えた後、送信動作とログ出力、再送キューの挙動を確認する。

## 手順
1. `git checkout feature/logging-enhancements && git pull --ff-only`
2. `/etc/onsitelogistics/config.json` を更新 (`api_url=http://raspi-server.local:8501/api/v1/scans`)
3. systemd サービスを停止・無効化 `handheld@denkonzero.service`
4. `sudo PYTHONPATH=/home/denkonzero/e-Paper/RaspberryPi_JetsonNano/python/lib python3 scripts/handheld_scan_display.py`
5. バーコードを 2 回読み込み (`Status: DONE` を確認)
6. `sqlite3 ~/.onsitelogistics/scan_queue.db 'SELECT id, target, retries, payload FROM scan_queue'`

## 結果
- スキャン完了後 `Status: DONE` が表示された。
- `raspi-server.local` が名前解決できないため HTTP 接続は失敗し、payload は `scan_queue` に保存された。サーバー起動後に再送予定。
- systemd 自動起動は停止済みで、手動実行のみ有効。

## メモ
- サーバー起動時に `/etc/hosts` へ `raspi-server.local` を追記、または `api_url` を IP アドレスへ更新する必要あり。
- 正式運用時は RaspberryPiServer 側のログ（`mirror_requests.log`）と `~/.onsitelogistics/logs/handheld.log` を突き合わせて確認する。
