# GPU单次控制器v4

固定新root gpu_pair_2026-09-14_v4；发布52文件运行包及控制器，共58文件。
动作：check-only、preflight、deploy、test-only、submit、status。
连接仅复用已认证SSH master，不收集密码、不自动重连。
提交需SUBMIT_ONE_B2_GPU_V4_A100_8CPU_64G_2H和有效test-only回执。
本地/远端独占提交意图，先hold核对typed A100和sacct，失败保留同JobID，不自动重提。
若站点改写GPU请求，停在hold，由独立核验的同作业修正处理，不能跳过资源核对。

用户2026-09-14明确要求推进直到完成提交；本次沿用1A100/8CPU/64GiB/2h范围，
新资源授权只用于这个新诊断作业，子进程50分钟预算不变。
不代表最终formal40/作者checkpoint/valbest33同bank比较完成。
