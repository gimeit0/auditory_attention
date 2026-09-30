# Job683523 v15 原始失败证据

五文件由已认证SSH只读复制；SHA256SUMS来自远端验收及原始marker，五项本地
复核均PASS。不是成功数值工件，不可填入模型比较统计。

Job683523在spcc-a100g09从2026-09-10 17:05:23至17:09:09 JST运行3分46秒，
Slurm FAILED2:0。verify-results返回DIAGNOSTIC_FAILURE_RECORDED，VERIFY_RC=2，
numeric_results_interpretable=false，matrix=null，post_errors=[]，PRE/POST相同。

有界异常链定位`_invoke_attested_operator`的正常返回后校验（第4327行），
`_live_inference_attestation`第4288行的scene/model图或执行指纹/来源记录比较
不一致。原始日志没有输出具体哪一项，不可凭该日志判定唯一根因。函数正常
返回后被拒绝也不等于已取得可用的预测工件。原v15工具仍保持冻结SHA，未重提。

## 后续独立CPU对照（不是GPU原始工件）

`synthetic-native-cpu.json`和`synthetic-compiled-cpu.json`为失败后在hakusan1
新进程运行8元素Toy的实际stdout。与科学模型、原GPU artifact inventory
分开：原`SHA256SUMS`仍只包含五份原始失败工件；新增
`CPU_PROBE_SHA256SUMS`仅记录探针与这两个stdout。

同版本2.1.1中native指纹保持，Dynamo eager首次forward后完整模型指纹
因框架初始化变化而不一致，第二次稳定；两种条件数值均正确。不等同
实际模型/Inductor/A100验证，也不解释原批大小NLL差异。
详见[诊断与待审批边界](../2026-09-10-job683523-runtime-lifecycle-diagnosis.md)。
