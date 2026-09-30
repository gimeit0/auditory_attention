# v12：恢复原运行环境与有限异常链诊断

2026-09-10。用户批准后开始；三模型比较尚未完成。

## 范围

以 SHA 清单核验通过的 v11 R2 十六文件为基线，新建独立 v12。保留 v11、
Job682295 五份本地原始证据和原 v4 全部冻结文件。

恢复原 v4 runner 明确设置的 CUBLAS_WORKSPACE_CONFIG=:4096:8、
OMP_NUM_THREADS=8、TOKENIZERS_PARALLELISM=false。固定值由已验源码生成，
不接受父环境覆盖，在 coordinator/每个 cold child exec 前设置；沿用现有
环境精确核验及启动记录。不是关闭确定性、放宽容差或改变 AMP/TF32/compile。

失败日志新增有界异常链的类型、代码位置和固定原因分类；不记录原始底层
异常消息、args、局部变量、环境或张量。任意异常消息可能包含密钥，故不能
直接 dump traceback/locals。保留原顶层 JSON/退出 2 及所有失败校验。

旧错误只证明 frozen reference prediction failed；环境遗漏已确认，但其为
该失败唯一根因仍未证明。新诊断也不是最终模型评估。

## 验证顺序

1. 新增环境构造、父子启动边界、原 runner 字面值一致性和日志隐私/预算回归。
2. 先 RED 后修复；原 594 项不删除、不弱化，再跑新测试、lint、AST 范围审查。
3. 同版本完整 CPU 准备检查后再决定 GPU 诊断；必须实际验证，不以单测替代。
4. 新 SHA、freeze 和单次提交，终态必须 verify-results；失败不盲重提。

开始时 SSH BatchMode 只读检查返回 255/认证失败；本地工作可继续，未操作远端。

## 本地验收结果

新增启动环境8项：修复前13次失败（含子用例），修复后全部通过。异常日志
初始9项有8项报错；实现后再加日志故障保留原错误回归，10项全部通过。
十三个独立测试入口共612项通过：原594项断言不改，仅协议/路径版本递增，
新增18项。numeric344项90.316秒，submit66项11.755秒；其余202项全部通过。
本地Python3.11.15/torch2.12.1 CPU，不等同于超算2.1.1/cu118/A100验证。

全包 Ruff check/format、runner bash -n、两个 CLI help 通过。AST复查确认生产
仅child_environment增加三个字面值，CLI加stderr有限异常信息与一个helper；
runner/submitter仅版本路径改变。现有bootstrap已在exec前调用同一环境构造器，
没有引入两份可能漂移的环境配置。实际本地bootstrap exec边界验证其最终
环境和BOOTSTRAP_ENVIRONMENT记录完全一致。

六项内存退化全部被测试捕获：分别删除三环境值、允许父值覆盖、泄漏原始
cause消息、遗漏cause链。没有额外代理审查；这是主代理自查，不能冒充独立验收。
v11原十六文件清单再次完整通过；v11失败五份本地原始证据保持不变。

v12候选十八文件清单：
`afb0549063938ecc853c8110b4b4a211357624dfb20fc46dd9da0d1630e5a31b`。
诊断源码：`b5cf658961739a9f9b1ae3532554ce35f28dd43d927af43534dea70928c213a4`。

同版本CPU探针已准备并通过本地源/hash/编译预检，尚未远端执行：
`2026-09-10-diagnostic-v12-remote-cpu-probe.py`。它先设这三个固定值再导入
torch，原CPU保护仍限制torch线程为1，且不执行forward，不等同于GPU正式worker。
临时源码/缓存只在新/tmp目录；不修改HOME、冻结源或旧记录，不提交作业。

## 当前边界

上一轮共享socket不存在。持续目标恢复后实际核验 master47089 存活，已启动
SHA绑定的v12临时CPU探针；其fixed_launch_environment、torch2.1.1+cu118、
24个pinned/96个snapshot读取已通过，完整检查仍在进行。
当前未上传到正式诊断root、未冻结或提交v12，没有新Job ID；不得重提旧作业。

新操作脚本从已核验v11脚本保留所有边界/禁止覆盖/单次提交检查，仅更新版本
及固定SHA。freeze/job尚未产生的脚本使用不可通过的UNREVIEWED占位值，必须
在实际回执到达并审阅后固定；不能推测其值或提前调用提交。

## 实际同版本完整CPU验证通过

临时CPU探针完成，REMOTE_CPU_PROBE_RC=0，FORMAL40_CPU_STATE_SEAL_PROBE_PASS。
原三个固定环境值已在torch导入前设置并记录；torch2.1.1+cu118/CPU线程1。
严格加载61状态键/参数覆盖1.0，扩展70模块清单、210个OrderedDict注册表，
60个唯一状态张量完整快照通过。scene3/model9可调用图通过；指纹work381329，
230个节点、110个代码对象、4个literal缓存，原600000上限不变。
重复指纹、60状态、RNG和scene一致，24pinned/96snapshot最终源复验通过。
没有forward、生产worker签发或GPU数值结果；这只解除部署前CPU门禁。
