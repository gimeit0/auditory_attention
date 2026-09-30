# P05b固定布局候选:真实四布局已运行并复算(Job 726428),尚未审定数值政策

**9/19:** Job 726428 COMPLETED/0:0(5分16秒,spcc-a100g04),四布局离线复算完成:固定配置逐位一致、同伴重排 correct cue 逐位一致、跨批形状 NLL 差 ≤1.03e-3、987 条配对 0 翻转。状态 `P05B_OFFLINE_RECOMPUTED_NOT_QUALIFIED`,[台账与结果](../docs/superpowers/evidence/p05b-production-20260918/REPORT.md)。冻结包 release SHA `dc0c81d8…059a`;远端根目录 `eager_p05b_20260918_v1` 已发布,不可复用于新作业。以下为此前状态历史。


最新追加：`offline_review.py`统一离线科学复算入口已完成，7组比较、987条配对记录（不是独立样本数），源码纳入发布清单。整包本地/原生CPU102项通过，[证据](../docs/superpowers/evidence/p05b-cpu-native-qry7yvl_/REPORT.md)。下一项为最终冻结检查/明确预算审批/现场投递；未提交新GPU作业。以下93项与更早状态为历史。

最新：已实现 `ship.py`，操作说明见 [OPERATIONS.md](OPERATIONS.md)。更新整包本地及超算原生CPU均93项通过，[本轮证据](../docs/superpowers/evidence/p05b-cpu-native-w6ncfjx5/REPORT.md)。仅合成测试，无正式发布/作业；下一项是下载后的统一离线科学复算入口。下段69+15项为上一轮历史。

2026-09-18。仅供剩余覆盖资格验证，不是正式全量比较入口。运行包装此前69项原生CPU通过；本轮新增发布/单次held提交/条件放行/传输校验控制器核心15项本地通过，原69项回归仍通过，见[最新控制器证据](../docs/superpowers/evidence/p05b-controller-local-20260918-v1/REPORT.md)。尚无SSH操作CLI，新增源码与变更后的sbatch尚未原生复测；未部署正式包、未提交、未生成正式授权。

## 已实现

- `eager_compare.py`：独立的新协议；四种固定布局和外部布局SHA绑定，LAYOUT.json纳入独占产物及receipt。旧eager v1源码和结果未改。
- `layouts/*.json`：已展开的trial ID、顺序、batch成员和16+1尾批规则。清单只来自旧32条，不根据模型结果选择。
- `review_layouts.py`：先逐文件核验、从logits独立复算，再按trial ID及cue条件配对。只允许计划中的桥接、cold1、16/1、同伴重排及尾批比较。旧产物必须通过原SHA固定的旧reader，不能冒充新协议。
- 比较报告包含逐trial有符号NLL差、mean/std(ddof=0)/max_abs、分位数、翻转、accuracy差和模型成对差值变化。`paired_nll_rows`保留在JSON中，现已接入CSV导出及本地收集。默认差方向右−左；新增有符号统计明确标为`nll_signed_left_minus_right`，两者不混用。
- `sequence.py`和`sequence_worker.py`提供四模型＋四验收进程、总deadline、外部hash契约与实际分配检查。bridge16/cold1固定配置差异停止；重排/尾批差异保存，不自动批准。`collect`只从已存在本地源复制，不负责SSH下载。
- 旧1e-6检查继续报告PASS/DIFF，任何结果都不自动获得全量资格。

样本布局：bridge16为原32条batch16；cold1为原32条batch1；peers16将前后16条交错以改变同伴；tail17为原前16条加原最后一条（不是前17条），batch16形成16+1。三模型及原controls均保留。

## 本地验证（布局核心的上一轮记录）

本机Python3.11.15 / Torch2.12.1，合成小模型CPU测试，无正式checkpoint/A100推理。测试中的HAKUSAN环境声明是合成测试数据，不是真实计算节点记录。

| 组 | 本次最终通过数 |
| --- | ---: |
| 新布局候选与验收 | 43（含从旧候选迁移的21项回归） |
| 原eager v1 | 21 |
| 原比较器及有符号统计 | 18 |
| 当前v4测试目录 | 74 |

合计156项测试执行，不声称156个全新独立测试。旧文档的v4 56项是历史记录，本次实际discover执行74项。新版本第一次运行因回执测试未传新增布局SHA而1项报错，已同步测试契约；其余20项通过。随后补全布局/配对/错误路径，最终43项全部通过。ruff检查通过。

源码AST回归要求：除新增布局函数和必要修改的选择、运行声明、receipt校验、CLI入口外，旧版所有函数逻辑保持一致；包括场景/模型推理、状态保护、指标复算、严格加载接口。新桥接真实A100结果仍需未来作业确认，不能用AST/CPU测试替代。

[原始测试日志与报告](../docs/superpowers/evidence/layout-local-20260918-v1/REPORT.md)

本地重跑（不连接超算）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B -m unittest discover \
  -s same_bank_compare_2026_09_18_layout_v1/tests -v
```

查看固定尾批（不运行模型）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  same_bank_compare_2026_09_18_layout_v1/eager_compare.py layout --layout tail17
```

## 部署前还缺什么

1. 原生CPU回归已完成：HAKUSAN Python3.11.5 / torch2.1.1+cu118，69项通过，28.687秒；[证据](../docs/superpowers/evidence/p05b-cpu-native-v2hfleb8/REPORT.md)。当前四进程顺序/总超时/独立scratch/桥接门/本地收集的合成测试不代表真实A100验证。
2. 控制器库、SSH操作CLI、包冻结入口、原生前检/只读恢复查询和统一离线复算入口已完成，102项整包原生合成测试通过；仍需最终冻结检查及明确预算审批。没有正式审批文件，不可执行生产投递。
3. 做真实调度test-only，核对实际资源；新包需完整绑定代码、四布局、外部基线receipt及收集/复算工具，不沿用旧725677投递入口。
4. 用户批准新预算及确切资源纠正范围后，才可提交；30分钟/1 A100/8CPU/64GiB目前仍是提案。无自动重试/追加作业/全量启动。

最初实现轮无网络操作；后续原生CPU回归通过一次SSH临时传入测试源码，未部署正式包、未提交Slurm作业、未更改正式数值政策。额外确认集、P06、成本测量及全量对比仍按总计划推进。
