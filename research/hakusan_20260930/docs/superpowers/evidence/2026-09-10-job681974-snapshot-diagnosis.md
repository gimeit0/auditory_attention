# Job681974 模型状态快照错误诊断

v10已发布且失败证据保留；本项仅诊断，不修改远端工具、checkpoint、bank，
不重提该作业。完整三模型比较尚未完成。

实际失败：model state snapshot failed，包装错误丢失了stderr里的具体cause。
验证结果DIAGNOSTIC_FAILURE_RECORDED，PRE/POST匹配、matrix=null。
详见v10-remote-deployment.md固定marker/log/inventory SHA。

只读同版本API探针：torch2.1.1+cu118的真实小型nn.Linear(1,1)实例，未forward，
`_parameters`、`_buffers`、`_modules`三个注册表均为collections.OrderedDict。
这与本机torch2.12.1使用dict不同。已发布v10 `_snapshot_model_entries`使用
`type(registry) is not dict`拒绝，而前面的模块发现/状态身份多数用
`isinstance(..., dict)`；此不一致可导致前置完整指纹通过而字节快照失败。

还发现需要一起审查的相邻路径：静态属性注册表查找、audio transforms的
额外模块发现仅接受精确dict；多个registry读取用dict.items，可能忽略
OrderedDict.move_to_end的实际顺序。不能只放宽snapshot一行而遗漏同类问题，
也不能任意接受Mapping或执行可覆盖迭代器。当前是源码/API证据，不把它
直接宣称成完整模型失败的唯一原因。

已准备临时同版本正式formal40 CPU探针：完全使用已发布v10固定源字节，
严格加载后记录注册表类型计数、调用原_snapshot_model_entries，并在外部
显示有界exception cause链。无forward/GPU/新发布/freeze/提交。

实际完整模型CPU结果（REMOTE_CPU_PROBE_RC=2）：严格加载61个state keys、
训练参数覆盖1.0、67个已发现模块；201个注册表全部为collections.OrderedDict。
随后原_snapshot_model_entries复现model state snapshot failed；其直接cause为
model state registry is invalid，定位已发布源line4704。由此确认此次快照的
直接失败原因，而不是模型权重缺失或数值canary不通过。

下一候选v11：保留已发布v10及681974全部证据，统一精确dict/OrderedDict注册表
读取，使用原生顺序；覆盖静态注册属性、列表内音频模块发现、状态快照及
重排/替换/原位改写检测。拒绝不支持的注册表子类，不调用用户覆盖的迭代协议。
不改变科学运行设置、600000工程work预算或原始NLL容差。先在本机回归，再在
真实torch2.1.1/formal40上验证完整状态快照、RNG及重复指纹，之后才评估GPU提交。
