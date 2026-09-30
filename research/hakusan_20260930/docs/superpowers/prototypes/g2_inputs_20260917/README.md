# G2 新代码身份与固定科学输入的绑定

2026-09-17。本地候选组件，不是可提交的完整 GPU 包；没有 freeze 写入或 scheduler CLI。

`verify_relation` 比较新的各 profile 冻结记录和已固定 v18/Job685198 数据依据：

- R/C/D/E 使用自己的已固定源 SHA、protocol 和目录，不能以旧freeze授权新代码。
- trial完整身份/顺序/bank行、所有音频的用途/哈希/大小/权限、snapshot、标签、模型与v4合同完全一致。
- 只允许新执行身份、单独校验的四个代码记录，以及跨次访问的inode/device/mtime不同。
- 四个代码文件均与调用者提供的新发布源码逐字节绑定；diagnostic与trace另有固定哈希。
  其余发布代码仍须由外层发布/授权检查绑定，不能把调用者提供的字节当作批准。
- 拒绝重复JSON键、非规范JSON、NaN、超预算输入、缺项、旧代码和跨profile混用。

`WorkerInputs` 的实际运行入口要求模块位于自己声明的新超算root，保留原生产解释器/冷进程
claim、`_load_worker_inputs`、`_revalidate_worker_inputs`；加载前后另核对四个物理源码和freeze。
不会伪造 production capability、替换原加载器或跳过 live audit。
评价锁、发布身份、调度预算/授权、scratch、scene scope、模型准备和输出归档仍由未来生产worker负责。

## 本地验收

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_inputs_20260917/validate_local.py
```

30秒监督器上限，16项测试、源码副本、前后哈希、完整输出与回执；加 `verify 证据目录`只读复查。
测试使用真实旧数据清单，但新freeze身份及两个未来启动文件是**明确标记的合成测试数据**。
没有在超算创建新freeze，没有执行原生产loader，没有加载模型/GPU。
保留原loader调用的AST检查不等于真实loader集成测试通过。

当前必须先取回Job721086的原生R/C结果，再确定后续生产worker发布方案。
真实模型加载、Linux scratch/spill连接、独立工件验收和GPU矩阵仍未完成。
本组件不能改变1e-6标准，也不能替代最终三模型10k/controls对比。
