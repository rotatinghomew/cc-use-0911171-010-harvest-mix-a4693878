# 业务数据契约

原料分级yield_fraction之和允许小于1，其差为分级损耗。conversion_yield为投入到产品的得率，minutes_per_kg按产品重量计。降级关系有方向。报价金额单位为分，step_kg是整包装步长，0表示不接单。固定成本不随组合改变。

## 市场情景与数量响应

`market_scenarios` 中每个情景给出**所有**产品的价格因子（`<product>_price_factor`，缺省为 1）和权重。权重按合计归一化。同一情景内各产品价格一起变动；分析只在同一情景内组合价格与数量，不会把不同情景的最乐观条件拼成一个方案。

客户的追加量由报价共同决定：报价变化按 `price_sensitivity` 缩放需求上限（`demand.quoted_volume`）。可执行交付量同时受最低交付量、需求上限、报价响应量和整包装步长约束（`demand.quantity_options`）。因此“接单量”不是与价格无关的自由变量。

## 组合分析与承诺的一致性

- `production.allocate` 是唯一分配入口：按等级供应与机时能力做确定性最大流分配，尊重单向降级。分析（`costing.evaluate`）与实际承诺校验（`costing.check_commitments`）都调用它，因此对同一组订单给出相同的消耗、闲置和短缺。
- 已有 `bookings` 先占用原料与机时；组合分析只在剩余能力上比较（`portfolio._remaining_basis`）。
- `portfolio.recommend` 只推荐在**全部**市场情景下都能交付的方案。逐情景收益与期望收益均由同一方案、同一情景内价格得出；不可交付的情景不计入期望，也不会被静默忽略。
- `portfolio.compare` 对业务员指定加入/排除的意向单重新求最优并排比较，给出与基准的收益、闲置原料/机时、短缺数量差异；固定成本标记为不变。
- `portfolio.bottlenecks` 只把实际用满的等级/机时列为瓶颈，并给出粗算的边际价值用于排序；不进入收益口径。可降级来源与方向一并说明。
- `portfolio.unchanged_costs` 列示固定成本与单位变动费率；变动成本总额只因交付量与品种结构变化。

## 不可行意向单

不可行时返回 `diagnosis`，列出冲突的等级（含可降级来源是否用尽）、受限机时，以及报价导致的追加量冲突；若指定单之间存在多个交付量组合，返回 `forced_alternatives` 并汇总冲突，而不是只展示某一个组合的短口。

## 采纳与过期建议

`portfolio.adopt(data, recommendation, expected_resource_id)`：

1. `recommendation["resource_id"]` 必须等于调用方持有的原料/能力依据；
2. `recommendation["analysis_id"]` 必须等于当前原料/能力、需求/价格与固定成本的指纹；任一变化都要求重新分析，不把过期建议写成订单；
3. 按当前数据重新做承诺核对，通过后才写入 `bookings`，并记录 `acceptances`。已承诺的意向单不能重复采纳。

`analysis_id` 覆盖评分所依赖的全部输入；`resource_id` 只覆盖原料与能力。两者同时校验。

## 现有组合入口

`app.inspect(data, as_of)` 是只读检查。`app.portfolio_report(data, as_of, include, exclude)` 通过 `portfolio.assets_report` 一次给出推荐、指定单比较、瓶颈与不变成本，同样只读。CLI 对应 `python3 app.py portfolio --include O2 --exclude O1`。

输入为本地记录集合，输出为 JSON 可表示的字典；不修改输入。领域接口会对不符合业务口径的数据抛出 `ValueError`。缺失、不足和不适用不应伪装成零数量。组合总数超过上限时抛出 `ValueError`，要求用加入/排除缩小范围，而不是截断枚举后给出看似最优的结论。
