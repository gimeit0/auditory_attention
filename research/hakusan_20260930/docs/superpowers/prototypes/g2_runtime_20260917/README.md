# G2 worker、离线验收和矩阵控制

服务完整计划G2；不是checkpoint总体比较结果，也不是GPU资源批准。

- `runtime.py`：真实生产cell的单次调用、作用域关闭后写终态、四组R/C/D/E停止规则及E/C/D/R候选顺序。数值DIFF可继续，执行无效立即停止。
- `evidence.py`：重读保存数组，复用原pass/state/RNG/loader/运行设置检查，并绑定父进程记录的PID和环境。不会签发活模型权限。
- `test_runtime.py`：30项控制流模拟、环境构造和既有合成数组语义检查；未运行真实生产模型。
- `validate_local.py`：固定来源、输入、子进程和日志，复查原数组证据。

固定证据见[本地运行控制记录](../../evidence/2026-09-17-g2-runtime-core.md)。只读复查：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_runtime_20260917/validate_local.py verify \
  docs/superpowers/evidence/g2-runtime-local-20260917T060959Z-yhugq8o2
```

必须由外层绑定发布/请求、调度资源及实际进程。`run_worker`的1800秒结束检查不是强制超时；父进程必须监督并终止超时进程组。
矩阵候选仍需旧B2关系解释和两次冷重复；内容验证成功不等于生产观测无干扰或允许全量评估。
当前1800秒/10000秒只是既定草案上限，不是新GPU使用授权。

## 实际进程入口候选（尚未部署）

`entry.py`提供matrix/worker/verify三个独立入口，`run_matrix.sbatch`只调用已绑定请求，不负责提交。
它要求固定生产路径、外部绑定的计划/请求SHA、32文件发布SHA、四个新freeze、实际运行中的typed A100调度资源和独占attempt。
父进程绑定实际命令/环境/PID，worker和验收各用新的解释器；超时及日志超限均终止整个进程组。
旧profile独立提交入口在新包中显式关闭，不复制旧submit逻辑。

`build_release.py`只生成本地候选包，没有上传、活数据audit/freeze、提交或资源批准。
`test_entry.py`的调度行是明确合成数据；小型成功/超时/日志超限子进程实际执行，但没有模型推理。
打包后的四组模块只做冷导入/源绑定检查，未加载torch/numpy或生产权重。

`bootstrap.py`解决job_id未知时无法预先给出请求SHA的问题：sbatch只接收固定plan SHA；held后写新job绑定请求，运行时再从实际作业号独立推导校验。
这不是单次提交控制器，也不创建或批准资源请求。
当前固定候选及复查详见[计划绑定修正](../../evidence/2026-09-17-g2-plan-binding-fix.md)；31文件入口候选保留为历史，不再部署。
不能直接将本目录的sbatch文件提交到集群：尚缺新部署、真实freeze和经批准的单次提交请求。
