# 美股每日异动与推荐建仓日报

每个交易日美股收盘后自动跑一遍：拉取行情 → 扫描异动 → 多因子评分选出建仓候选 → 生成 Markdown / HTML / JSON 日报 → 可选推送到 Slack / Discord / 钉钉 / 企业微信。

> 本程序基于历史量价数据的规则计算，仅供研究参考，不构成任何投资建议。

## 快速开始

```bash
pip install -r requirements.txt

# 1. 离线演示（合成数据，无需联网）
python -m daily_report run --source demo --print

# 2. 真实行情：Yahoo Finance（yfinance，批量下载，推荐）
cp config.example.yaml config.yaml      # 按需修改阈值 / 资金 / 自选股
python -m daily_report run --source yfinance --config config.yaml

# 3. 或 Stooq（免费日线 CSV，逐只请求，稍慢）
python -m daily_report run --source stooq --config config.yaml

# 4. 用自己的 CSV 行情（兼容 Yahoo 导出格式）
python -m daily_report gen-demo --out data/csv      # 生成一份示例 CSV 看格式
python -m daily_report run --source csv --csv-dir data/csv
```

报告写到 `reports/<日期>.md|html|json`，同时更新 `reports/latest.*`。示例输出见 `docs/sample_report.md` / `docs/sample_report.html`（由 GitHub Actions 用 Yahoo Finance 真实行情生成）。

常用参数：`--date 2026-09-24`（默认今天，非交易日自动回退到最近交易日）、`--universe nasdaq`、`--max-symbols 500`、`--top-n 5`、`--capital 50000`、`--formats md,html`、`--notify`、`-v`。

## 报告内容

1. **市场概览**：SPY / QQQ 等基准表现，覆盖股票数、涨跌家数、涨超/跌超 5% 家数、52 周新高/新低数、涨跌幅中位数、成交额变化、站上 MA50 / MA200 比例、涨跌幅前五、板块平均涨跌幅。
2. **异动榜**：对每只股票最新交易日打标签，按强度排序：
   - 暴涨 / 暴跌（≥ 10%）、大涨 / 大跌（≥ 5%）
   - 放量（≥ 20 日均量 2.5 倍）/ 缩量（≤ 40%）
   - 52 周新高 / 新低，20 日新高 / 新低
   - 跳空高开 / 跳空低开（缺口 ≥ 2%，财报日常见）
   - 大振幅（≥ 6%）
   - 统计异常（当日收益率 z-score ≥ 3）
3. **推荐建仓**：多因子评分（满分 100）筛出 Top N，并给出完整交易计划。
   - 趋势 30：收盘 > MA50 > MA200，MA20 向上（历史不足 200 日时看 MA20 / MA50）
   - 动量 20：20 日涨幅在 0~25% 的健康区间
   - 量能 15：温和放量上涨或缩量回调
   - RSI 15：RSI14 在 45~72
   - 形态 20：回踩 MA20 低吸 / 放量突破 20 日高点追强
   - 过滤：股价 < $5、20 日均成交额 < $20M、ATR > 5%、当日涨幅 > 6% 或跌幅 > 4%、跳空低开、历史不足 120 天、基准 ETF
   - 交易计划：入场价、止损（收盘 − 2×ATR 与 10 日最低取高者，且至少 3%）、目标价（盈亏比 1:2）、按"单笔风险 1% 总资金"反推的建议股数（整股，可开碎股）与仓位（上限 15%）
4. **风险提示**

所有阈值都在 `config.example.yaml` 里，改一份 `config.yaml` 即可。

## 数据源与股票池

| source | 说明 |
|---|---|
| `demo` | 用内置股票池的代码生成合成行情并注入典型异动，离线可跑，用于演示与测试 |
| `csv` | 本地 CSV。目录下放 `all.csv` 长表（含 code/ticker 列）或每只一个 `<TICKER>_<Name>.csv`；兼容 Yahoo 导出格式，缺 amount 时按 close×volume 估算 |
| `yfinance` | Yahoo Finance，`yf.download` 一次批量拉取整个股票池，几百只只需几十秒；有本地缓存 |
| `stooq` | Stooq 免费日线 CSV，无需 key，逐只请求；有本地缓存 |

股票池 `data.universe`：

| 值 | 说明 |
|---|---|
| `builtin` | 内置约 190 只美股大盘股 + SPY/QQQ/IWM/DIA（`daily_report/data/universe_builtin.csv`） |
| `nasdaq` | 调 Nasdaq 股票筛选器拿全市场代码、板块、市值，按市值降序取前 `max_symbols` 只（`min_market_cap` 过滤） |
| 文件路径 | txt 每行一个代码（支持 `#` 注释），或 csv 含 `ticker[,name,sector]` 列 |

`watchlist` 里的自选股与 `benchmarks` 里的基准 ETF 无论如何都会拉取；基准只在概览中展示，不参与异动与推荐。

## 每日自动运行

美股收盘为美东 16:00，日线数据通常收盘后十几分钟就绪。

**crontab（Linux / macOS）**，按服务器所在时区换算，例如 UTC 服务器工作日 21:30（美东 16:30 / 17:30）：

```
30 21 * * 1-5 cd /path/to/repo && /usr/bin/python3 -m daily_report run --source yfinance --config config.yaml --notify >> logs/daily.log 2>&1
```

或直接用 `scripts/run_daily.sh`（自带日志目录与虚拟环境激活）。

**GitHub Actions**：仓库自带 `.github/workflows/daily.yml`，工作日 UTC 21:30 自动运行并把报告作为 artifact 上传；在仓库 Secrets 里配置 `WEBHOOK_URL` / `WEBHOOK_KIND` 即可同时推送。

## 本机无法访问行情接口时

`.github/workflows/fetch-data.yml` 可在 GitHub 云端拉取行情并生成日报，然后把行情快照 `history.csv` 和报告一起强推到 `data-snapshot` 分支。在 Actions 页面手动运行它（或用 API 触发），之后在任何只能访问 GitHub 的环境里：

```bash
bash scripts/pull_snapshot.sh            # 拉取快照，并用 csv 数据源在本地复算
bash scripts/pull_snapshot.sh --top-n 5  # 可附加任意 run 参数
```

`--dump-history` 选项也可以单独使用：`python -m daily_report run --source yfinance --dump-history data/history.csv`，把一次联网拉到的行情存下来，之后离线用 `--source csv` 反复调参复算。

## 推送

`config.yaml` 的 `notify` 节：

```yaml
notify:
  webhook_url: https://hooks.slack.com/services/...
  kind: slack        # slack | discord | dingtalk | wecom | generic
```

`generic` 会 POST 一个 `{title, text, report}` JSON，方便对接自己的服务。

## 开发

```bash
pip install -e ".[dev]"
pytest -q
```

目录结构：

```
daily_report/
  cli.py          命令行
  config.py       配置数据类与 YAML 加载
  pipeline.py     取数 → 指标 → 异动 → 推荐 → 概览
  indicators.py   MA / ATR / RSI / 量比 / 52 周高低 / z-score 等
  anomaly.py      异动检测
  recommend.py    评分与交易计划
  report.py       Markdown / HTML / JSON 渲染
  notify.py       webhook 推送
  market.py       代码规范化 / 美元格式化
  data/           股票池与数据源：universe, demo, csv, yfinance, stooq
  templates/      Jinja2 模板
tests/            pytest
```
