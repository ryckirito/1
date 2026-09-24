# A 股每日异动与推荐建仓日报

每个交易日收盘后自动跑一遍：拉取行情 → 扫描异动 → 多因子评分选出建仓候选 → 生成 Markdown / HTML / JSON 日报 → 可选推送到钉钉 / 企业微信。

> 本程序基于历史量价数据的规则计算，仅供研究参考，不构成任何投资建议。

## 快速开始

```bash
pip install -r requirements.txt

# 1. 离线演示（合成数据，无需联网）
python -m daily_report run --source demo --print

# 2. 真实行情（东方财富公开接口，直接用 requests，无需 akshare）
cp config.example.yaml config.yaml      # 按需修改阈值 / 资金 / 自选股
python -m daily_report run --source eastmoney --config config.yaml

# 3. 也可以用 akshare（需额外 pip install akshare）
python -m daily_report run --source akshare --config config.yaml

# 4. 用自己的 CSV 行情
python -m daily_report gen-demo --out data/csv      # 生成一份示例 CSV 看格式
python -m daily_report run --source csv --csv-dir data/csv
```

报告写到 `reports/<日期>.md|html|json`，同时更新 `reports/latest.*`。

常用参数：`--date 2026-09-24`（默认今天，非交易日自动回退到最近交易日）、`--top-n 5`、`--capital 500000`、`--formats md,html`、`--notify`（推送到配置的 webhook）、`-v`（调试日志）。

## 报告内容

1. **市场概览**：覆盖股票数、涨跌家数、涨停 / 跌停数、涨跌幅中位数、成交额变化、站上 MA20 比例、涨跌幅前五。
2. **异动榜**：对每只股票最新交易日打标签，按强度排序。标签包括：
   - 涨停 / 跌停（按板块自动识别 10% / 20% / 30% / ST 5%）
   - 大涨 / 大跌（默认 ±7%）
   - 放量（量比 ≥ 3）/ 缩量（量比 ≤ 0.35）
   - 60 日新高 / 60 日新低
   - 跳空高开 / 跳空低开（缺口 ≥ 3%）
   - 大振幅（≥ 8%）
   - 统计异常（当日收益率 z-score ≥ 3）
   - 高换手（数据源提供换手率时）
3. **推荐建仓**：多因子评分（满分 100）筛出 Top N，并给出完整交易计划。
   - 趋势 30：收盘 > MA20 > MA60，MA20 向上
   - 动量 20：20 日涨幅在 0~30% 的健康区间
   - 量能 15：温和放量上涨或缩量回调
   - RSI 15：RSI14 在 45~72
   - 形态 20：回踩 MA20 低吸 / 放量突破 20 日高点追强
   - 过滤：ST、当日涨停、当日涨幅 > 7% 或跌幅 > 4%、跳空低开、20 日均成交额 < 5000 万、ATR > 6%、历史不足 70 天
   - 交易计划：入场价、止损（收盘 − 2×ATR 与 10 日最低取高者，且至少 3%）、目标价（盈亏比 1:2）、按“单笔风险 1% 总资金”反推的建议股数与仓位（上限 20%）
4. **风险提示**

所有阈值都在 `config.example.yaml` 里，改一份 `config.yaml` 即可。示例输出见 `docs/sample_report.md` / `docs/sample_report.html`（demo 数据生成）。

## 数据源

| source | 说明 |
|---|---|
| `demo` | 合成随机行情并注入典型异动，离线可跑，用于演示与测试 |
| `csv` | 本地 CSV。目录下放 `all.csv` 长表（含 code 列）或每只一个 `<code>_<name>.csv`；支持中文表头（日期/开盘/最高/最低/收盘/成交量/成交额/换手率） |
| `eastmoney` | 东方财富公开行情接口。先拉全市场快照，再对“成交额前 N + 涨跌幅/量比极端股 + 自选股”逐只拉前复权日 K；有本地缓存（`data/cache`） |
| `akshare` | 同上思路，通过 akshare 取数，需 `pip install akshare` |

`max_symbols` 控制联网数据源的候选池大小（默认 300，全市场约 5000 只全拉一遍要几分钟，按需调大）。

## 每日自动运行

**crontab（Linux / macOS）**，每个工作日 15:30 收盘后跑：

```
30 15 * * 1-5 cd /path/to/repo && /usr/bin/python3 -m daily_report run --source eastmoney --config config.yaml --notify >> logs/daily.log 2>&1
```

或直接用 `scripts/run_daily.sh`（自带日志目录与虚拟环境激活）。

**GitHub Actions**：仓库自带 `.github/workflows/daily.yml`，工作日北京时间 15:40 自动运行并把报告作为 artifact 上传；在仓库 Secrets 里配置 `WEBHOOK_URL` / `WEBHOOK_KIND` 即可同时推送。

## 推送

`config.yaml` 的 `notify` 节：

```yaml
notify:
  webhook_url: https://oapi.dingtalk.com/robot/send?access_token=...
  kind: dingtalk        # dingtalk | wecom | generic
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
  indicators.py   MA / ATR / RSI / 量比 / z-score 等
  anomaly.py      异动检测
  recommend.py    评分与交易计划
  report.py       Markdown / HTML / JSON 渲染
  notify.py       webhook 推送
  market.py       板块 / 涨跌停幅度 / 交易所判断
  data/           数据源：demo, csv, eastmoney, akshare
  templates/      Jinja2 模板
tests/            pytest
```
