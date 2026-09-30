# E1 750474：错误结构完成与来源字段审查

状态：`E1_ERROR_STRUCTURE_COMPLETE_NOT_DEV_COMPLETE`。不改变主指标，不发布科学候选标签。

## 错误结构覆盖

`analyze_e1_errors.py` 对 A、B 全部 60 个数组、38400 条预测分类；B 冷重复单独保留，未作为额外独立样本合并进统计。每次分析先重跑冻结包 offline-check，并校验输入数组 SHA。两进程对应的 alpha_1 错误计数与标签碰撞清单相同。

结果：[REPORT.json](release_e1_20260927_v3/error-analysis-750474-wyzfs1v7/REPORT.json)；逐预测分类：[ERROR_TRIALS.csv](release_e1_20260927_v3/error-analysis-750474-wyzfs1v7/ERROR_TRIALS.csv)。报告保存输入与代码 SHA、各类别计数及说话人簇 bootstrap 区间。19 项统计与分类测试通过。

分类口径：目标与任一干扰者词标签相同的 trial 单列 label_collision，不算可区分的干扰错误。非碰撞 trial 的互斥顺序是 target > distractor > cue_word > other，同时保留原始 target/distractor/cue 命中标志，避免掩盖多个角色词标签重叠。该顺序仅用于描述性分表，不改变正确率、样本纳入或 D。

cue 标签取实际条件对应的词：correct、shuffled、probe_distractor；silent 没有 cue。main 的 clean/correct 实际是零 cue，不按名字算作正确 cue；新 clean/correct_cue 才读取 correct_cue 标签。分类测试覆盖这些区别。

示例（分母不同，不直接将下面两行当配对比较）：

| A / α=1 | n | target | distractor | cue_word | other | label_collision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main correct | 2000 | 886 | 35 | 1 | 1078 | 0 |
| main shuffled | 400 | 33 | 50 | 1 | 316 | 0 |

## P1–P9 审查进度与发现

原始证据目录 `release_e1_20260927_v3/collected-750474-_rosoog2/state/attempt/`，冻结包为同级 `package_ready/`。本表是审查记录，不替代冻结验收器，也不自称全部来源门已关闭。

| 项 | 当前证据 | 审查结论 |
| --- | --- | --- |
| P1 版本 | A/WORKER.json：Python 3.11.5、torch 2.1.1+cu118、CUDA 11.8、cuDNN 8700 | 有实际值，生产离线验收已检查 A/B |
| P2 GPU/主机 | NVIDIA A100-PCIE-40GB、spcc-a100g06、job750474、8 CPU | 与终态 sacct 节点一致 |
| P3 六运行设置 | deterministic=true、cuDNN deterministic=true、benchmark=false、matmul=highest、两 TF32=false | 与冻结 eager FP32 值一致 |
| P4 资源 | A/B STAGES.json 每 pass 的 allocated/reserved 字节、RSS 与单位 | 字段及正值/顺序已由生产验收检查；最终报告仍需汇总最大值 |
| P5 UTC 时间 | A/B STAGES.json 的 process_started/finished 与每 pass 起止 | **范围限制待最终审定**：字段实际上覆盖模型加载后 execute_loaded 的执行阶段，不是操作系统子进程完整生命周期；不能把它说成包含加载阶段的进程起止 |
| P6 调度 | COLLECTION_MANIFEST.json 终态 sacct；release-750474/remote.jsonl 放行前后 scontrol | 已有两种只读证据，不伪称终态 scontrol 回读 |
| P7 α/mode | RELEASE.json execution.pass_map 与 alpha_grid | 十个 main pass、七个 clean pass及五点网格齐全，与合同表对应 |
| P8 暴露 | execution.pilot_exposure | E0 746603、19 条清单、5 clean；decision_record.documents 绑定 26/27 号 SHA |
| P9 合同/签署 | RELEASE 绑定 28/29 SHA；外部 SIGNOFF.json 绑定同一 release、δ=2 | 冻结 RELEASE 仍保留当时 PENDING 字符串，后来的用户签署须以外部记录覆盖显示，不能改冻包伪造当时已签署；导师意见仍 NOT_RECORDED |

P5 的字段存在与格式通过，不足以支持“完整进程 UTC 起止已记录”的更强说法。PROCESS_COMPLETE.json 保留 PID、命令、退出码和总 elapsed，但未记录每个子进程的 UTC 创建/退出时刻。不得根据文件 mtime 或比例倒推伪造。最终完成审计须显式处理这个来源限制；本轮不放宽冻结要求、不自动重跑 GPU。

## 接续工作

继续本地独立复算所有主要/次要结果，检查 28+29 的完整条目覆盖（特别是按 clean/mixed 分开的错误结构、来源字段与图文）。整理最终证据矩阵，将“数值分析已完成”和“合同全项交付已验收”分开。若发现原归档无法补齐的来源要求，诚实列缺口，不以绿色测试替代证据。
