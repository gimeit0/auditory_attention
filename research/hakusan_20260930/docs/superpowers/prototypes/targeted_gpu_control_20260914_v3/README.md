# GPU 单次控制器 v3（需独立新授权）

控制独立 `gpu_pair_2026-09-14_v3`，发布固定49文件运行包及控制器。
支持本地check-only、远端preflight、不可覆盖deploy、scheduler test-only、
显式一次submit、只读status。旧v1/v2目录、失败记录、包、授权均不覆盖。

## 资源核验

运行脚本固定 `--gres=gpu:nvidia_a100:1`，仅1节点/8CPU/64GiB/2h。
控制器清除 SBATCH/SLURM 选项环境覆盖，实际提交先 `--hold`，再独立读取
scontrol 与 sacct。两者必须同意单张 typed A100、CPU、内存、节点、暂扣
状态及零分配/运行；还核对账户、nonce、runner及输入输出目录。
TresPerNode必须明确A100；TresPerJob可缺省，但如出现只能同一张typed A100。
任何泛型替代、其他型号、数量、额外约束、重复字段、记账滞后或失败均不放行。

旧授权令牌和旧包SHA拒绝。submit仅接受新的
`SUBMIT_ONE_B2_GPU_V3_A100_8CPU_64G_2H` 及本包最新通过的test-only收据。
此令牌是代码门控，不代表用户已经批准；必须先取得明确的新资源授权。
本地及远端写入独占提交意图后只调用一次sbatch，响应丢失也不自动重试。
预检、部署和test-only永不写AUTHORIZATION或调用实际提交。

## 验证与连接

运行本目录 `validate_local.py`：47项本地假SSH/调度器与私有临时文件测试。
`control.py check-only`校验55文件发布清单。两者不连接、不加载生产模型。
远端操作只复用现有共享SSH master；不采集密码或自动重连。
详细运行证据见[持续记录](../../evidence/2026-09-14-native-startup-and-gres-correction.md)。
