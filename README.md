# harvest-mix

原料分级、意向需求、销售组合情景比较及逐单资源承诺核对。

## 当前产品

这是可独立运行的本地分析应用，提供业务记录核对、确定性基线结果和销售组合的情景比较。各业务职责可直接作为 Python 接口调用，`app.py` 负责组合只读业务检查。结果可保存为 JSON，不依赖远端服务。

- `production.py`：分级可得量、降级关系、时间能力，以及分析与承诺共用的资源分配。
- `demand.py`：最低交付、整包装步长、报价响应与市场情景。
- `costing.py`：固定/变动成本、组合收益口径与实际承诺核验。
- `portfolio.py`：推荐组合、加入/排除指定单的比较、瓶颈解释、不变成本与带重新判断的采纳。

## 销售组合情景比较

```bash
python3 app.py portfolio                          # 推荐组合、瓶颈、不变成本
python3 app.py portfolio --include O2             # 业务员指定必须加入 O2 后比较
python3 app.py portfolio --exclude O1 --output out/portfolio.json
```

分析在不动 `bookings` 的前提下，用当前原料、分级损耗、单向降级范围和产线能力评估可执行选择：

- 同一市场情景内所有产品价格一起变动，报价同时决定客户愿意接受的追加量；不会把各产品最乐观的条件拼成一个不存在的组合。
- 推荐组合必须在全部情景下都能交付；逐情景收益与按权重汇总的期望收益只来自同一方案。
- 加入或排除某单后并排比较收益、闲置原料/机时和短缺，并解释真正用满的等级或机时。固定成本和单位变动费率不随方案改变。
- 不可行时说明冲突的等级（含可降级来源是否用尽）、机时以及报价让步条件。

采纳时若原料/能力、需求/价格或固定成本已变化，`portfolio.adopt` 拒绝写入并要求重新分析；通过后按与承诺校验相同的分配算法写入 `bookings`。

## 运行

使用 Python 3.11.x，无需安装第三方包。

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q .
python3 app.py demo
```

`inspect`、`demo` 和 `portfolio` 使用相同业务入口；`--as-of` 选择已知日期，`--data` 可选本地数据文件，`--output` 可将本次业务核对结果写入文件。默认数据位于 `fixtures/data.json`，默认日期为 `2026-11-17`。

## 容器

`Dockerfile` 固定到 Python 基础镜像内容摘要。构建后运行不联网：

```bash
docker build -t harvest-mix:local .
docker run --rm --network none harvest-mix:local python -m unittest discover -s tests -v
docker run --rm --network none harvest-mix:local
```

## 数据与业务契约

样例记录全部为本地合成数据，不代表真实农户、市场成交或实际试验结果。日期采用 `YYYY-MM-DD`，有记录时点的条目以 `recorded_at` 表示系统已知日期；同一业务键存在多个修订时选已知范围内最新记录，同日由 `revision` 区分，`withdrawn` 表示撤回。可修改样例验证业务边界，不能将演示数据的统计方向视为真实结论。

原料分级yield_fraction之和允许小于1，其差为分级损耗。conversion_yield为投入到产品的得率，minutes_per_kg按产品重量计。降级关系有方向。报价金额单位为分，step_kg是整包装步长，0表示不接单。固定成本不随组合改变。

接口细节见 `docs/contracts.md`。测试使用各自的内存副本和临时目录，不修改原始数据或依赖固定端口。
