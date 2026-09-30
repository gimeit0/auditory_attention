# Job683076：编译异常与冻结模块绑定失败

2026-09-10；失败分析，不是数值结果。用户既有批准覆盖恢复三个原runner环境
值与有限异常链日志。本轮继续该日志范围，不授权放宽任何通过条件。

## 事实与边界

v12 Job683076 FAILED2:0，A100g05，3分18秒。三个获批固定环境值实际正确。
verify-results认证失败记录；PRE=POST、post_errors=[]、matrix=null；完整证据
和固定SHA见[v12部署记录](2026-09-10-diagnostic-v12-remote-deployment.md)。

异常顺序是预测调用中的BackendCompilerFailed，随后异常出口的live attestation
在verify_runtime_bindings第3054行检测到sealed frozen module bindings changed。
现有日志不能确定底层编译异常种类、哪一个模块改变，也不能解释原NLL差异。

远端实际torch2.1.1的exc.py在BackendCompilerFailed.inner_exception保存底层
异常，而v12日志只遍历标准cause/context。官方源码亦如此：
[PyTorch v2.1.1 exc.py](https://github.com/pytorch/pytorch/blob/v2.1.1/torch/_dynamo/exc.py)。
实际安装文件SHA为f7b58007a693f4063f98e9c98ce458ce83ab60a32ba5f759bf0abee99c94e100。

只读读取计算节点临时目录被SSH host-key验证拒绝，没有绕过该验证。
现存五份原始证据已完整归档并通过哈希验证；不能从缺失日志编造异常消息。

## 同版本有界CPU小测试

探针[2026-09-10-job683076-toy-compile-probe.py](2026-09-10-job683076-toy-compile-probe.py)
读取固定SHA的发布v12/trace，但只创建独立临时src.Toy模型和8元素CPU张量。
不加载权重/音频、不调用生产worker、不用CUDA、不提交作业。线程数1，
可选CPU Inductor编译线程1，私有临时编译缓存；这些只是合成测试条件。

实际torch2.1.1+cu118完成六种case，进程exit0：保留或清除import表绑定时，
成功callback、故意失败callback、真实CPU Inductor均完成预期观测。
六种case都没有protected模块增删替换，原冻结绑定检查没有报错；两个故意
失败case都得到BackendCompilerFailed，其inner_exception是RuntimeError，
且inner_exception不是标准cause。CPU Inductor两个case计算结果通过合成
allclose检查；这不改变或证明生产科学阈值。此前本机2.12.1的纯函数两case
得到相同日志缺口，但不以本机结果替代远端证据。

结论仅限：通用编译失败不必然改变模块表；普通异常链确实会漏掉PyTorch
内部异常。尚未复现正式GPU根因，不能因此豁免late imports或关闭compile。

## 下一项：独立候选的失败遥测补全

保留已发布v12、旧版本和原v4；在独立v13候选中仅补充：

1. 有界遍历BackendCompilerFailed的直接inner_exception字段；不调用任意
   exception属性/str/repr，不输出原消息、环境、locals、张量或源码。
2. 现有绑定不一致分支仍抛同类同消息错误并撤销授权，仅附加有限的
   新增/移除/替换模块名和计数；不改变是否接受的判断。
3. 新回归须覆盖真实同版本异常类型、分支/环/输出限制、恶意属性钩子、
   原绑定拒绝/撤销及旧612断言；生产逐函数AST范围检查。

候选是否部署以实际本地/同版本复核为准，不能凭脚本存在宣称完成。后续若
需要更改导入生命周期、模型执行或任何科学配置，必须另行说明并审批。
本记录创建时没有v13远端目录、freeze或Job，不重提v12。
