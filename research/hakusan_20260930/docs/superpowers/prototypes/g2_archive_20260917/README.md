# G2逐pass数组归档与离线内容校验候选

供既有 `g2_lifetime_20260917/ProductionCell.run(consume)` 调用。
这是库组件，不是生产运行器、发布包或调度入口；没有新增资源授权。

## 数据路径

`原32条16→1 PassResult → Consumer → 40份原dtype数组 + manifest → 冷进程verify`

- 原数组writer/流式reader来自固定SHA的 `targeted_gpu_pair_20260915_scan/pass_archive.py`。
  私有AST副本只改变绑定schema和单文件容量；逆变换确认其余源码不变，不编辑原件。
- 每文件上限204,800,000字节，从固定旧B2数组**几何信息**推导。
  每次传输1MiB、每child总2GiB、manifest8MiB不变；不是放大中间tensor采集额度。
  旧B2数值不作为R/C/D/E新结果的强制相等oracle。
- 每pass存8个粗边界、8个derived数组、4个official数组，共40文件。
  不重新推理、不改dtype、不重新签署原pass；写入前后检查原承诺和summary不变。
- job、PID、profile、release/new-freeze SHA、完整trial identity、上下文metadata摘要绑定。
  原文件不覆盖；写入失败保留部分文件，callback/writer均拒绝再次使用。
- 独立校验必须由可信supervisor提供receipt SHA及预期身份，而不是从待验manifest自行接受。
  原decoder检查serialized pass commitment；全部40文件、1280个逐trial哈希重新验证，
  official文件还须与原无损输出编码相同；从这些字节重新计算固定1e-6数值判定。
- `NUMERIC_DIFF`为有效数值差异，不能等同执行失败或伪装成通过。
  任意文件/身份/原承诺/宣称的数值结果不匹配则拒绝。

`Consumer`构造不导入numpy/torch。真实运行器应在 `consume(result, metadata)` 内，
以已核验的完整trial文档、既定job/profile/freeze及完整发布包SHA构造绑定并调用一次Consumer；
返回原回执给ProductionCell。不要在回调外提前关闭场景、模型授权或mmap。
归档回执还需加入coordinator的受绑定终态；回执本身不是执行身份认证。

## 已验证范围

最终证据：[g2-archive-local-20260917T034258Z-47rh9pu7](../../evidence/g2-archive-local-20260917T034258Z-47rh9pu7/)。
27项测试通过；D/E各自实际合成32条、34次forward、4份mmap，再由独立进程读回。
保存后原gate仍有效、RNG不变、原清理/重复运行拒绝检查通过。
27份来源快照、五个冷进程日志及回执已保存；独立只读复查通过。

本地Python/torch环境与旧fixture一致，Linux-mount检查为显式stub。
每组实际保存425,280字节；204.8MB上限只作元数据边界检查，未以真实大模型验证峰值内存或I/O耗时。
没有运行完整ProductionCell真实输入loader，没有真实checkpoint、CUDA或R/C原生编译归档验证。
内容校验不认证执行来源、不重建完整模型保护链、不证明追踪无干扰；
`independent_results_verified`、`production_ready`、`ready_for_gpu`仍为false。

## 命令

在工作区根目录，仅只读复查既有证据：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_archive_20260917/validate_local.py verify \
  docs/superpowers/evidence/g2-archive-local-20260917T034258Z-47rh9pu7
```

开发时不带`verify`会创建新独立证据目录；每child45秒、五阶段总120秒，失败不自动重试。
最终复查也必须分profile冷进程，不能卸载原loader模块来绕过固定名称保护。
初次同解释器复查失败的证据保留并见[执行记录](../../evidence/2026-09-17-g2-array-archive.md)。

下一项：把此组件接入有界生产child/coordinator、固定新身份和发布清单/新freeze，
逐条确认真实加载、执行来源、容量/超时和GPU资源批准，再执行真实32条G2；不是再提交旧CPU作业。
