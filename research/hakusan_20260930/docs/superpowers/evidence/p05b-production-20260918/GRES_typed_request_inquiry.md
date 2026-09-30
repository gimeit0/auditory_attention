# typed GRES 被改写问题：现场证据与向管理员的询问稿

2026-09-19 整理。目的：结束“每个作业都要单独授权一次同作业 GPU 修正”的循环。

## 1. 超算文件夹中的官方说明怎么写

- 講習会資料_20260414_part1_JA2.pdf：只给出分区表（GPU-1A：A100 用，spcc-a100g[01-10]，1 节点 1 GPU，默认 26core/256GB/1GPU），以及 `salloc -p GPU-1`、`#SBATCH -p ...` 的示例。**没有任何 typed GRES（`gpu:nvidia_a100`）写法。**
- 講習会資料_20260618_JA.pdf：GPU 交互示例为 `salloc -p GPU-1 -c 2 -G 1`，即**泛型 `-G 1`（= `--gpus=1`）+ 用分区决定 GPU 型号**。同样没有 typed GRES。
- 官方参考页：<https://www.jaist.ac.jp/iscenter/mpc/kagayaki/2/#c5869>（PDF 第 39 页所引）。

结论：站点文档的标准做法是“分区选型号，泛型申请 GPU 数量”，typed GRES 不在支持说明范围内。

## 2. 现场只读查询结果（2026-09-19，登录节点）

| 项 | 值 |
| --- | --- |
| JobSubmitPlugins | `lua`（源码在登录节点常见路径均不可读） |
| GresTypes | `gpu`；SelectType `select/cons_tres` |
| AccountingStorageTRES 含 | `gres/gpu:h100-20c`、`h100-80c`、`nvidia_a100`、`nvidia_a40`、… |
| GPU-1A / GPU-LA 节点 GRES | 仅 `gpu:nvidia_a100:2(S:0-1)`；h100 型号只存在于 VM-GPU-L（`h100-80c`） |
| `spart` GPU-1A MaxTRES | `cpu=26,mem=256G,node=1`（无 gres 项；对比 GPU-1 有 `gres/gpu:nvidia_a40=1`） |
| 三次作业最终 AllocTRES | 724808 / 725677 / 726428 均 `gres/gpu:nvidia_a100=1` |

历史上五次（705468、713897、715276、724258、726428）以 `--gres=gpu:nvidia_a100:1` 提交后，held 状态下 `ReqTRES` 显示 `gres/gpu:h100-20c=1`、`TresPerNode` 变为泛型 `gres/gpu:1`；用 `scontrol update ... TresPerJob=gres/gpu:nvidia_a100:1 TresPerNode=gres/gpu:nvidia_a100:1` 修正后可正常运行于 A100。另有一次（r1）同时给 `--gpus=nvidia_a100:1` 与 `--gpus-per-node=nvidia_a100:1` 被 Slurm 本身拒绝（"Invalid GRES specification (with and without type identification)"）。

推断（未确认）：`job_submit.lua` 在提交时把 GPU 请求规范化为泛型 `gpu:N` 并给记账串填了一个默认型号 `h100-20c`；由于 GPU-1A 节点只有 A100，实际分配不受影响，但请求记录与已批准的“1×nvidia_a100”不一致，触发我们的资源核验。这是**请求记录层面的不一致**，不是曾经跑在 H100 上。

## 3. 两条可选出路

A. **管理员确认后改用站点标准写法**：`-p GPU-1A --gpus=1`（不写型号），核验改为“分区=GPU-1A 且 AllocTRES 含 nvidia_a100=1”。运行时核验（设备型号读回）保持不变。需要修改 `remote_control.check_tres` 的规则并重新冻结包，属于一次性变更。

B. **管理员提供保留 typed GRES 的提交方式**（例如插件豁免或指定参数）。

任一出路都需要管理员回复作为依据；在回复前维持现状（typed 提交 + 单独授权的同作业修正）。

## 4. 询问稿（日文，供用户发送；请自行填写署名）

件名：GPU-1A パーティションにおける typed GRES 指定の扱いについて

情報科学センター ご担当者様

いつもお世話になっております。JAIST の s2510040 と申します。HAKUSAN の GPU-1A パーティション利用に関して、ジョブ投入時の GRES 指定について確認させてください。

`sbatch --partition=GPU-1A --gres=gpu:nvidia_a100:1 --hold ...` で投入すると、`scontrol show job` の `ReqTRES` が `gres/gpu:h100-20c=1`、`TresPerNode` が `gres/gpu:1` に書き換えられています（例：Job 726428、2026-09-18）。`scontrol update JobId=... TresPerJob=gres/gpu:nvidia_a100:1 TresPerNode=gres/gpu:nvidia_a100:1` で修正すると A100 ノードで正常に実行できます（実行後の AllocTRES は `gres/gpu:nvidia_a100=1`）。

お伺いしたい点は以下の 3 点です。

1. この書き換えは job_submit プラグインの仕様でしょうか。GPU-1A では実際の割当は常に A100 になると理解してよいでしょうか。
2. 研究上の再現性記録のため、投入時点の `ReqTRES` を `nvidia_a100` のまま保持する指定方法があればご教示ください。
3. なければ、GPU-1A では `--gpus=1`（型番指定なし）が推奨される標準的な書き方という理解でよいでしょうか。

お忙しいところ恐縮ですが、ご確認のほどよろしくお願いいたします。

（署名）
