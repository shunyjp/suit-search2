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
                        yahoo_auctions.py      Yahoo!オークション（実装済み・実機確認済み）
                        paypay_flea_market.py  PayPayフリマ（実装済み・実機確認済み）
                        yahoo_shopping.py      Yahoo!ショッピング（実装済み・実機確認済み）
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
    storage/          SQLAlchemy モデル・リポジトリ（SQLite、実機確認済み）
    workflows/        crawl / recheck / report ジョブ
    config/           YAML 設定ファイル
  tests/              279件 全パス（ビジネスロジック層 96–100% カバレッジ）
  scripts/
    fetch_sample.py   1件取得確認スクリプト
    run_pipeline.py   フルパイプライン実行スクリプト
    test_search.py    search() 実機テストスクリプト
```

## 環境セットアップ

```bash
# 1. Python 3.11+ が必要
python --version

# 2. 依存ライブラリインストール
pip install -r requirements.txt

# 3. Playwright ブラウザインストール
python -m playwright install chromium

# 4. 環境変数設定
# GEMINI_API_KEY: LLM補完が有効になる（未設定でも通常判定は動作）
# YAHOO_AUCTION_APP_ID: search() が有効になる（未設定でも手動URL入力は動作）
export GEMINI_API_KEY="your-gemini-key"         # Mac/Linux
export YAHOO_AUCTION_APP_ID="your-yahoo-appid"  # Mac/Linux
$env:GEMINI_API_KEY = "your-gemini-key"         # Windows PowerShell
$env:YAHOO_AUCTION_APP_ID = "your-yahoo-appid"  # Windows PowerShell
```

Yahoo Japan API キーの取得: https://e.developer.yahoo.co.jp/register

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

# フルパイプライン実行（URLを直接指定）
python scripts/run_pipeline.py https://auctions.yahoo.co.jp/jp/auction/XXXXXXXXX
python scripts/run_pipeline.py https://paypayfleamarket.yahoo.co.jp/item/XXXXXXXXX
python scripts/run_pipeline.py https://store.shopping.yahoo.co.jp/zozo/XXXXXXXX.html

# search() テスト（YAHOO_AUCTION_APP_ID 必要）
python scripts/test_search.py
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

## search() の動作方式

Yahoo Auctions 検索ページは headless ブラウザを bot 検出してサーバー側で結果を空にするため、
スクレイピングは不可能。また Yahoo Auctions Web Service API（`auctions.yahooapis.jp`）は
新規登録アプリでは 403 を返す（廃止済みと推定）。

そのため `search()` は **Yahoo Shopping API V3 (`condition=used`)** を使用する：

| 方式 | 状態 | 備考 |
|------|------|------|
| Yahoo Auctions スクレイピング | ❌ bot検出でブロック | `pageData.items=[]` が返る |
| Yahoo Auctions Web Service API | ❌ 403 Forbidden | 新規登録では利用不可 |
| Yahoo Shopping API V3 (used) | ✅ **動作確認済み** | ZOZO Used 等の中古品 |

返却される URL は `store.shopping.yahoo.co.jp` 形式で、`YahooShoppingConnector` が処理する。

## コネクタ一覧

| コネクタ | 対象URL | 取得方式 |
|----------|---------|---------|
| `YahooAuctionsConnector` | `auctions.yahoo.co.jp/jp/auction/*` | Playwright + `__NEXT_DATA__` |
| `PayPayFleaMarketConnector` | `paypayfleamarket.yahoo.co.jp/item/*` | Playwright + `__NEXT_DATA__` |
| `YahooShoppingConnector` | `store.shopping.yahoo.co.jp/*/*` | httpx + `__NEXT_DATA__` (SSR・ブラウザ不要) |

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
| Yahoo!ショッピング コネクタ | ✅ 実装済み・実機確認済み（httpx・ブラウザ不要） |
| price / status / size パーサー | ✅ 実装済み |
| material / style / condition パーサー | ✅ 実装済み |
| Gemini LLM 補完（テキスト） | ✅ 実装済み・実機確認済み（`google-genai` SDK, `gemini-2.5-flash`） |
| Gemini LLM 補完（画像・採寸表） | ✅ 実装済み・実機確認済み（マルチモーダル） |
| search()（Yahoo Shopping API） | ✅ 実装済み・実機確認済み（50件/回） |
| SQLite 保存 | ✅ 実装済み・実機確認済み（`suitfinder.db` 自動作成） |
| Alembic マイグレーション | ❌ 未作成（`create_tables()` で代替） |
| recheck_job | ⚠️ スタブ |
| report_job | ⚠️ スタブ |
| n8n 定期実行連携 | ❌ 未着手 |

## 既知の制限事項

- **Yahoo Auctions `search()` はオークション出品を返さない**: Yahoo Auctions の API・スクレイピングは両方ブロックされており、代替として Yahoo Shopping の中古品（主に ZOZO Used）を返す。個人出品のオークション商品は手動でURLを入力して処理する。
- **listing_type の判定**: Yahoo Shopping 経由のアイテムは `listing_type` が特定されないため、verdict が `NO_MATCH` になりやすい（採寸データ自体は正常取得）。

## 次の実装優先順位

1. **listing_type 判定の改善**: Yahoo Shopping アイテムを固定価格として認識させる
2. **n8n 定期実行連携**: HTTP trigger で crawl_job を定期実行
3. **recheck_job / report_job**: DB 接続後に実装
