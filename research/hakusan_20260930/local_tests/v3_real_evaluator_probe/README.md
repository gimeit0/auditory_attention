# 真实 v4 evaluator 的 v3 依赖记录复现（2026-09-08）

命令（工作区根目录）：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B local_tests/v3_real_evaluator_probe/probe.py
```

本地实际执行，退出码 0（探针成功输出差异，不表示生产审计通过）。
读取真实冻结 evaluator 源码并核对 SHA：
`31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4`。
调用未经修改的诊断 v3 真实加载器与图记录函数。

## 观察

- immediate_second_read：所有函数 anchors_match=true；但
  `_frozen_import_context`、`strict_load_model` 的 graph 记录不一致。
- 第一处容器长度 1100→1099；差异显示加载器临时模块
  `_verified_v4_evaluator_<随机标识>` 被移除。
- after_pandas_read_csv：anchors_match 仍为 true；相同两个入口 graph 不一致，
  对应容器长度增为 1436。数字取决于本地解释器和导入环境，不是验收固定值。
- 探针按元组位置比较，删除一项会造成大量后续索引错位；报告中的差异数量
  不能解释成数万个独立函数被修改。

## 源码证据与结论

冻结 v4 的 `_frozen_import_context` 读取和修改 sys.modules；
strict_load_model 可达该上下文。v3 加载器在临时模块仍登记于 sys.modules
时保存 callable graphs，随后 finally 中执行 sys.modules.pop(name, None)。
因此加载器自身正常清理就使之后的精确图比较失败；随后 pandas 导入继续
改变该全局模块表。错误无需任何模型加载或预测就可以在本地复现。

这定位了远端同一检查的一个确定性失败机制。没有完整执行真实远端
read_frozen_context/清单验证，也不声称排除了后续其他差异。

## 安全边界与后续

### 生命周期回归：发现尚未解决的正向失败

执行 `test_lifecycle.py`（相同 isolated audattn Python）。原型七断言仍通过；
新增 unittest 4 项中 3 项通过、1 项失败，退出码 1：

- 通过：真实 frozen_scene_context 退出后模块表恢复，旧 callback 被拒绝。
- 通过：冻结源文件内容变更在真实导入时被拒绝。
- 通过：活动期间替换受保护模块会改变 graph（仅差异检测，不是完整 worker 拒绝）。
- RED：合法进入冻结作用域后 evaluator seal 仍然改变。原因是原型虽然允许
  无关新模块，却仍将授权加载的 selftrain 模块视为不可变基线的变化。

夹具使用真实 v4 evaluator 图和真实诊断 frozen_scene_context，但场景源是
本地最小临时文件，不加载真实模型。未修改生产包或远端。

该失败是下一项修复的明确验收条件：不可通过无条件刷新基线解决；需要将
受保护模块绑定到可信作用域 nonce 和冻结源清单，活动期间验证实际模块身份，
退出后撤销，正常进入不能改变 evaluator 的代码身份记录。原型仍不可部署。

### 实验性策略实现（非生产候选）

新增 candidate_policy.py，在独立进程中加载未经修改的 v3，并只替换该进程
内的容器身份函数。没有修改已发布源码。策略固定既有模块绑定身份，并单独
跟踪测试配置的受保护前缀；无关新模块不再扩展整张模块表指纹。

实际运行命令：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B local_tests/v3_real_evaluator_probe/candidate_policy.py
```

退出码 0，7 个断言通过：真实加载器清理允许、pandas 导入允许、无关模块
新增允许、受保护模块插入检测、既有 json 模块替换检测、函数替换检测、
恢复原状后图匹配。测试的是差异检测，不是完整生产异常拒绝链路。

明确剩余风险：保护前缀是实验配置，不能替代冻结源清单；合法受保护模块
进入/退出作用域仍会改变图，必须由受控作用域验证处理；新增依赖模块尚未
自动纳入后续保护边界；未测试模型加载、lazy helper、sys.path/cwd 生命周期。
因此本原型不可上传、不可直接复制到生产函数，也不能据此宣布问题已修复。

下一项：从冻结源清单推导保护范围，设计作用域进入前/活动中/退出后的
身份验证，覆盖合法切换及活动中篡改，同时验证新增依赖绑定。完成后才考虑
独立生产候选与全套测试。

### 第二轮对照检查

探针新增并实际执行两个对照（退出码 0）：

- 在进程内加入完全无关的临时模块，两个入口的 graph 都发生变化，复现
  正常模块表更新被误报。finally 删除探针模块。
- 将 facade.strict_load_model 暂时替换为另一函数，anchor_changed=true；
  finally 恢复原函数。这仅证明身份差异可检测，不是完整篡改拒绝链路验收。

源码复核还确认 frozen_scene_context 会临时移除受保护模块、安装 finder，
退出时恢复模块；worker 校验同时绑定场景作用域 nonce、导入来源记录与模型
attestation。后续修复必须保留这些机制，不能把整个模块表的内容恒定当作
代码恒定的替代品。

### 下一轮实现前的验收清单

1. 正向：真实 evaluator 刚加载后、pandas 正常导入后、冻结上下文进入/退出后
   均不误报。分别用冷进程验证，不能只在已经导入完毕的进程里测试。
2. 负向：替换公开函数、修改其 __code__、替换可达 helper 均拒绝。
3. 负向：替换活动冻结作用域中的受保护模块、改变源文件 SHA、改变导入
   来源均拒绝；作用域退出后的过期凭据不得复用。
4. 不接受无条件重新登记基线、跳过整个 graph、全局忽略 sys.modules 的修复。
5. 先在未发布的本地候选中实现明确的可变状态策略，保留 v3，跑真实 evaluator
   生命周期与现有套件；通过前不生成上传步骤。

未修改任何 v1/v2/v3 已发布包或冻结 v4；未加载 checkpoint，未做 GPU 运行，
未创建远端目录、freeze 或 job。新增内容只有独立本地探针和说明记录。

下一步应设计“代码身份”和“导入上下文可变状态”的分离验证，并建立真实
evaluator 正向与篡改负向测试。不能仅刷新基线、关闭 graph 比较或忽略所有
sys.modules 内容来规避错误；必须保留冻结 src/selftrain 及可调用对象的身份
验证。先证明正常导入可通过、被替换函数/受保护模块仍拒绝，再考虑新候选。
