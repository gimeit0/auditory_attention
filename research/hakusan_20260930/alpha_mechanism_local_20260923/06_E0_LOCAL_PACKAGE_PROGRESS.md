# E0执行包本地进度（2026-09-23）

状态：E0_LAYOUT_REFERENCE_LOCAL_PASS，**不是E0_PACKAGE_LOCAL_PASS**。

## 本轮实际完成

- 近期计划已修正：E1共26,600条；E2基础约167.7分钟且提交前审分批；文件身份与阶段身份分离；E1增加证据不足分支并去除未实现的lapse排除承诺；对齐容量/吞吐决策补充；本地不等待SSH；四周为有条件窗口。
- `E0_LAYOUT_96.json`：96个ID、6个原完整批、各条件原批索引和目标标签均已物化。SHA `f28160c857512c90533837d7a4f54a761a6deef6d6cf86aafadecd34138f7e90`，基于原提案，不是生产执行授权。
- `e0_layout_reference.py`：只读核验归档四文件SHA，按bank中control索引映射提取formal40历史输出；不能直接把trial_id当2000行control数组下标。未重算模型预测。
- 288条历史参考（96 correct + 64×3 control）标签与logits一致；FP64离线NLL复算最大绝对差约1.25e-6，低于提案固定复算容差。详细四条件摘要见`E0_LOCAL_REFERENCE_REPORT.json`。不代表新的α输出通过桥接。
- `test_e0_layout_reference.py`新增6项测试，总36项通过：历史参考/NLL、布局改动、1bit/dtype/顺序错配、NLL损坏/非有限、6048条身份计数、少项/重复/错mode/错序。
- 首次读取发现control CSV标签使用整数值浮点文本（如786.0），改为先核验有限整数再与argmax比较；未改原结果或容差。

6048条演练当前是**预测身份清单计数/顺序校验**，尚不是6048条完整模型输出归档全流程测试；不能混称。

## 下一步与待完成项

1. 单模型生产候选：复用受审strict-loader及原生预处理，独立bypass；不改原三模型执行器的身份声明。
2. 把布局、历史参考和α适配接到阶段执行/失败记录，补G0–G7全部门槛；当前只有局部离线校验函数。
3. 完整归档合成回归，包括预算耗尽、失败中断、文件损坏与观测清理；当前不提供可提交入口。
4. 整包本地验收后，再请求恢复远端和具体部署/原生CPU测试授权；GPU按已列预算单独审批。

本轮无checkpoint加载、SSH、上传、GPU或训练。2k选择器尚未实现/冻结，不把未来工作登记成已完成。

复现：

```bash
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover -s alpha_mechanism_local_20260923 -v
/opt/anaconda3/envs/audattn/bin/python -B alpha_mechanism_local_20260923/e0_layout_reference.py
```
