# 要件とロードマップ（OnSiteLogistics）

Raspberry Pi Zero 2 W を用いたハンディリーダ（Window D）の役割、現況、機能要件、決定事項、残課題を整理する。セットアップやスクリプト実行手順は `docs/handheld-reader.md` を参照すること。

---

## 0. 現況サマリー（2025-10-31 時点）
- **役割**: 工場内の部品移動をバーコードで記録し、RaspberryPiServer（Pi5）へ送信するモバイル端末。所在・搬送履歴は Pi5 から Window A／サイネージへ展開する。
- **稼働状況**: `scripts/handheld_scan_display.py` による HID/シリアル両対応、再送キュー、`--drain-only` CLI、config ファイル読み込み、電子ペーパー表示が動作済み。テストログは `docs/test-notes/` に蓄積中。
- **依存関係**: Pi5 API (`/api/v1/scans`, `/api/logistics/jobs`)、Dropbox サイネージ（Window C）へのデータ連携方針、Window A UI の表示要求。
- **課題**: 実機テスト網羅、ログローテーションと監視、電源運用と筐体設計、物流ジョブ送信の本番運用化。

---

## 1. ゴール
1. ハンディリーダが部品バーコード＋棚バーコードの 2 ステップを確実に取得し、Pi5 へ即時送信できること。
2. 通信断や電源再投入時でもローカルキューから自動再送され、所在情報の欠落を防ぐこと。
3. Pi5 から Window A／Window C へ展開される所在・物流情報と整合し、現場全体で同じデータを参照できること。

---

## 2. 関係者と責務

| 区分 | 役割 | 主な責務 |
| --- | --- | --- |
| プロダクトオーナー（ユーザー） | ハンディの運用要件・投入スケジュールの決定 | バーコード仕様、棚コード体系、運用ルールの提示 |
| OnSiteLogistics チーム（Window D） | ハンディ端末のソフト／ハード整備、再送キューとログ監視 | `scripts/handheld_scan_display.py`・config・systemd の保守 |
| RaspberryPiServer チーム（Window E） | `/api/v1/scans`・`/api/logistics/jobs` の提供、アクセストークン運用 | API スキーマ公開、Pi5 側ログ監視、サーバー再送フィードバック |
| Window A チーム | 右ペイン UI とサイネージでの所在可視化 | イベント受信、エラー表示、Pi5 連携の検証 |

---

## 3. 機能要件（ステータス付き）

| 状態 | ID | 内容 | 実装メモ |
| --- | --- | --- | --- |
| ✅ | F-01 | HID キーボードスキャナから A/B コードを読み取り、順序・タイムアウト・キャンセル（`CANCEL`/`RESET`）を判定する | `KeyboardScanner`（evdev） + cancel コード、30s タイムアウト |
| ✅ | F-02 | USB シリアル（CDC-ACM）スキャナへ自動フォールバックし、デバイスプローブを複数ボーレートで試行する | `SERIAL_GLOBS` / `SERIAL_BAUDS` / リトライロジック |
| ✅ | F-03 | 電子ペーパー（Waveshare 2.13" V4）へ状態表示を更新し、部分更新 5 回ごとに全更新する | `EPaperUI`、部分更新カウンタ |
| ✅ | F-04 | `config/config.json` もしくは `ONSITE_CONFIG` から API URL・トークン・デバイス ID・ログ設定を読み込む | CLI `--config` で任意パス指定可 |
| ✅ | F-05 | 送信失敗時に SQLite キューへ格納し、起動時／`--drain-only` 実行時に順次再送する | `QueueStore`、`drain()`、CLI フラグ |
| ✅ | F-06 | ローテーション付きログ（10 MiB × 3 世代）にイベント・エラーを出力し、`--debug` で詳細ログを有効化する | `logging.handlers.RotatingFileHandler` |
| ☐ | F-07 | `/api/logistics/jobs` への搬送完了連携を本番運用へ組み込み、エラー時のリトライをサーバー応答に合わせて調整する | 現状はオプション。運用手順・確認コマンドを整備する |
| ☐ | F-08 | systemd service/timer（例: `handheld@.service`, `handheld-drain.timer`）を定義し、電源投入・定期再送を自動化する | サンプル unit を `docs/handheld-reader.md` へ掲載予定 |
| ☐ | F-09 | 電子ペーパー以外のフォールバック表示（USB シリアルコンソール／LED）を定義し、故障時の緊急運用手順を用意する | ハード設計・実機検証待ち |

---

