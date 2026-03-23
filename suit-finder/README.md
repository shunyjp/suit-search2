# Suit Finder

中古メンズスーツ横断検索・候補判定システム（Phase 1–3 初期実装）

## 設計方針

- **evidence 中心設計**: DOMセレクタはテキストバケット取得にのみ使用。サイズ・素材はすべて本文・仕様欄テキストから正規表現で解釈する。
- **unknown / ambiguous を正常系として扱う**: 取得できなかったフィールドは `null` で保持し `unknown_fields` に列挙する。あいまい表現は `warnings` に残す。
- **LLM は補助のみ**: ルールベース parser で取得できなかったフィールドの補完にのみ使用（Phase 4）。
- **最終判定は必ずルールベース**: `decision_engine.py` のルールが主体。LLM 出力を直接 verdict に使わない。

## ディレクトリ構成

```
suit-finder/
  app/
    api/              FastAPI エンドポイント
    connectors/       サイト別コネクタ (Yahoo!オークション実装済)
    fetchers/         Playwright ブラウザ管理・ページ取得
    evidence/         EvidenceBlock 抽出・クリーニング・マージ
    parsers/          price / status / size (Phase 1–3 実装済)
                      material / style / condition (Phase 4 スタブ)
    normalizers/      テキスト・単位・素材の正規化
    llm/              Dify クライアント (Phase 4 スタブ)
    rules/            判定エンジン・スコアリング
    storage/          SQLAlchemy モデル・リポジトリ
    workflows/        crawl / recheck / report ジョブ
    config/           YAML 設定ファイル
  tests/
    fixtures/         サンプル JSON (Evidence Package, Parser Output など)
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
playwright install chromium

# 4. 環境変数設定
cp .env.example .env
# .env を編集して DATABASE_URL などを設定
```

## テスト実行

```bash
# プロジェクトルート (suit-finder/) で実行
cd suit-finder

# 全テスト
pytest

# カバレッジ付き
pytest --cov=app --cov-report=term-missing

# 特定モジュール
pytest tests/test_size_parser.py -v
pytest tests/test_price_parser.py -v
pytest tests/test_status_parser.py -v
pytest tests/test_decision_engine.py -v
pytest tests/test_normalizers.py -v
```

## API サーバー起動

```bash
cd suit-finder
uvicorn app.api.main:app --reload
```

`http://localhost:8000/docs` で Swagger UI が確認できます。

### エンドポイント

| Method | Path | 説明 |
|--------|------|------|
| GET | `/health` | ヘルスチェック |
| POST | `/crawl/` | 1件フェッチ＋判定 |
| POST | `/search/yahoo-auctions` | 検索URL生成 |
| GET | `/admin/report` | レポート (Phase 2+ スタブ) |

#### /crawl/ リクエスト例

```json
{
  "url": "https://page.auctions.yahoo.co.jp/jp/auction/xxxxxxxxx",
  "headless": true
}
```

#### /crawl/ レスポンス例

```json
{
  "url": "https://...",
  "success": true,
  "item_id": "uuid-xxxx",
  "verdict": "MATCH",
  "score": 0.85,
  "blocking_reasons": [],
  "reasons": [],
  "warnings": ["material_parser は未実装 (Phase 4)"]
}
```

## スクリプト実行

```bash
# PageSignals のみ確認（Playwright 必要）
python scripts/fetch_sample.py https://page.auctions.yahoo.co.jp/jp/auction/xxxxxxxxx

# フルパイプライン実行
python scripts/run_pipeline.py https://page.auctions.yahoo.co.jp/jp/auction/xxxxxxxxx
```

## 購入判定条件（ユーザー定義）

詳細は `app/config/judgement_rules.yaml` を参照。

### ジャケット
| 項目 | 条件 |
|------|------|
| 肩幅 | 43–45 cm 必須 |
| 身幅 | 51–53 cm 必須 |
| 袖丈 | 60–64 cm 必須 (59cm以下NG) |
| 着丈 | 72 cm 参考 |

### パンツ
| 項目 | 条件 |
|------|------|
| ウエスト平置き | 42–45 cm |
| 股下 | 74cm以上 (裾ダブルなら71cmまで許容, 70cm以下NG) |
| 裾幅 | 18cm未満NG |
| ワタリ | 29cm以下NG |

### 金額
- **30,000円以下**
- オークション形式は **即決価格が必須**

## 判定区分

| 区分 | 説明 |
|------|------|
| `MATCH` | 全条件をクリア |
| `REVIEW` | 条件は満たすが unknown フィールドが多い |
| `NO_MATCH` | 1つ以上の blocking 条件に抵触 |

## 未実装・暫定実装箇所

| 項目 | 状態 | Phase |
|------|------|-------|
| material_parser | スタブのみ | Phase 4 |
| style_parser (ダブル/1ボタン判定) | スタブのみ | Phase 4 |
| condition_parser (汚れ/穴判定) | スタブのみ | Phase 4 |
| 検索結果一覧のURL収集 | 未実装 | Phase 2 |
| Dify/LLM 補完 | スタブのみ | Phase 4 |
| recheck_job | スタブのみ | Phase 2 |
| report_job | スタブのみ | Phase 2 |
| PostgreSQL 保存 | 実装済み・未テスト | Phase 2 |
| Alembic マイグレーション | 未作成 | Phase 2 |
| Yahoo Auctions CSS セレクタ | 要実機確認 | Phase 1 |

## 次の実装優先順位

1. **Yahoo Auctions セレクタ確認**: 実際のページで PageSignals 取得確認
2. **検索結果ページのURL収集**: `search()` メソッドの実装
3. **material_parser**: ウール/ポリエステル/モヘア混率抽出
4. **style_parser**: シングル/ダブル、ボタン種別判定
5. **condition_parser**: 汚れ・穴・グレード判定
6. **Dify 補完統合**: unknown フィールドを LLM で補完
7. **PostgreSQL 保存テスト + Alembic**
8. **n8n 定期実行連携**
