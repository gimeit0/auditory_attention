# G2 完整双轮配对检查：本地完成，同版本编译验证待授权

2026-09-16，承接用户“go on”。本轮没有SSH、远端查询、上传、freeze或新作业。
目标仍是formal40与作者checkpoint的冻结10k对比；当前工作属于G2评估路径工程验证。

## 本轮完成

新候选：[说明与入口](../prototypes/g2_compiled_check_20260916/README.md)。
旧G2准备候选、CellBridge、编译取证器、v19保护逻辑和历史回执均保持不变。
新包固定绑定15份旧来源，连同6份新来源/说明，共21份文件形成独立源码快照。

补齐的是此前缺少的**完整双轮参考/观测配对**，不是又一次仅查版本/API：

- 每个profile分别在两个独立冷进程中运行原受保护路径和CellBridge路径；不复用模型或编译缓存。
- 每个进程固定32条合成完整身份、batch16→1、AMP关闭、34次模型调用、一次fixture strict-load。
- 两轮均保存8个输入/输出边界以及pred_label、NLL、p_target、p_probe_distractor四项逐条输出。
- 校验模型状态、完整RNG记录、六项运行设置、身份顺序、源包SHA、进程PID和输出内容。
  返回的RNG pickle字节只做内容校验，不反序列化。
- 原始PassResult承诺由旧函数验证后保留摘要；新简化输出包不冒充完整生产PassResult归档。
- 复用已固定的有界进程监督器，单子进程60秒、本地总180秒、日志上限4MiB；失败不自动重跑。

R/C原生候选只允许Python3.11.5/torch2.1.1+cu118、单CPU Slurm计算分配。
使用原compiler lifecycle和已固定的目标编译器/生成代码执行取证器，不替换编译回调或跳过guard。
**此路径尚未在同版本环境执行，不因本地D/E通过而认定R/C通过。**

## 最终本地结果

Python3.11.15 / torch2.12.1，CPU单线程、CUDA不可见。
四个冷进程按D-reference、D-observed、E-reference、E-observed依次完成，总33.709秒。

| 配对 | 单进程样本/调用 | 两轮所有已保存数组 | 最大绝对差 |
| --- | --- | --- | --- |
| D参考 vs D观测 | 32条 / 34次 | 逐字节相同 | 0 |
| E参考 vs E观测 | 32条 / 34次 | 逐字节相同 | 0 |

最终18项测试通过，0失败、0错误、0跳过；5份新Python文件AST语法检查通过。
拒绝测试覆盖重算哈希后的NLL改动、类别翻转、身份/顺序/缺轮、PID/缓存复用、
AMP/运行设置/seed改变、模型/RNG改变、错误release/nonce、夸大生产/编译结论等。
实际调用原生child的错误版本入口，在模型准备前停止，未生成成功结果。

首轮单元测试曾把身份字段数误写为11，实际固定schema为10；已修正并完整重验，
没有删除身份字段或放宽保护。首轮双轮配对本身通过，早期快照保留于
`g2-paired-local-20260916T043304Z-h3psy6z8`，不作为最终候选验收回执。

## 最终证据与复查

目录：[g2-paired-local-20260916T044126Z-o3f8g1xe](g2-paired-local-20260916T044126Z-o3f8g1xe/)。

- [RELEASE.json](g2-paired-local-20260916T044126Z-o3f8g1xe/RELEASE.json)：
  `70ed80ca0d3a39d562bcf06a289d259eeb4a616d8a9a229122625ff3a17029dd`
- [TERMINAL.json](g2-paired-local-20260916T044126Z-o3f8g1xe/TERMINAL.json)：
  `7129014e988c5ceab3b36cb812771ffcc836473e34e098202fd7195e2dfb3f45`
- [UNIT_TESTS.json](g2-paired-local-20260916T044126Z-o3f8g1xe/UNIT_TESTS.json)：
  `5db4ab9a19e4355b283ec741a7f5433ef66b7a4d8f672dcc015d7a5b71a64096`

`package/`保留完整21份来源；4份结果JSON与4份进程日志由终态绑定。
本次创建的临时冷缓存目录已清理，不删除任何旧证据或超算文件。

只读复核，不运行模型、不联网：

```sh
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_compiled_check_20260916/run_check.py verify \
  docs/superpowers/evidence/g2-paired-local-20260916T044126Z-o3f8g1xe
```

旧CellBridge最终回执只读复查PASS；旧Job720730固定下载结果只读复查PASS，无新远端调用。

## 限制及下一项授权

合成fixture使用seed0（不是生产seed），构造模型后交给模拟strict-load，
原生compiler lifecycle在封存前由原函数签发；这属于明确披露的测试预注入，
不证明真实checkpoint加载顺序或来源。没有真实formal40、作者checkpoint、音频库或GPU推理。
`production_interference_validated=false`、`ready_for_gpu=false`始终保留。

缺少的下一项是同版本R/C完整双轮配对，不是重新训练，也不是总体模型对比。
拟议**一次新CPU作业：1CPU、6000MiB、22分钟、0GPU**；
四个冷子进程R-reference、R-observed、C-reference、C-observed，单进程300秒，
coordinator1260秒，Slurm1320秒，任一执行失败即停、不自动重试。
该时限是预算上限，不保证能够完成；CPU通过也不是A100数值验收。

**资源未获新授权；尚无native coordinator/SSH/sbatch提交入口。**
若用户批准，再核验分区/额度、完善有界启动与独立收集入口并进行一次提交。
旧Job720730的1CPU/6000MiB/10分钟单次授权已经使用，不能复用。
之后仍需真实生产worker、G2 GPU数值选择、三模型smoke、冻结10k预测及配对统计报告。
