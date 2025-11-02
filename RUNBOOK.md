# OnSiteLogistics RUNBOOK

Raspberry Pi Zero 2 W ハンディリーダ（Window D）の運用手順とトラブルシュートをまとめる。作業前には `docs/requirements.md` と `docs/handheld-reader.md` で最新仕様を確認し、Pi5（RaspberryPiServer）側の API が稼働していることを必ず確認する。

## 1. サービス操作

### 1.1 状態確認
```bash
sudo systemctl status handheld@denkonzero.service --no-pager
```
- `active (running)` であれば正常。
- `failed` や `inactive` の場合は 1.3 のログ確認を実施。

### 1.2 起動・停止・再起動
```bash
sudo systemctl start handheld@denkonzero.service
sudo systemctl restart handheld@denkonzero.service
sudo systemctl stop handheld@denkonzero.service
```
再起動後は `journalctl -u handheld@denkonzero.service -n 20 --no-pager` で直近ログを確認する。

### 1.3 ログの確認
```bash
sudo journalctl -u handheld@denkonzero.service -n 50 --no-pager
sudo tail -n 50 /var/log/onsitelogistics/handheld.log  # ローテーションログ想定
```
- `POST OK` や `Queue drained` が並ぶ場合は正常。
- `HTTP status != 200` が続く場合は Pi5 側 API またはネットワークを確認。

## 2. 設定ファイルの更新

本番構成ファイル: `/etc/onsitelogistics/config.json`

### 2.1 スクリプトによる配置
```bash
cd ~/OnSiteLogistics
sudo ./scripts/install_client_config.sh \
  --api-url http://raspi-server.local:8501/api/v1/scans \
  --api-token <token> \
  --device-id HANDHELD-01
```
- 既存ファイルは `*.bak` へバックアップ（`--force` 指定時を除く）。
- 反映後はサービス再起動 → 2.2 の疎通確認を実施。

### 2.2 疎通チェック
```bash
cd ~/OnSiteLogistics
./scripts/check_connection.sh --dry-run   # URL/Token 確認のみ
./scripts/check_connection.sh             # 実際に HTTP POST を送信
```
- HTTP ステータス 200/201 を期待。401/403 はトークン未設定の可能性。
- `curl failed` の場合は Pi5 の稼働状況・Wi-Fi 接続を確認。

## 3. API トークン運用

Pi5（RaspberryPiServer）、Window A（tool-management-system02）、OnSiteLogistics（本リポジトリ）は同じ Bearer トークンを共有する。ローテーションは RaspberryPiServer RUNBOOK（4章）を基準に、以下の手順で実施する。

1. **Pi5 / Window A で新しいトークンを発行**  
   Window A で `python scripts/manage_api_token.py rotate --station-id HANDHELD-01 --reveal` を実行し、新しいトークン値を取得する（`station_id` は端末名に置き換える）。Pi5 `/etc/default/raspi-server` の `API_TOKEN` / `VIEWER_API_TOKEN`、Window A `/etc/toolmgmt/window-a-client.env` の `RASPI_SERVER_API_TOKEN` を同じ値へ更新し、各サービスを再起動する。

2. **Pi Zero 側の設定を更新**  
   `/etc/onsitelogistics/config.json` の `api_token` を新しい値に差し替える。`scripts/install_client_config.sh --api-token <token>` を再実行するとバックアップを維持しながら配置できる。

3. **サービス再起動と疎通確認**  
   ```bash
   sudo systemctl restart handheld@denkonzero.service
   ./scripts/check_connection.sh --dry-run
   ./scripts/check_connection.sh          # 必要に応じて実送信
   ```
   200/201 が返れば成功。401/403 の場合は Pi5 / Window A 側の設定とトークン一致を再確認する。

4. **記録と監査**  
   ローテーション日・対象端末を運用ノートや `docs/test-notes/` に記録し、Pi5 側 `/var/log/raspi-server/app.log` とハンディ側ログを保存する。端末紛失時は Pi5 でトークンを失効し（`python scripts/manage_api_token.py revoke --station-id HANDHELD-01` など）、本手順で再発行する。

## 4. 再送キューの管理

`scripts/handheld_scan_display.py` は送信失敗時に SQLite キューへ保存する。

### 3.1 手動ドレイン
```bash
cd ~/OnSiteLogistics
sudo ./scripts/handheld_scan_display.py --drain-only
```
- 未送信データがある場合は順次送信し、完了後に終了。
- 終了コードが 0 以外の場合はログを確認し、再送試行前に原因を調査。

### 3.2 件数確認のみ
```bash
sudo ./scripts/handheld_scan_display.py --drain-only --dry-run
```
- キューが空の場合は `queue_size=0` を出力。

## 5. シリアルスキャナ環境のセットアップ

CDC-ACM スキャナを使用する場合は udev ルールと systemd override を設定する。
```bash
cd ~/OnSiteLogistics
sudo ./scripts/setup_serial_env.sh denkonzero
```
- 実行後、`/dev/minjcode0` または `/dev/ttyACM0` が作成されるか確認。
- サービス再起動後に `SERIAL` ログが出力されることを確認。

## 6. 障害対応フロー

| 症状 | 初期確認 | 追加対応 |
| --- | --- | --- |
| サービス起動失敗 | `journalctl -xe` で ExecStart エラーを確認 | config 権限 (`640` root:root) と JSON 設定値を再確認。必要に応じて再配置。 |
| スキャン入力を認識しない | `/dev/input/event*` / `/dev/ttyACM*` の存在確認 | スキャナの HID/Serial 切替を確認。必要なら `setup_serial_env.sh` を再実行。 |
| 送信失敗が継続 | `check_connection.sh` 、Pi5 側 `sudo docker compose logs app -n 50` を確認 | API 側の認証・ネットワーク障害。Pi5 でレスポンスログを確認し、トークン発行を再実施。 |
| キュー溢れ | `--dry-run` で件数確認、`--drain-only` で強制送信 | 送信失敗原因を解消後に再送。キュー保持期間（7日想定）を超える場合は CSV へエクスポートの検討。 |

## 7. 定期点検

| 頻度 | 項目 |
| --- | --- |
| 日次 | サービス稼働確認、`--dry-run` でキュー件数確認、Pi5 への疎通テスト。 |
| 週次 | 電子ペーパー残像・バッテリー稼働時間の点検、スキャナケーブルの状態確認。 |
| 月次 | `docs/docs-index.md` の棚卸し状況更新、ログローテーションサイズ確認、Pi5 API 仕様変更の有無確認。 |

## 8. 参照ドキュメント
- 要件・決定事項: `docs/requirements.md`
- ハンディ操作詳細: `docs/handheld-reader.md`
- 棚卸し計画: `docs/logistics-audit-plan.md`
- RaspberryPiServer 連携仕様: `/Users/tsudatakashi/RaspberryPiServer/docs/api-plan.md`