## 4. 非機能要件
- **性能**: A/B 2 回のスキャン入力から送信完了まで 2 秒以内を目標。通信失敗時はキュー投入まで 1 秒以内。電子ペーパー更新は部分更新 0.5 秒以内。
- **可用性**: 電源投入後 15 秒以内にサービス起動。systemd により異常終了時は自動再起動。キューの最大保持期間は 7 日間を上限とし、溢れた場合は警告ログ。
- **保守性**: 設定は `/etc/onsitelogistics/config.json` に集約し、`scripts/install_client_config.sh` で初期化。ログは `/var/log/onsitelogistics/handheld.log`（想定）へ出力し、`journalctl -u handheld@` で追跡可能とする。
- **セキュリティ**: API トークンは Pi5 が発行・ローテーション。設定ファイルの権限は `600` を保持し、送信先は HTTPS/TLS も将来的に検討する。ローテーション手順は RaspberryPiServer RUNBOOK（4章）および OnSiteLogistics RUNBOOK（3章）に従い、Pi5／Window A と同じ値を `/etc/onsitelogistics/config.json` に反映する。

---

## 5. インターフェースと依存関係
- **RaspberryPiServer (Pi5)**: `/api/v1/scans`（所在更新）と `/api/logistics/jobs`（搬送記録）。レスポンス JSON を `QueueStore` へ記録し、必要に応じて Window A へ返す。
- **Window A**: Socket.IO イベントを受信して所在画面を更新。ハンディの送信遅延が UI 表示へ影響するため、エラー発生時は通知用の API/Socket.IO を協議する。
- **Window C**: Dropbox 経由で所在サイネージを更新する際、Pi5 側の JSON 生成スケジュールに従う。ハンディからの送信は Pi5 で即時反映される前提とする。
- **ハードウェア**: USB スキャナ、電子ペーパー、LED/ブザー（オプション）。交換手順・予備パーツの管理は RUNBOOK 整備後に記載予定。

---

## 6. 決定事項

| 決定日 | 内容 | 理由 / 参照 |
| --- | --- | --- |
| 2025-09-xx | HID → シリアルへの自動切替ロジックを実装し、どちらのスキャナでも同一スクリプトを使用する | ハード構成変更時でもサービスを維持するため |
| 2025-10-xx | SQLite ベースの再送キューと `--drain-only` CLI を導入 | 通信断時の手動再送・統計確認を容易にするため |
| 2025-10-xx | ローテーションログ（10 MiB × 3）と `/proc` 監視を整備 | 長時間稼働時のログ肥大・メモリ枯渇を防ぐため |
| 2025-10-xx | `/api/logistics/jobs` 連携は任意オプションとして実装、運用投入前に Window A と調整 | 物流データの扱いを段階的に導入するため |
| 2025-11-05 | Pi5 / Window A / ハンディで同一 API トークンを共有し、RUNBOOK にローテーション手順を追加 | 認証エラー防止と紛失時の迅速な失効を実現するため |

日付は実施時点で更新し、関連コミット・テストログを `docs/test-notes/` に記録すること。

---

## 7. バックログ / 未対応課題

- **優先度: 高**
  - systemd unit/timer のサンプル整備とテスト。`docs/handheld-reader.md`・README へ導入手順を追記する。
  - 実機での長時間運用テスト（キュー溢れ・Wi-Fi 再接続・電源遮断復帰）を `docs/test-notes/` に記録する。
  - `/api/logistics/jobs` 連携のユースケース定義（棚間搬送／工程完了）とエラー通知ルール策定。
- **優先度: 中**
  - 電子ペーパーのステータス表示を多言語／アイコン化し、視認性を向上させる。
  - CLI のヘルプメッセージ・usage を README に抜粋し、現場スタッフ向けクイックリファレンスを作成する。
  - 監視スクリプト（ログ件数・キュー長の警報）を追加し、Window A/Slack へ通知する仕組みを検討する。
- **優先度: 低**
  - ハード筐体／3D プリントケースの設計・ケーブル結束方法のドキュメント化。
  - 電源管理（UPS 連携、バッテリー残量モニタ）と省電力設定の検証。
  - オフラインモードでの一括同期（QR 付き紙伝票から CSV 生成）など将来機能の調査。

課題を着手・完了した際は本書を更新し、完了内容を `docs/test-notes/` または `CHANGELOG.md`（新規作成可）に記録する。

---

## 8. 参照ドキュメント
- ハンディ操作・セットアップ: `docs/handheld-reader.md`
- ドキュメント運用ルール: `docs/documentation-guidelines.md`
- ドキュメント索引: `docs/docs-index.md`
- テスト記録: `docs/test-notes/2025-10-26-handheld-send.md`
- RaspberryPiServer 側仕様: `/Users/tsudatakashi/RaspberryPiServer/docs/requirements.md`, `docs/api-plan.md`
