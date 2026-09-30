# 单次原生 Inductor CPU 基线/取证检查

批准范围：1 CPU、6000 MiB、10分钟、0 GPU、最多一次新作业。不是checkpoint总体比较。
25项本地批处理/验收测试和10项事件匹配器测试通过；Job720730已COMPLETED/0:0，2分26秒。
工件已下载独立验收：两侧完整输出逐字节一致，目标生成代码执行证明通过，限本合成CPU模型。
本次提交授权已使用，不再执行deploy/test-only/submit。不是真实模型/GPU/总体比较通过。
10文件源快照及测试回执在`docs/superpowers/evidence/g2-backend-batch-20260916/local-3hvzcg15/`。

当前只读查询命令；不自动连接、不重复提交。

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_backend_batch_20260916/driver.py \
  status --local \
  "$HOME/发表/超算/docs/superpowers/evidence/g2-backend-batch-20260916/local-3hvzcg15"
```

结果固定后，优先使用本地只读复查（无需SSH）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/evidence/2026-09-16-g2-backend-cpu-review.py
```

已审查deploy、test-only回执后调用了一次submit；提交需要同包test-only回执和精确预算确认。
先held再核查实际TRES/时间/任务/命令/nonce，匹配才release同一作业。响应不明时只查询，不重提。
运行结束collect后review，结果需与调度终态一致。失败保留完整阶段日志与工件，不放宽阈值、不再提交。

reference/observed各240秒、协调器540秒；首次失败后停止。旧50秒登录节点路径仍禁用。
原backend_evidence和监督器均SHA固定，旧文件不修改。生产模型、32真实样本、GPU和最终三模型比较仍未验证。
