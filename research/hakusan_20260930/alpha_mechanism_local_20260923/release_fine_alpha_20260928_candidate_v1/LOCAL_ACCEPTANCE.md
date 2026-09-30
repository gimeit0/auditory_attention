# 0.01低α扫描：本地候选验收

2026-09-28。状态：`FINE_ALPHA_LOCAL_CANDIDATE_VERIFIED_NOT_GPU_AUTHORIZED`。

## 交付内容

- 54点：0–0.50步长0.01，加.75/.875/1；只评估现有formal40，不训练。
- 复用E1已冻结2000条开发trial、400条提示对照、200条clean输入及批次布局。
- 194,400条科学预测；加入原生/α=1历史桥接、三独立进程冷重复和独立gain旁路后，219,600条总预测。
- 新包：[package/RELEASE.json](package/RELEASE.json)，40个清单文件。
- release SHA：`b0bd8b4269b5542b65bbf6d3982b7484838f983d0c5fe7a9538551ea9a076b8f`。

## 已完成核验

全目录398项测试通过，48项新增；详见[完整日志](regression.log)和[执行记录](regression.json)。没有跳过项目。隔离环境下运行包自身check通过，见[包检查](package-check.log)；runner通过`bash -n`。

新测试涵盖整数网格/准确计数、54点八gain的独立float64公式、原生/α=1及旁路/α=0端点、八gain合成小模型跨全部扫描块、输入变更、NaN/NLL错误、低性能非执行失败、归档破坏/错job/错PID/缺G5/缺来源字段、完整生命周期窗口、预算到期、子进程/独立验收失败、无授权拒绝、单次held、返回码不明禁止重投、站点GRES改写保持held且不自动修正。

4个旧冻结包中的134个文件与原清单一致，前后结果相同，见[准备前](LEGACY_BEFORE.json)、[准备后](LEGACY_AFTER.json)。未改旧E0/E1/E2包或旧科学结论。

## 范围边界

这是本地合成/历史文件核验，不是原生生产验收。未连接超算、未上传、未新加载生产checkpoint、未提交GPU作业，尚无新的低α曲线。不能将通过状态写成实验完成或儿童发育对应已成立。

执行包已经包含受审E1加载器、原生音频/新clean路径及独立验收入口。真实A100上仍须通过源导入、加载、六条件历史逐位桥接、冷重复、音频/源文件前后核验；失败不自动降低门槛、不自动重试。

统计/科学报告在真实结果完成后执行，依据[46号计划](../46_FINE_ALPHA_001_EXECUTION_PLAN_20260928.md)完整报告所有54点、提示效应及α=0实测残差、错误结构、说话人簇区间和暴露样本敏感性版本。不将逐点区间当同时置信带，不标注未经验证的儿童年龄。

## 下一次授权

拟申请：上传到独立目录并只读预检；单A100、8CPU、64GiB、最多6小时，唯一一次held提交。约5.2小时来自旧任务实测线性估算，不保证新运行速度。

本文件不授予GPU权限。APPROVAL及RELEASE_AUTHORIZATION均未生成。提交后核对实际资源及spool，另行批准释放；站点改写GPU类型时停在held，修正须单独授权。脚本不会自动重连SSH。

当前只读复查命令（Mac本地，不提交）：

```bash
/opt/anaconda3/envs/audattn/bin/python -I -B \
  "$HOME/发表/超算/alpha_mechanism_local_20260923/release_fine_alpha_20260928_candidate_v1/package/fine_alpha_entry.py" \
  check b0bd8b4269b5542b65bbf6d3982b7484838f983d0c5fe7a9538551ea9a076b8f
```

不要直接运行sbatch文件或重复已有提交脚本。正式新作业号目前不存在。
