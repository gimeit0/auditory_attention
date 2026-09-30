# E0 v2源码导入隔离修正（2026-09-25）

本版本替代未提交的v1。v1包和远端训练快照/缓存保持不变；不在旧目录覆盖。

修正：受审快照的Python模块通过定点MetaPathFinder/SourceFileLoader从已核验SHA的`.py`字节编译，不调用缓存取码路径，不写pyc。已有缓存只计数，不作为执行输入；无源码pyc、未固定源码、哈希变化、命名空间逃逸仍拒绝。仅在冻结导入上下文内安装，异常/嵌套退出移除；不修改全局SourceFileLoader实现。不承诺限制受信源码主动调用的任意自定义反序列化操作。

目标部署路径：`/home/s2510040/audattn_e0/e0_20260925_v2/package`。预算/样本/α/G5容差不变，1A100/8CPU/64GiB/30分钟，held一次，不自动release或重试。发布SHA见同目录BUILD_RECEIPT.json。

上传核验后，先在登录节点运行只读原生预检（不会加载checkpoint）：

```bash
P=/home/s2510040/miniconda3/envs/attn/bin/python
PKG=/home/s2510040/audattn_e0/e0_20260925_v2/package
SHA=请填本地BUILD_RECEIPT中的release_sha256
"$P" -I -B "$PKG/e0_entry.py" check "$SHA"
"$P" -I -B "$PKG/e0_entry.py" source-check "$SHA"
```

只有整包与原生预检通过且发布/预算审查完毕，才可运行一次：

```bash
"$P" -I -B "$PKG/submit_e0_once.py" --release-sha256 "$SHA" --confirm-action SUBMIT_E0_HELD_ONCE
```

返回held回执后停下，检查Slurm实际资源与runner；站点改写typed GRES需要另行审查，不自动修正/释放。SSH/回执不明先查日志及队列，不重跑提交器。

本版本构建和本地测试不代表超算已部署、已提交或真实E0通过。下一步先独立目录上传/核验/source-check，不提交旧v1。
