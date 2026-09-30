# 低α扫描v3本地验收

2026-09-28。状态：**本地候选验证通过，未上传、未获新GPU授权。**

## 身份与实际验证

- release SHA：`1644b8bd3e9eea855476f123e904707f82c9d1465f4345f43432c847893e87d7`
- [机器回执](LOCAL_ACCEPTANCE.json)：SHA `b35dd562ebfcf1704b25cfa83df33bea73aa8e51b9b1a7492613b1d94dd41f9d`
- [构建回执](BUILD.json)：41个清单文件，加RELEASE共42个文件；目标`/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v3/package`尚未创建。
- 全目录497项通过（64.318秒），见[regression.log](regression.log)；新增23项并发回归，本轮针对性32项通过。测试中的Slurm响应都是替身，不是真实提交。
- [隔离包检查](package-check.log)及[runner语法检查](runner-syntax.json)通过。
- 六个旧冻结包214个清单文件前后不变，见[LEGACY_BEFORE.json](LEGACY_BEFORE.json)和[LEGACY_AFTER.json](LEGACY_AFTER.json)。

## 本轮变化

修正提交阶段按`audattn`名称一律阻止并发的问题。独立作业必须在新审批的并发审阅记录中，并实时匹配编号、目录、入口和源脚本/spool哈希；未审阅或发生变化仍停止。

初次队列核查在创建单次state之前；正式held调用前再核查一次。INTENT绑定最终队列证据。拒绝重复提交、未知响应停止、不自动修正资源、不自动放行均保留。不宣称账户最多能跑两个作业，也不承诺队列原子性；放行前还需复查。

包内只新增并发检查模块，改变提交器、读取新版本的入口、scope/远端路径和生成runner。科学合同除版本号外与v2一致；模型、数据、α公式/54点、219,600条总预测及1 A100/8CPU/64GiB/6小时候选预算都不变。

## 后续门槛

待批准v3独立目录上传、逐文件核验、原生只读导入预检及当时并发作业的只读审阅；随后单独批准最多6 GPU小时和一次held提交，核查资源后再单独放行。v1/v2授权与预检不自动移用于v3，旧版本脚本不能直接复用。

本轮network_access=false、production_checkpoint_loaded=false、gpu_jobs_submitted=0；没有新科学结果。[完整说明与执行计划](../48_FINE_ALPHA_V3_SUBMISSION_QUEUE_FIX_20260928.md)。
