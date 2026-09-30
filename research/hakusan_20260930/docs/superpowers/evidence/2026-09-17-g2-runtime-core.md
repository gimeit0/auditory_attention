# G2运行控制与原语义离线验收：本地证据

2026-09-17。完成库级生产worker/矩阵控制和保存结果的原语义复核；没有执行真实GPU矩阵或总体checkpoint比较。

固定证据目录：`g2-runtime-local-20260917T060959Z-yhugq8o2`。

- 31份来源快照、45份绑定输入；运行前后相同。
- 30项检查，0失败/错误/跳过；子进程74771，1.276秒，退出0。
- `VALIDATION.json` SHA256：`cd7a57be6cc3274da4e9d07c270339e6cd4e76b6883207455f453c72a12748b2`。
- `tests.log` SHA256：`d3e1bb52e3f028f4c289af38c638886f8c1e9f5bbb450fc13a09db8daab965b2`。
- 单独只读复查返回 `LOCAL_G2_ARCHIVE_RECHECK=PASS`、`LOCAL_G2_RUNTIME_CORE_RECHECK=PASS`。

检查范围：14项矩阵控制模拟、5项worker终态/清理模拟、4项环境构造、7项既有合成数组的原pass语义验证及拒绝检查。
没有把这些模拟或合成输入标记为生产模型；未运行新的模型forward。

实现保留原strict-load、完整trial身份、承诺、状态/RNG和修改检查。独立校验新增父进程PID/env、完整新freeze与旧科学输入关系、历史B2原始scene/cue关系；R/C编译证据仅在实际生成并执行后才可接受。
完整真实生产验收路径尚未执行。矩阵固定R/C/D/E顺序；数值差异继续，执行异常停止；候选固定E/C/D/R，不依据准确率挑选。
候选必须再满足旧B2解释和冷重复条件，不能直接用于全量比较。

当前依赖SHA：

| 文件 | SHA256 |
| --- | --- |
| runtime.py | cfbd9280e53294a6b1ac3a9534a31f0dc5f9b839a2c6b0348ee59f9d59467507 |
| evidence.py | bd69ecec9426649d26c3df4a75765ff394ef5fa0369b0d3c49afe42ea104d4d8 |

远端查询另有失败：沙箱DNS失败后获准尝试实际SSH，但认证返回255及 `Permission denied (publickey,password,hostbased)`。
没有取得新的队列、分区或生产目录状态，不能声称队列为空或目录不存在。未重新提交721086或任何旧作业。

下一项是有界真实子进程入口及发布/请求/调度绑定；随后仍需新freeze、明确GPU预算和真实32条执行。旧部署包与证据不改写。
