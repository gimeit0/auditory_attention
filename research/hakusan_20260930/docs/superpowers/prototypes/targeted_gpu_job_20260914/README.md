# 独立GPU运行包v2：启动顺序修正已接入，未部署或提交

2026-09-14。与旧Job705468的运行包并存，新的目标root为
`/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-14_v2`。
旧包、旧授权/作业和输入保持不变，不复用失败目录或提交意图。

## 与已固定v1的差异

- 新gpu_child的实际run函数已接入本地验证的startup适配：先独占创建
  scratch再导入数值库，之后绑定原加载器签发的执行scratch类型。
  导入/目录错误进入原try/finally并记录CHILD失败。原lifetime函数AST不变。
- coordinator、contract和runner的目标路径指向新v2。原超时、失败保留、
  双冷进程、完整数组/168采集验收逻辑保持；未改原模型/数据/数值阈值。
- runner明确声明 `--gpus=nvidia_a100:1` 和 `--gpus-per-node=nvidia_a100:1`。
  单节点1A100/8CPU/64GiB/2h不变，原705468的泛型GPU类型错误不应再照搬。
  类型语法依据[Slurm官方sbatch文档](https://slurm.schedmd.com/sbatch.html#OPT_gpus)。
  实际集群仍须test-only及暂扣资源回读；静态声明不等于已获分配。
- 新增部署入口AST、A100资源/新root、实际新入口导入失败的3项测试，
  原导入顺序静态测试加强为scratch进入先于try内的数值库导入。

候选必须经新SHA发布；旧manifest与旧705468授权不能授权本包。
当前没有新的资源授权或提交回执，不能直接运行sbatch。

## 验证入口

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_gpu_job_20260914/validate_local.py
```

预计45项运行包测试＋38项归档回归。全部只用本地合成CPU、假调度器、
受控子进程及合成数组；不连接超算，不提交GPU，不加载生产模型。
本机Linux挂载验证、HAKUSAN torch2.1.1导入顺序和真实A100执行不得
从这些本地测试推断为通过。超算同版本启动复验和新controller仍待完成。

[启动修正本地证据](../../evidence/2026-09-14-job705468-startup-fix-local.md)
保留独立15项测试及四个新进程结果。原科学目标仍是formal40与作者checkpoint
对比；本运行包只处理formal40的B2参考/观测数值诊断，不是最终对比结果。
