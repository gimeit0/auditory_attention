# 先导隔离上传执行记录 — 2026-09-23

用户批准：上传冻结先导文件到新的超算独立目录并核验哈希。未批准对齐/GPU。

目标：`/home/s2510040/audattn_holdout_pilots/pilot_20260923_0415868e9127`。
包范围：62条音频 + PILOT_MANIFEST.json + DECODE_RESULT.json，共64文件、2,390,929字节。包含6条短录音以保留原始冻结先导证据，并不授权将短录音用于对齐。

38项本地测试通过，所有本地音频按解码记录SHA重验；上传脚本只接受不存在的新根目录，用独占写入，不覆盖旧数据；计划上传后独立只读复核。

## 已发生

- [上传回执](pilot-upload-56dyb4e6/RECEIPT.json)、[预期文件清单](pilot-upload-56dyb4e6/INVENTORY.json)。
- 现有SSH master控制检查返回running，但上传SSH在110秒本地限时后超时，未返回远端成功/失败JSON，stdout/stderr均未提供结果。
- 状态 **NOT_VERIFIED**。不能将master running当作远端传输健康证明；不能认定没有文件写入，也不能认定已经上传完成。
- 没有自动重传、删除、覆盖、重连或提交作业。
- 随后执行独立的只读固定目录状态检查，不包含任何写入；也在110秒后超时，见[只读失败回执](remote-readonly-0bpkqd5f/RECEIPT.json)。因此仍无法确定远端目录是否存在或有部分文件，状态为 `WAITING_FOR_USER_SSH_RECOVERY`，不得声称上传完成。

后续必须先确认远端目录状态，再决定是否恢复传输；禁止直接重跑upload_pilot.py作为“重试”。原冻结本地清单与音频完整保留。
