# GPU冷参考/观测候选v4

保留原32条B2、batch16→1、权重/数据/阈值/数值六标志及冷双进程。
修复Job713897启动环境遗漏：OMP_NUM_THREADS=8、CUBLAS_WORKSPACE_CONFIG=:4096:8、TOKENIZERS_PARALLELISM=false。
启动前拒绝已导入数值库，导入后记录真实8线程、interop线程和CPU affinity。
外围阶段计时使用stdout，单次40分钟栈转储使用stderr；无新增模型hook或CUDA同步。
计时插入移除后AST必须恢复原调用；实际合成CPU/mmap测试覆盖带计时参考循环。

仍为单作业1A100/8CPU/64GiB/2h，child3000秒、pair6600秒，不自动重试。
运行包52文件；本地61项新包/38项归档回归，另47项控制器测试。
本地通过不代表真实GPU或最终三模型比较通过。独立新root，旧v3和713897证据保留。
