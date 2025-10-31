# OnSiteLogistics

工場内の部品・材料の所在をリアルタイムに把握し、サイネージで可視化するための支援ツールです。現場スタッフがハンディスキャナで移動票と棚のバーコードを読み取り、その履歴を集約して所在を表示する仕組みの構築を目指します。

- **対象**: 小規模金属加工工場
- **主な機能目標**:
  - ハンディリーダと棚バーコードの読み取りによる入出庫記録
  - サーバー連携による所在データ蓄積とサイネージ表示
  - モバイルバッテリー駆動の携帯デバイス運用

## ドキュメント
- `docs/AGENTS.md`: エージェント向け運用指針
- `docs/documentation-guidelines.md`: 文書運用ルール
- `docs/requirements.md`: 要件・決定事項・未決課題
- `docs/handheld-reader.md`: ハンディリーダ開発ノート
- 初回導入やサーバー疎通手順は `docs/handheld-reader.md` の「実行コマンドメモ」「セットアップログ」を参照してください。

今後の構成として、セットアップや運用手順が固まり次第 `RUNBOOK.md` やサーバー連携仕様書を追加します。

## 設定ファイル
- サンプル: `config/config.sample.json`
- 実運用時は `/etc/onsitelogistics/config.json` に配置します。
- 自動セットアップ例:
  ```bash
  cd ~/OnSiteLogistics
  sudo ./scripts/install_client_config.sh \
    --api-url http://raspi-server.local:8501/api/v1/scans \
    --api-token <token> \
    --device-id HANDHELD-01
  ```
- 設定後は `sudo systemctl restart handheld@<user>.service` でサービスを再起動し、送信が成功することを確認してください。
- 疎通テスト: `sudo ./scripts/check_connection.sh --dry-run` で設定内容を確認し、`sudo ./scripts/check_connection.sh` で実際にテスト送信して HTTP ステータスを確認できます。
- キューの再送: `sudo ./scripts/handheld_scan_display.py --drain-only` を実行するとキューに溜まったスキャンを順次送信し、完了後すぐ終了します。cron/systemd からの定期実行も可能です。
- RaspberryPiServer の構内物流 API と連携する場合は、以下の項目を追記してください。
  ```json
  {
    "logistics_api_url": "http://raspi-server.local:8501/api/logistics/jobs",
    "logistics_default_from": "STAGING-AREA",
    "logistics_status": "completed"
  }
  ```
  ハンディリーダで A/B コードを読み取るたびに、所在更新（`/api/v1/scans`）に加えて搬送完了レコードを `/api/logistics/jobs` へ送信します。通信断時はスキャン送信と同じキューで自動再送されます。

## テスト

開発環境でサンプル設定の整合性を確認する場合は pytest を利用します。

```bash
pip install -r requirements-dev.txt
pytest
```

または Makefile を利用する場合:

```bash
make test
```
