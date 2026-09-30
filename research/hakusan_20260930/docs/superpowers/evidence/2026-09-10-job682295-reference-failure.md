# Job682295：参考推理失败与运行环境遗漏

2026-09-10；这是失败分析，不是科学结果。

审批更新：用户已回复“好的”，批准在独立 v12 恢复下述三个原 runner 固定
环境值并增加有界异常链日志。须先完成回归和真实路径检查，再单次受控提交；
不授权修改模型、精度序列、矩阵、容差或任何旧版冻结文件。

## 已确认的事实

v11 R2在真实torch2.1.1/formal40 CPU完整准备检查通过后，独立部署、freeze、
check-only全部通过，只提交一次Job682295。A100g02运行3分35秒后FAILED2:0。
只读verify-results返回DIAGNOSTIC_FAILURE_RECORDED/exit2，matrix=null，
numeric_results_interpretable=false、post_errors=[]。工件只有ENVIRONMENT、
PRECHECK、POSTCHECK、RUNNING，没有完成的参考或cell数值工件。

```text
freeze 8e304d05f099a6d8ab7ab9c05a98de7ce35eab1886d0b040d6af2c6e19e559e6
failure fadf15e57a5e482f4648f692119617387a5bf03ea21ee46126227323efe3e154
log 5dd91c497198876cbb6de84136939946412fee2b786a33f8c6cfbae829a8c287
artifact_inventory 61e97548b108f2d52aff83e5dcd67ee27fc2591d427e75fbec2dbf6775ecb307
PRECHECK=POSTCHECK 981170e65b0d0e04c9a97d66eafe2682bf139ff2c5f4cfcc24dfbbae811e17a3
```

stderr实际只有`diagnostic error: frozen reference prediction failed`。
源码run_reference_pass包裹预测operator的异常并用`raise ... from error`保留
内存cause；CLI仅输出最外层str，父进程只记录child exit2，因此底层异常未
进入当前持久日志。不能从这个错误断言CUDA/cuBLAS、模型输出或post-call
执行指纹中的哪一个失败，也不能声称本次已解释原Job646900的NLL差异。

## 独立确认的环境遗漏（不是已证实的唯一根因）

原冻结v4 runner（SHAb3531dce...）明确设置以下固定值；v11干净子进程
环境构造器没有这些键。对SHA39ee10de...的child_environment进行只读函数
调用，即便parent提供这些值，输出仍全部None。没有启动worker或推理。

| 环境键 | 原v4 runner | v11 child_environment |
| --- | --- | --- |
| CUBLAS_WORKSPACE_CONFIG | `:4096:8` | 缺失 |
| OMP_NUM_THREADS | `8` | 缺失 |
| TOKENIZERS_PARALLELISM | `false` | 缺失 |

PyTorch官方v2.1.1源文件Context.cpp中，CUDA>=10.2且确定性算法开启时，
相关cuBLAS操作要求受支持的workspace设置，否则报错；配置第一次检查结果
保存在static bool，因此应在数值库初始化前提供。这与生产torch2.1.1/cu118
有关，CPU准备验证不会执行对应GPU路径。参考
[PyTorch v2.1.1 Context.cpp](https://github.com/pytorch/pytorch/blob/v2.1.1/aten/src/ATen/Context.cpp#L114)。

由此只能确认诊断环境没有完整复现原runner，并有明确的CUDA失败风险；
尚未取得Job682295的底层异常或GPU最小复现，不把风险推断写成既定根因。

## 下一方案：需明确审批运行环境合同后执行

1. 保留原v4和诊断v1–v11、失败记录及已冻结源，不原地修补或重提Job682295。
2. 在独立新版本恢复原runner这三个固定环境值：启动coordinator和每个cold
   child之前设置，禁止继承任意parent覆盖；记录并核验实际值。保留原模型、
   精度/TF32/compile及矩阵/容差，不改为warn_only、不关闭确定性。
3. 增加有限的异常链类型/位置与诊断上下文记录，失败后落日志；不输出环境
   全量内容、局部变量、张量或密钥，不吞异常、不改变退出2或失败门禁。
4. 先做环境构造/原runner固定源一致性、父子传播和错误链回归，再验证真实
   GPU最小路径/原诊断。若再次失败必须以具体异常为依据，不能盲重试。

该方案会改变v11已冻结的runtime环境合同，即使目的是恢复原v4设置，也应
明确批准后执行。本轮未创建v12、未变更运行环境、未提交第二个GPU作业。

## 本地归档

五份原始证据已下载至[job-682295-v11](job-682295-v11/)，包含freeze、失败
marker、完整log及PRE/POST；使用预先固定的SHA256SUMS验证5/5通过。
发布后的v11十六文件候选清单亦再验全通过，没有原地修补。
