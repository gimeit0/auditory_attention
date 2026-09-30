# 真实严格加载后的编译回调登记候选

2026-09-13更新。**本地24项通过；真实超算Job703751登记检查及本地原始证据复核通过。**
见[执行与验收记录](../../evidence/2026-09-13-real-registration-cpu-job.md)。
不是GPU版本、生产worker签发或三个checkpoint的比较结果。

## 与上一步的区别

Job703415验证了合成模型上原受控编译接口的完整34次前向及冷进程端点一致。
更早的真实formal40 CPU检查只安装/移除了StreamObserver的27个阶段hook。
本候选将严格加载后的真实对象连接到Job703415使用的**原CompiledLease**：
42个计划位置、27个模块，加外层pre/post，共29个实际回调。

- `admission.py`：真实入口自己调用原verified evaluator的strict_load_model，
  不接受调用者提供的模型或“这是生产对象”的布尔开关。检查原production
  capability、24固定文件、formal40 SHA、snapshot loader签发的真实类对象，
  严格加载后60条参数/缓冲区与父A2预前向状态逐SHA比较。
- 安装原CompiledLease后签发原冷编译器身份，检查状态/RNG/runtime不变，
  然后撤销身份并移除全部回调；不调用模型、音频变换或原生产prepare函数。
  原生产CUDA门禁保留。本侧路只返回检查数据，不返回可执行的prepared worker。
- `probe_cpu.py`：**仅计算节点入口**，固定B2，要求1CPU/4GiB/TINY、
  无GPU分配、私有/tmp scratch和原只读共享锁。没有SSH、sbatch或重试能力。
  已由独立固定包在Job703751单次运行，不要在登录节点直接执行或再次提交。
- `test_admission.py`：合成42位置结构测试；有意不加载真实架构、不运行forward，
  不伪造本机torch2.12.1为远端2.1.1。真实冷编译器签发未由本地测试覆盖。
- `validate_local.py`：120秒上限的新本地子进程、17份源/输入SHA清单、完整日志
  和回执。默认仅本地测试，无联网、上传、冻结或提交。

## 本地结果与命令

[实际回执](../../evidence/real-registration-local-20260913T051944Z-n3u5umyq/receipt.json)：
LOCAL_REGISTRATION_CANDIDATE_VERIFIED、24项零跳过、rc0；Python3.11.15、torch2.12.1。
两个cell保持原目标和32条/16→1计划；本地登记和清理不改变状态/RNG/runtime。
错误类、缺失位置、旧hook、绑定/handle替换、非eval/未冻结、伪造capability、
无原worker的forward、登录节点或不符资源声明均被拒绝。Ruff通过。

SOURCE_MANIFEST.json SHA：
`4c72fc9779fe48373908eca2638b69bcf5ed173a9cd9db52062b119128a876d5`。

```sh
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_real_registration_20260913/validate_local.py
```

这条命令可重复运行，只生成新的本地测试证据目录；不会重提703415。

## 已执行的远端许可与验收

用户另行批准1CPU、4GiB、最多30分钟、无GPU后，已使用独立root、26文件固定包、
test-only和单次提交控制运行Job703751。COMPLETED0:0，实际2分32秒；没有自动重试。
本次仅运行B2计划的严格加载和登记检查，forward_calls=0、captures=0；
A2与真实动态42位置调用顺序不由这次空登记证明。

真实torch2.1.1的原编译器身份签发/冷状态/撤销、严格加载报告、父状态、29回调/清理、
无CUDA和原文件前后SHA均通过。10份回传原始工件及26份固定源码经本地独立复核。

登记已经通过，但production_preparation_validated=false、ready_for_gpu=false仍成立。
原正式生产准备函数及GPU观测器接入、真实输入重建/父结果重放、A100/Inductor
端点无干扰检验仍未完成。不得把CPU绑定检查当成NLL差异原因或最终优劣结论。
研究角色保持REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST。
