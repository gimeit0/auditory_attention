# GPU v2提交控制器修正与本地验收

2026-09-14 JST。本轮继续修正实际提交入口，不改旧Job705468或科学数值判据。
最终formal40与作者checkpoint的完整对比仍未完成。

## 已完成的修正

新入口：[GPU v2控制器](../prototypes/targeted_gpu_control_20260914/README.md)。
沿用已接入先建scratch、后导入的49文件运行包，补齐独立新目录的部署、
test-only、单次暂扣提交、资源复核及放行控制。目标目录仍未在远端创建：
`/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-14_v2`。

1. 暂扣记录必须同时给出typed-A100的ReqTRES、TresPerJob和TresPerNode。
   泛型GPU不再代替具体型号；拒绝H100、额外GPU/其他GRES及数量错配。
2. 核对同一JobID、用户、nonce、脚本、工作目录、输入和日志路径，必须
   尚未运行/分配，且CPU8、内存64GiB、时限2小时、单节点、禁止requeue。
3. 放行前增加sacct交叉核对。记账必须唯一、PENDING、0秒、无分配，
   资源请求与scontrol一致；空结果、迟到、查询失败或冲突均保持暂扣。
   不自动重试、更新资源、重提或取消；两份查询原文均保存，status可读取。
4. 新包使用独立本地证据目录、新确认参数和新包SHA。旧705468的单次
   资源授权、提交意图和修正/放行记录不可复用。

原B2、32条样本、16→1顺序、严格模型加载、父数组匹配、168采集、
数值容差及研究角色均未更改。候选构建/校验不是新的GPU资源授权。

## 验收证据

- [新45项测试回执](gpu-control-v2-local-20260913T185915Z-3mbpu883/receipt.json)：
  全部通过、零跳过，独立子进程28555，Python3.11.15。调度器/SSH为模拟，
  含实际本地文件传输和超时测试，不是超算作业。
- [旧34项回归回执](gpu-control-local-20260913T190002Z-lgd9vm4s/receipt.json)：
  全部通过、零跳过；旧51份固定来源未改变。
- [独立复核记录](2026-09-14-gpu-v2-control-review.json)及
  [可重跑只读复核器](2026-09-14-gpu-v2-control-review.py)：重新逐SHA读取
  新55/旧51份来源、两个测试回执及原始日志/子结果。保存的真实HAKUSAN
  typed-only A100记录可被新解析器接受，旧H100错配记录被拒绝。
  重放只替换目标root/runner路径，没有修改资源值，也不是新的远端查询。
- 新[55文件控制清单](../prototypes/targeted_gpu_control_20260914/CONTROL_RELEASE.json)
  SHA：`42da7aec12a2b64a7a9608d1f047cdddf1230d5b949ce12401947eb3cbab5b67`。
- 已固定49文件运行包SHA仍为
  `8ddf8cc8ece27a14c49336b60fd1a45ffa295f57fb45778a66c559514d6d04f5`。

## 当前边界与下一步

[本轮实际CPU复验入口回执](startup-probe-remote-20260913T190003Z-666g_w9r/receipt.json)
显示共享`master.sock`不存在，process=null、result=null；在本地连接检查即停止。
没有发送探针载荷、远端上传或新作业；不能声称HAKUSAN同版本CPU/A100通过。
这是认证依赖，不是排队等待，也不说明服务器不可达。没有尝试收集密码或重连。

用户在Mac终端恢复认证：

```bash
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-10-hakusan-connect.sh"
```

恢复后先执行已准备的有界Linux/torch2.1.1 CPU启动复验，核对结果；之后
才部署新包、Slurm test-only和审核新资源授权。实际GPU冷参考/观测、
定位数值差异、三模型smoke及10000条正式同bank对比仍待完成。
评估仍为复用验证bank的审计，不是独立测试结果。

本轮分类为progress：控制器缺陷得到修正且有新的完整测试证据。
本轮新增GPU作业0、远端上传0；长期目标保持未完成。
