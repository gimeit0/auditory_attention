# 2026-09-08 数值诊断 v4 本地回归记录

状态：未发布候选。未成功连接或修改 HAKUSAN，未冻结新输入、未提交作业。
这里的诊断 v4 与已冻结的 same-bank 评估 v4 是不同工具包。

## 背景与本次修复

真实评估 v4 的 Job646900 因批大小 canary 的 formal40_nll 最大绝对差
0.0077362060546875 失败；该数值差异的原因仍未确定。
诊断 v3 的 audit 则被 production evaluator differs from verified loader 阻止。

本地候选通过限制模块注册表特殊处理的对象范围、验证冻结快照模块授权、
在 worker 准备结束后封闭模块集合来修复合法导入造成的身份误报。
新增直接 import 模块绑定检查后，发现本地 torch 首次加载 Dynamo 会替换
torch.manual_seed；源码 torch/_dynamo/__init__.py 明确执行了此包装。
现在固定 SHA 的真实 evaluator 在签发函数图之前导入 Dynamo，不在签发后
重设基线。新增反例确认 manual_seed 和 yaml 模块被替换时仍能检测。

## 本次实测

- 本地 Python 环境：/opt/anaconda3/envs/audattn/bin/python；torch 2.12.1。
- test_numeric_diag：344 项通过，94.575 秒。
- test_submit_numeric_diag：独立进程、-I -B，66 项通过，10.570 秒。
- test_loader_record：独立进程、-I -B，6 项通过，0.318 秒。
- test_real_evaluator_scope：初次 17 项通过；补充篡改检查后独立进程、-I -B，
  21 项通过，0.900 秒。
- 当前共 437 项通过；ruff check、ruff format --check、bash -n 通过。
- 已发布诊断 v3 的八项候选 SHA 校验全部通过，旧文件未修改。

一次错误的合并测试调用（未使用 -I，且同进程混跑提交器与加载器测试）
出现 7 个错误，涉及解释器隔离要求和模块注册表冲突；上面的通过结果来自
按各入口独立进程重新执行，并非忽略失败。真实源码生命周期测试在修复前
曾因 manual_seed 身份变化失败，修复后通过。

## 验收边界与下一步

真实 evaluator 源码测试使用临时快照及部分模拟科学输入，不是完整生产 audit。
本地 torch 2.12.1 不等于集群 torch 2.1.1+cu118。没有真实 checkpoint/音频/A100
推理结果，不能宣称全部潜在问题已排除，也不能发布 SMOKE_PASS。

下一步先复查候选补丁与发布身份，再在新的诊断根受控部署，执行 audit-inputs；
只有 audit 和冻结成功才进入单次诊断作业提交。保留所有旧版本失败证据。
原 bank、checkpoint、SNR、模型角色、数值容差和非独立测试的科学定位均不变。

## 追加只读连接检查

自动执行 ssh -o BatchMode=yes -o ConnectTimeout=10 s2510040@hakusan1 hostname，
返回 255 / Permission denied (publickey,password,hostbased)。不是作业运行失败；
远端命令没有执行。需要用户在其已认证的终端提供只读环境与目录检查输出。
不向用户索取密码。新增四个回归覆盖默认参数篡改、finder 移除、整个注册表替换、
初始化后依赖函数代码原地修改，均通过。

## 用户回传的远端只读预检

用户在 HAKUSAN 登录终端确认 torch 为 2.1.1+cu118；新的诊断 v4 根
same_bank_v4_job646900_2026-09-03_v4 不存在，squeue 用户队列查询无输出。
这些是该次查询的状态，不代表未来队列状态，也不证明候选已通过远端 audit。
本次重新核对 v4-candidate-manifest.sha256 的九个文件全部通过。
下一操作仅准备新诊断根和 staging，不发布到 tools、不冻结、不提交作业。
当前候选的独立发布复查仍未完成；准备空目录不等于批准生产执行。

## 用户回传暂存区校验与独立复查启动

用户回传 DIAG_V4_UPLOAD=PASS / UPLOAD_RC=0，随后在 HAKUSAN 对四个生产
文件逐一校验通过，DIAG_V4_STAGE_VERIFY=PASS / STAGE_VERIFY_RC=0。
目录清单显示文件仅在 .upload-staging，tools 仍为空；尚未发布或执行 audit。
早先在 HAKUSAN 执行 Mac 上传块被 Darwin 检查阻止，不是本次上传失败。

用户明确同意后启动 diag_v4_release_review 只读独立审查，范围为候选代码、
真实失败路径覆盖和发布条件；不连接超算、不修改文件、不提交作业。
主代理重新核对九文件候选清单、bash -n 和 ruff check 均通过。
独立审查结论尚待回传，不将这些静态通过记录视为发布批准。

### 独立审查已返回：Not Ready

diag_v4_release_review 复现合法 src.spatial_attn_lightning 导入仍改变
strict_load_model 的签发函数图，P1 阻断发布。现有测试夹具仅含 selftrain，
437 项通过不足以证明此生产路径。主代理追加隔离主测试344项再次通过，
92.659秒，但不覆盖这个新发现。候选文件及远端暂存文件保持不动。
详见 .superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/
v4-independent-release-review.md。下一步先修复回归，不发布、不冻结、不提交。
