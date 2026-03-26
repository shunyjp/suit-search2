# Suit Finder

中古メンズスーツ横断検索・候補判定システム

## 設計方針

- **evidence 中心設計**: DOMセレクタはテキストバケット取得にのみ使用。サイズ・素材はすべて本文・仕様欄テキストから正規表現で解釈する。
- **unknown / ambiguous を正常系として扱う**: 取得できなかったフィールドは `null` で保持し `unknown_fields` に列挙する。あいまい表現は `warnings` に残す。
- **LLM は補助のみ**: ルールベース parser で取得できなかったフィールドの補完にのみ使用。最終判定は必ずルールベース。
- **画像補完**: テキストに採寸情報がない場合、Gemini のマルチモーダル機能で画像（採寸表）からサイズを読み取る。

## ディレクトリ構成

```
suit-finder/
  app/
    api/              FastAPI エンドポイント（/health のみ実装）
    connectors/       サイト別コネクタ
                        yahoo_auctions.py   Yahoo!オークション（実装済み）
                        paypay_flea_market.py  PayPayフリマ（実装済み）
    fetchers/         Playwright ブラウザ管理・ページ取得
    evidence/         EvidenceBlock 抽出・クリーニング・マージ
    parsers/          全パーサー実装済み
                        price_parser       価格・即決/オークション判定
                        status_parser      出品中/終了判定
                        size_parser        採寸値抽出（regex）
                        material_parser    繊維組成抽出
                        style_parser       シングル/ダブル・ボタン種別判定
                        condition_parser   状態・汚れ判定
    normalizers/      テキスト・単位・素材の正規化
    llm/              Gemini 補完レイヤー（実装済み）
                        gemini_client.py   google-genai SDK ラッパー
                        supplement.py      テキスト補完 → 画像補完の2段階実行
                        merger.py          LLM結果を既存出力にマージ（上書き禁止）
                        prompts.py         プロンプトビルダー
    rules/            判定エンジン・スコアリング
    storage/          SQLAlchemy モデル・リポジトリ（実装済み・DB未テスト）
    workflows/        crawl / recheck / report ジョブ
    config/           YAML 設定ファイル
  tests/              279件 全パス（ビジネスロジック層 96–100% カバレッジ）
  scripts/
    fetch_sample.py   1件取得確認スクリプト
    run_pipeline.py   フルパイプライン実行スクリプト
```

## 環境セットアップ

```bash
# 1. Python 3.11+ が必要
python --version

# 2. 依存ライブラリインストール
pip install -r requirements.txt

# 3. Playwright ブラウザインストール
python -m playwright install chromium

# 4. 環境変数設定（オプション）
# GEMINI_API_KEY を設定すると LLM 補完が有効になる
# 未設定でも通常判定は動作する
export GEMINI_API_KEY="your-key-here"  # Mac/Linux
$env:GEMINI_API_KEY = "your-key-here"  # Windows PowerShell
```

## テスト実行

```bash
# プロジェクトルート (suit-finder/) で実行
cd suit-finder

# 全テスト（279件）
pytest tests/ -q

# カバレッジ付き
pytest --cov=app --cov-report=term-missing

# 特定モジュール
pytest tests/test_size_parser.py -v
pytest tests/test_price_parser.py -v
pytest tests/test_status_parser.py -v
pytest tests/test_decision_engine.py -v
```

## スクリプト実行

```bash
# PageSignals のみ確認（Playwright 必要）
python scripts/fetch_sample.py https://auctions.yahoo.co.jp/jp/auction/XXXXXXXXX
python scripts/fetch_sample.py https://paypayfleamarket.yahoo.co.jp/item/XXXXXXXXX

# フルパイプライン実行
python scripts/run_pipeline.py https://auctions.yahoo.co.jp/jp/auction/XXXXXXXXX
python scripts/run_pipeline.py https://paypayfleamarket.yahoo.co.jp/item/XXXXXXXXX
```

## LLM 補完の動作フロー

```
1. テキスト解析（regex パーサー）
      ↓ unknown_fields > 3 または outer_fibers が空
2. Gemini テキスト補完（説明文・仕様欄を送信）
      ↓ unknown_fields > 5 かつ image_urls あり
3. Gemini 画像補完（採寸表画像を最大4枚送信）
      ↓
4. マージ（LLM値は confidence=0.4, source="llm_gemini"。既存値は上書きしない）
```

`GEMINI_API_KEY` 未設定の場合、LLM ステップはスキップされ通常判定のみ実行（例外なし）。

## API サーバー起動

```bash
cd suit-finder
uvicorn app.api.main:app --reload
```

`http://localhost:8000/docs` で Swagger UI が確認できます。

現在実装済みのエンドポイント：

| Method | Path | 説明 |
|--------|------|------|
| GET | `/health` | ヘルスチェック |

## 購入判定条件（ユーザー定義）

詳細は `app/config/judgement_rules.yaml` を参照。

### ジャケット
| 項目 | 条件 |
|------|------|
| 肩幅 | 43–45 cm 必須 |
| 身幅 | 51–53 cm 必須 |
| 袖丈 | 60–64 cm 必須（59cm以下NG） |
| 着丈 | 72 cm 参考 |

### パンツ
| 項目 | 条件 |
|------|------|
| ウエスト平置き | 42–45 cm |
| 股下 | 74cm以上（裾ダブルなら71cmまで許容、70cm以下NG） |
| 裾幅 | 18cm未満NG |
| ワタリ | 29cm以下NG |

### 金額
- **30,000円以下**
- オークション形式は **即決価格が必須**

### スタイル・素材 NG
- ダブルブレスト / 1ボタン / 金銀ボタン NG
- ポリエステル・ポリウレタン・コットン主体 NG

## 判定区分

| 区分 | 説明 |
|------|------|
| `MATCH` | 全条件をクリア |
| `REVIEW` | 条件は満たすが unknown フィールドが多い |
| `NO_MATCH` | 1つ以上の blocking 条件に抵触 |

## 実装状況

| 項目 | 状態 |
|------|------|
| Yahoo!オークション コネクタ | ✅ 実装済み・実機確認済み（`__NEXT_DATA__` 方式） |
| PayPay フリマ コネクタ | ✅ 実装済み・実機確認済み |
| price / status / size パーサー | ✅ 実装済み |
| material / style / condition パーサー | ✅ 実装済み |
| Gemini LLM 補完（テキスト） | ✅ 実装済み（`google-genai` SDK） |
| Gemini LLM 補完（画像・採寸表） | ✅ 実装済み（マルチモーダル） |
| 検索結果 URL 収集（`search()`） | ✅ 実装済み・実機未テスト |
| PostgreSQL 保存 | ✅ 実装済み・DB未テスト |
| Alembic マイグレーション | ❌ 未作成 |
| recheck_job | ⚠️ スタブ（DB接続部分のみ未実装） |
| report_job | ⚠️ スタブ |
| n8n 定期実行連携 | ❌ 未着手 |

## 次の実装優先順位

1. **検索結果 URL 収集の実機テスト**: `YahooAuctionsConnector.search()` を実際の検索ページで確認
2. **PostgreSQL + Alembic**: Docker 等で DB を立ち上げ → `crawl_job` の保存部分を通しテスト
3. **n8n 定期実行連携**: HTTP trigger で crawl_job を定期実行
4. **recheck_job / report_job**: DB 接続後に実装
