# E0生产候选入口、便携参考与单次held提交（2026-09-24）

状态：E0_CANDIDATE_LOCAL_CHECKS_PASS。用户要求补齐的三项已实现并打包；未上传、未提交、未执行真实checkpoint/A100验收。不将本地测试称为E0_ENDPOINT_PASS。

## 交付

1. [冻结候选包](release_20260924_v1/package)：`e0_entry.py`先做全文件SHA/清单/资源合同校验，再进入`production_e0.py`。coordinator绑定提交回执和Slurm job；A/B独立隔离Python进程各自调用audited_session→strict-load→原生音频provider→G5/历史桥接阶段。退出加载上下文、完成输入postcheck后才发布worker成功记录。加载、桥接、G5、观察摘要、npz、日志都有独立文件和绑定。
2. `reference/reference.npz`（约906KiB）与`REFERENCE.json`：从重新核验SHA的728520归档提取288条model-condition参考（96 correct+3×64 controls），包含ID、FP32 logits和恢复为FP32的历史NLL。包中保留完整原归档SHA、模型SHA及布局SHA；不依赖Mac路径，不使用新模型输出来生成期望值。
3. `submit_e0_once.py`及`run_e0.sbatch`：固定独立部署路径；独占state目录，检查相关队列、test-only，再一次sbatch --hold。GPU-1A/student，1 nvidia_a100、8CPU、64GiB、30分钟、no-requeue。持久化INTENT与原始response，响应不明/超时禁止重试；不自动release、不修改GRES。runner比对Slurm实际执行脚本与包内脚本字节。

受审core原文件直接复制，SHA未变。快照源码按原snapshot manifest的provenance_files逐文件验证，拒绝额外Python文件/bytecode；原生回调和架构另做固定SHA检查。执行与postcheck同时失败时保留两者错误信息。

离线验收重新读取所有输出，核对跨进程/端点/观察器逐位结果、α0 cue independence、NLL复算，重新核对历史桥接及加载报告、job/PID/reference绑定。最终E0_COMPLETE仍只说明工程验收，不表示α科学结论或独立测试集结果。

## 已执行的本地验证

- 全套104项测试通过（9.096秒），包含模拟生产worker-body的正向归档/桥接、postcheck失败不发布成功、首轮历史桥接错配即停止。该组生产body测试明确使用合成加载上下文与参考，不伪装真实模型证据。
- 新提交测试全部mock scheduler，没有调用sbatch/squeue：核对固定预算、一次held、相关队列阻止、test-only失败、未知response、超时留证且不重试。
- 便携参考与原Job728520选定logits/NLL逐位一致。
- 冻结包在项目外工作目录以`python -I -B ... check`通过；隔离导入生产模块通过且没有模型加载；runner的`bash -n`通过。
- 首轮新增打包测试拒绝了macOS系统临时路径中的/var链接；修正为禁止包根及包内链接，未放宽数据哈希/数值验收，之后全套重跑通过。

## 固定身份与操作说明

- Release SHA：`05a1271fa398bf2c0006a9486ca09ffae6d9bd8759f7ecb54522460c3c57a9f8`
- Reference manifest SHA：`448b9dc4ed4a125cc557ce5b5e3fade210f0f8554aeb73af141411f40edbeee9`
- [构建回执](release_20260924_v1/BUILD_RECEIPT.json)
- [部署位置、校验和单次提交命令](release_20260924_v1/README.md)

## 下一动作与限制

下一步是只读远端预检与独立目录部署/哈希复核，然后单次held提交，审查Slurm实际资源及runner后单独release。不要运行旧v8或其它历史诊断提交脚本。当前无作业号。

尚未验证真实torch2.1.1+cu118环境的整包运行、真实checkpoint/音频与A100数值；这些是E0任务本身的验收内容，不是本地合成测试能提前证明的事实。GPU开销不由CPU耗时推算。

父进程的离线验收仍是协作式时限，子进程组执行受1500秒总截止，整个作业最终由Slurm30分钟限制。没有实现自动release/自动typed-GRES修正；站点改写后必须停在held审查。

本轮无SSH、上传、checkpoint读取、GPU任务或训练。冻结包不原地修改；任何后续修复都须新版本、重新测试及核验SHA。
