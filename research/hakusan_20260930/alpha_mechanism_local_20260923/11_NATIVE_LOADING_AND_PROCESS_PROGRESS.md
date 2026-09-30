# 原生加载/音频接线与独立进程监督（2026-09-23）

状态：LOCAL_NATIVE_SEAMS_AND_PROCESS_TESTS_PASS。生产执行包尚未闭合，不能提交E0。

## 新增实现

1. `audited_model_session.py`：候选加载上下文，无CLI、无SSH、无提交功能。要求Slurm Linux分配、隔离Python、指定Python/torch/CUDA/cuDNN与A100；校验旧manifest及formal40 SHA，持旧evaluation lock，前后核验冻结输入；调用旧strict_load_model并恢复历史runtime/RNG。原生回调两源码在import前及之后核对固定SHA，架构代码核对原路径与SHA。严格加载器内部临时import会恢复sys.modules，因此架构来源检查使用forward代码文件而非再次解析类的模块名。
2. `native_batch_provider.py`：每批按历史顺序构造scene、correct cue，再构造shuffled/silent/distractor；scene与历史逐样本SHA对齐、控制子集与布局对齐、标签/probe保持旧语义。只缓存当前批payload与128项waveform cache；拒绝错序、变bank、scene hash错配、非有限SNR误差。这里复用原生音频回调，singleton预处理仍由旧predict执行，不重写数值流程。
3. `two_process_supervisor.py`：顺序启动A/B两个新session子进程，共用总时限；超时/异常杀进程组，首进程失败不启动B，不自动重试、不覆盖目录。日志、LAUNCH与FAILED保留；零退出还必须经过调用者的独立验收才写PAIR_EXECUTION，永不标科学通过。父进程验收callback只有协作式时限，不具硬中断保障。

## 本轮实际测试范围

全套86项本地测试通过，新8项覆盖：合成音频回调的顺序/控制构造/两轮重建；scene SHA、SNR、bank变更及错序拒绝；两个真实不同子进程PID与输出核对；首进程错误、超时、验收拒绝和不覆盖；非分配环境拒绝进入加载。

**没有执行真实strict-load。** 加载上下文仅完成代码接线与入口拒绝测试，未验证真实checkpoint/冻结import依赖闭包。音频适配器测试使用合成回调；双进程测试是轻量生命周期检查，尚未运行两个独立的完整模型worker。因此不声称原生音频或A100 E0验收完成，也不声称已获得冷重复模型结果。

## 下一步（本地）

- 统一worker入口，接上加载上下文→历史桥接worker-body→独占文件sink；归档G5、观察、加载及桥接报告的SHA。
- 解决历史参考目前绑定Mac本地路径的问题，形成便携且固定SHA的288条参考包；不能部署后放宽或跳过728520桥接。
- 两独立模型进程的完整合成演练及独立归档验收；增加损坏/不完整报告/后代进程超时等整包负测试。
- 完成冻结源码/依赖清单、失败后postcheck异常的双重记录、整包review，再申请远端部署与GPU预算。现无提交命令。

本轮没有SSH、上传、读取真实checkpoint、GPU或训练作业。用户终端连接成功不视为部署或GPU授权。
