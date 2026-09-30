# G2同版本检查：API通过，CPU编译取证超时

2026-09-16 JST。用户同意继续后完成以下操作；**无新增调度作业、无GPU、无真实checkpoint加载或输入freeze。**

## 已确认的进展

复用现有SSH master（pid58367），没有密码收集或自动重连。
HAKUSAN实际Python3.11.5、torch2.1.1+cu118，CPU亲和性[0]、torch线程1。
四组R/C/D/E精度读回及加载后的模型包装适配检查通过，34.798秒，CUDA未初始化、HOME未改。
这是合成CPU准备测试，未调用编译后的forward，不能称为生产strict-load或原生Inductor执行通过。

在实际环境取得7份编译相关源码并保存内容及SHA：torch入口、Dynamo eval_frame/convert_frame/utils、
Inductor backend、compile_fx和codecache。前三份Dynamo SHA与原v19固定来源一致。
确认默认compiler对象精确类型为`torch._TorchCompileInductorWrapper`；其`__call__`调用`compile_fx`。
`CompiledFxGraph`的生成和生成代码的实际调用不是同一事件，旧context-entered标志不足以证明执行。

新增独立候选`backend_evidence.py`：

- 绑定精确目标compiler对象和已核对源代码的函数code对象；不依赖调用方提供“compiled=true”。
- 记录该compiler调用栈内产生的`CompiledFxGraph`，绑定生成函数、globals、缓存源文件及SHA。
- 要求生成代码在编译返回后的推理区间被实际调用并成功返回，拒绝只有编译、无执行或不属于目标的事件。
- 不替换Torch回调、不加模型hook；但`sys.setprofile`本身的影响仍须单独测量，不能宣称无干扰。

10项本地合成事件测试通过；候选尚未接入G2真实worker，`production_ready=false`不变。
此前G2本地22项的固定源码/工件另以新进程复查通过，没有修改其5份源文件。

## 本轮失败与准确边界

1. 新API封装的首次本地检查在torch2.12.1遇到legacy medium/新API组合读回错误。
   修正本地初始化为high，与此前本地测试一致；原生2.1.1仍执行medium→allow_tf32=True→实际high。
   两种初始化在回执中明确区分，没有把本地行为当作原生行为。
2. 后续原生小型CPU Inductor检查在50.150秒触及子进程限时，监督器杀停整个进程组（-9）。
   监督器50.195秒返回，临时目录已移除，HOME未改，jobs_submitted=0。
   子日志0字节：无法判断卡在torch导入、来源校验、编译或执行，不能把超时直接归因于Inductor。
   没有有效编译执行/端点结果，不能用本次结果进入GPU数值矩阵。

已补全`IMPORT_TORCH`、`OBSERVER_PREPARE`、两次forward的开始/结束计时及一次30秒栈；
该修订尚未在超算执行。登录节点50秒限制保持不变，`run_compiled.py native`已禁用，防止重复同一路径。
旧失败源码及日志保留，不把修订后的代码冒称为已运行的版本。

## 固定证据

- [原生API检查](g2-api-native_cpu-20260916T013120Z-7vdn9nd4/receipt.json)：
  SHA `8f5f7ad6c83f221711cb5f36d729afc21492f6ab6c6c65d38d4a04bca12428c1`。
  同目录保存请求、返回、7份实际源码；result SHA `084ce78339e5bfe52c45dc133fa360ad0a35b62a0ae211bb52a3f77ab306961f`。
- [原生编译取证超时](g2-backend-native-20260916T013920Z-ngwjkwdm/receipt.json)：
  SHA `4301dd0c3ef8ff80aaa511db173055ce528af0e6fea9df4bd763b5db90ca2a40`。
  同目录保存当时全部5份候选源、10项测试日志、原生请求/监督器终态/空子日志。
- [修正后API本地检查](g2-api-local_cpu-20260916T013018Z-sufin88_/receipt.json)；
  [此前本地API失败](g2-api-local_cpu-20260916T012946Z-bmekbpjq/receipt.json)保留。
- [实际远端源码对应的本地事件测试](g2-backend-test-20260916T013851Z-ng76lh0n/receipt.json)。

[只读复查脚本](../prototypes/g2_native_20260916/review.py)核对上述固定回执SHA、全部工件、请求/源码绑定、
原生API读回与超时终态，输出`G2_NATIVE_EVIDENCE_REVIEW_PASS`；它不会把失败改成PASS。
[短命令与候选说明](../prototypes/g2_native_20260916/README.md)。

## 下一项与授权边界

建议另批**一个独立CPU计算节点验证**，不在登录节点延时：

| 项目 | 拟议上限/规则 |
| --- | --- |
| Slurm | 1CPU、6000MiB、10分钟、0GPU；最多10个CPU allocation分钟 |
| 子进程 | 原生compile基线、带取证，各自冷启动/独立缓存，各240秒；前项失败不运行后项 |
| 监督器 | 540秒内部截止，受Slurm600秒外部上限约束；超时终止进程组 |
| 数据 | 同一小型合成模型与固定CPU输入；不是formal40、作者checkpoint或真实32条 |
| 验收 | 来源/配置/输入/模型状态/RNG/端点输出/生成代码与执行证据，阶段耗时与内存，临时目录清理 |
| 停止 | 不自动重试/重提、不放宽输出比较规则、不追加GPU |

尚未获该预算授权，未创建批处理发布包或调用sbatch。此前Job718727预算已使用，不能移作本次授权。
批准后再准备最小批处理包、核验实时分区/账户和资源上限、单次提交并独立取回验收。
这不是“checkpoint对比作业”，只为完成G2所需编译取证与观测干扰验证；
真实G2-M/G2-R、G4三模型smoke、G5全量及统计报告仍未完成。
