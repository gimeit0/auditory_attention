# v13独立部署与实际结果

## 最新终态：Job683154失败，诊断继续

续记：用户恢复SSH后补齐PRE/POST，本地五份核心证据SHA全部通过。
同版本最小探针已复现固定PATH下真实Triton缺ldconfig，以及跨模块CPU tracing
在构造后清理模块时触发同类sealed绑定变化。原v4四SHA保持，相关队列空。
这不是数值结果；独立v14固定PATH/模块封存生命周期修复方案尚待明确批准，
没有新版本或新提交。完整事实/推断边界见下方诊断记录。

实际 FAILED 2:0 / 3分14秒 / spcc-a100g01；2026-09-10 14:34:01→14:37:15 JST。
只读 verify-results 返回 DIAGNOSTIC_FAILURE_RECORDED / VERIFY_RC=2，
matrix=null、post_errors=[]、numeric_results_interpretable=false。
这不是模型比较结果。新日志确认编译器 inner_exception=FileNotFoundError，
并有4个受保护模块新增（记录前三个src/src.audio_transforms/src.custom_modules）。
具体缺失文件与模块生命周期仍需验证；不重提Job683154。

最终 failure SHA：bab521a36e3c0a4bb5ec1703e5aec5f281026784c495459d45f263bc1676ef69。
最终 log SHA：39162e1d7e52251577755c20a89b7fb5c23a13f549028ff2222946813a5034ab。
三份本地原始证据已复验，PRE/POST副本尚待下载。恢复检查时共享SSH连接已失效，
非交互认证返回255；没有新提交或生产代码修改。
详见[本次诊断记录](2026-09-10-job683154-compiler-path-import-diagnosis.md)。

以下为按时间保留的部署经过，RUNNING等是历史状态。

2026-09-10。沿既有有界失败日志授权，只补内部异常/模块delta，不改科学设置、
资源、32条诊断矩阵、通过条件或旧版本。629项本地及实际同版本formal40 CPU
检查PASS，见[v13修复记录](2026-09-10-diagnostic-v13-failure-metadata-repair.md)。

十九文件候选manifest：9cee85c7940c0ee3e5f75aeff28f7beea2124ef3b25dd30e55a2250f6e935839。
独立远端root：same_bank_v4_job646900_2026-09-03_v13。

八个Mac操作入口由完整读取的v12模板作精确版本/pin替换生成，bash-n通过。
create绑定原v4四SHA及v12 freeze/failure/log三个已归档SHA；不删除或改写旧版。
freeze和Job未知的下游脚本设显式阻断占位符，只在真实回执审阅后替换。
本记录创建时尚未部署，下面按真实结果追加，禁止把计划当成作业完成。

## 实际发布

原v4及v12七个绑定SHA复验通过，相关队列为空，新root创建/四文件上传成功。
stage/tools八次固定SHA校验通过，publish exit0；四份暂存硬链接及空stage
已移除，完整文件仍保留tools（600），目录700。旧版本未删除或覆盖。
已进入audit/freezing，尚无新freeze回执或Job ID；不重跑create/publish。

## 实际freeze

audit=PASS，freeze=INPUTS_FROZEN，协议v13/32trials/24pinned，组合exit0。
新freeze固定SHA：48b6c9ec1115796da95bed4710395bce7c7eb8eb45084f135689821df4971f51。
已据真实回执更新五个后续脚本的F并解除freeze占位阻断；Job仍未知，查询/
结果脚本继续显式阻断。下一项只读check-only，通过前不得提交。

check-only实际返回CHECK_PASS/exit0，协议、freeze和五个目录/root准确绑定，
源码与freeze前后SHA一致。现在仅调用单次submitter一次；不直接sbatch，
不重试。若响应不确定先检查持久状态。Job仍以真实回执为准。

## 单次提交Job683154

submitter仅调用一次，SUBMIT_RC=0；之后只读status及终态验收，不重提。

```json
{"job_id":"683154","next":"wait_then_status_and_verify_results","receipt":{"diagnostic_protocol":"formal40_batch_invariance_diag_20260903_v13","input_freeze_sha256":"48b6c9ec1115796da95bed4710395bce7c7eb8eb45084f135689821df4971f51","intent_nonce":"5c0d9d7fcb7b452db62adf233fe1605e","intent_record_sha256":"d8761994efc668a00433b2779fdee864ea873d633428a85b0641870324f408ca","job_id":"683154","response_record_sha256":"e4acfb52866046b49c7d4eee6eee76c455d1f92416a0791efc1257ab1028e0a9","runner_sha256":"5a5330c744d8b6b38a8ecf84bbf59e9e4cc93547e3b6cfb39d073e332cdb1e09","schema_version":1,"status":"SUBMITTED"},"status":"SUBMITTED"}
```

三份查询/验收脚本的Job占位阻断已据此真实回执解除。该回执不是数值结果。

只读状态实际RUNNING，自2026-09-10T14:34:01在spcc-a100g01运行。
启动记录三个恢复环境值正确；BOOTSTRAP_ENVIRONMENT_SHA256为
2d0b6a9654ab61bc0786743e0e77e709869f7bb3b8681cd3bef271fad5899b1d。
运行中日志不是最终证据，不提前把它的临时SHA固定成最终工件身份。
