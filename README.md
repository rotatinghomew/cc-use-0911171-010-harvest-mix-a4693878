# harvest-mix

原料分级、意向需求及逐单资源承诺核对。

## 当前产品

这是可独立运行的本地分析应用，提供业务记录核对和确定性基线结果。各业务职责可直接作为 Python 接口调用，`app.py` 负责组合一次只读业务检查。结果可保存为 JSON，不依赖远端服务。

- `production.py`：分级可得量、降级关系及时间能力。
- `demand.py`：订单最低交付和报价响应。
- `costing.py`：固定与变动成本及实际承诺核验。

## 运行

使用 Python 3.11.14，无需安装第三方包。

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q .
python3 app.py demo
```

`inspect` 与 `demo` 使用相同业务入口；`--as-of` 选择已知日期，`--data` 可选本地数据文件，`--output` 可将本次业务核对结果写入文件。默认数据位于 `fixtures/data.json`，默认日期为 `2026-11-17`。这些命令仅展示当前已经存在的能力。

## 容器

`Dockerfile` 固定到 Python 基础镜像内容摘要。构建后运行不联网：

```bash
docker build -t harvest-mix:local .
docker run --rm --network none harvest-mix:local python -m unittest discover -s tests -v
docker run --rm --network none harvest-mix:local
```

## 数据与业务契约

样例记录全部为本地合成数据，不代表真实农户、市场成交或实际试验结果。日期采用 `YYYY-MM-DD`，有记录时点的条目以 `recorded_at` 表示系统已知日期；同一业务键存在多个修订时选已知范围内最新记录，同日由 `revision` 区分，`withdrawn` 表示撤回。可修改样例验证业务边界，不能将演示数据的统计方向视为真实结论。

原料分级yield_fraction之和允许小于1，其差为分级损耗。conversion_yield为投入到产品的得率，minutes_per_kg按产品重量计。降级关系有方向。报价金额单位为分，step_kg是整包装步长，0表示不接单。固定成本不随组合改变。当前承诺采用确定性逐单核对，不做销售组合寻优或风险排序。

接口细节见 `docs/contracts.md`。测试使用各自的内存副本和临时目录，不修改原始数据或依赖固定端口。
