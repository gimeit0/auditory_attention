# Job 680910：执行映射类型校验失败

日期：2026-09-09。范围为用户失败日志的诊断与本地最小复现；不修改 v8
候选或原评估 v4，不新建发布版本，不重新冻结或提交。

## 远端回传事实

诊断 v8 / Job 680910 的 stderr 明确为：

```text
diagnostic error: unsupported execution mapping type: path=root.class[__init__].resolved[os.environ]; type=os._Environ
```

外层 primary_error 为 execution / EXECUTION_FAILED / child exit is nonzero: 2；
lock_acquired=true，post_errors=[]，matrix_status=null。产物只有 ENVIRONMENT、
PRECHECK、POSTCHECK、RUNNING 四个 JSON，没有已完成的数值矩阵/参考推理产物。
READ_RC=0 表示读日志成功，EVIDENCE_RC=2 保留失败返回值。用户此次截取未包含
VERIFY_RESULTS 完整 JSON 或失败标记 SHA，不能补造这些未回传字段。

本次已回传证据 SHA：

- v8 freeze：`1cdb55adbeed5118b9e13f816a5ea1c096125bb447ad61a46dcab96a172c266c`。
- Job 日志：`a0c2c807b444e9c4860ba39c45ffa46ba0c17e2e4b91449324d23d7490cf75e6`。
- artifact inventory：`0085b94107d7ea6a3dc8727eb2d1f532e27a7bb1b0def651e32be9b875b5ed7a`。
- PRECHECK 与 POSTCHECK（各 69770 bytes）：`f103b0d1bf1a8d88ffa8fa28fafc6432ecca1d1d4537b7557983218ce18efa81`。
- submission receipt（531 bytes）：`2e7b13c99077e5fb17c642bba36cd2f5bc0b2933279a604a2f4248899b001912`。

PRE/POST 哈希一致且 post_errors 为空，说明记录范围的后检未报告改变，不能
外推为整个共享文件系统未变。此次是诊断器拒绝映射类型，不能当作模型训练
失败、checkpoint 损坏或原 smoke NLL 偏差的解释。

## 本地源码检查与复现边界

固定 v8 诊断器 SHA：
`6624cda3d7ea21121599f6c2c05c46c060a1e647d2256991459735ca24d49182`。
`_container_execution_identity` 的 Mapping 分支只接收 dict 派生对象与精确
MappingProxyType，其他映射直接报错；os.environ 的 os._Environ 不在支持范围。
类的 callable graph 检查会扫描构造方法的属性引用；读取 os.environ 这个
属性就足以触发拒绝，不需要真正执行构造器或读取环境变量的值。

与冻结快照 SHA 一致的本地模型源码将 DioticAttentionDataset 类保存为
self.dataset；该数据集 __init__ 中存在
`clips_dir = os.environ.get("CV_CLIPS", clips_dir)`。这是一个有源码依据的
触发入口。日志路径没有具体拥有者类名，不能只凭这个短路径断定远端唯一
触发者就是此类，也不能保证接受它后不存在后续兼容性错误。

计划用 2026-09-09-job680910-environ-probe.py 校验三份源码 SHA，仅提取上述
赋值 AST 到最小构造器，调用指纹函数而不实例化该类。另测试普通 dict、
MappingProxyType、os.environ 本体，以及保存该最小类的 torch.nn.Module。
不输出环境变量名称/值，不遍历 os.environ，不读取 checkpoint/音频、不做
GPU 推理。复现只证明此兼容性缺陷，不等同于完整真实模型的端到端验收。

## 本地实际结果与下一步建议

探针在 Python 3.11.15 / torch 2.12.1 的独立本地进程完成，退出 0 表示
预期错误被复现，不表示诊断已修复。三份源码固定 SHA 均通过；模型数据集
类绑定在第 58 行，数据集构造器环境引用在第 158 行。普通 dict 与只读
mapping proxy 被接受；os.environ 被拒绝。源码衍生最小类的 callable graph，
以及将该类保存为 dataset 属性的最小 torch.nn.Module，均复现与远端一致的
`root.class[__init__].resolved[os.environ]; type=os._Environ` 报错。

日志：2026-09-09-job680910-environ-probe.log；探针 Ruff 通过，v8 十二候选
文件 SHA 复查全 OK。没有完整模型构造、环境内容转储、远端调用、训练或
checkpoint/音频读取；没有修改生产代码。最小构造器只定义、不执行。

已确认的直接阻塞是环境映射与执行指纹校验不兼容。上次 deque/torch.Size
覆盖仍不足以保证真实模型相关类的构造依赖可通过。这是现有本地夹具的
覆盖缺口；不应再次把合成测试全绿当作真实 A100 验收。

如进入修复，应在独立候选中设计环境映射的明确处理边界，保持对象替换、
内容变化和方法篡改可检测，拒绝任意未知 Mapping/恶意子类。环境可能含
敏感值，不应把完整环境内容放进指纹日志或报错，也不能简单放行/跳过整个
映射。补充真实源码相关构造器和模型属性覆盖，明确本地缺少的完整模型/
GPU 验证范围，再决定远端部署。保留 v8/Job 680910 证据，不改变科学数值
容差、AMP/TF32、checkpoint 或 frozen bank。此轮尚未实施该修复。
