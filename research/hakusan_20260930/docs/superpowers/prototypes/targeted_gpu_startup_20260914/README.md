# GPU child 启动目录顺序修正候选（本地验收）

2026-09-14 JST。修正 Job705468 的 `reference_cold` 独占创建冲突。
旧 `targeted_gpu_job_20260913`、51份控制包固定来源、远端失败目录及
输入清单保持不变；本目录不是新GPU发布包，没有提交入口或资源授权。

## 改动

- `startup.py`：在数值库导入前，使用原固定v18的标准库启动路径独占创建
  scratch、cache及intermediates目录并持有原目录描述符。保留真实HOME，
  原Linux本地挂载/权限/空缓存/符号链接/旧目录拒绝检查不删除。
- 数值库导入后，执行模块仍须由原 `baseline_bridge.load_v18` 签发。
  `bind_scope`将其原spill/mmap类型绑定到同一进程、仍打开的目录描述符；
  不再第二次mkdir，不接管此前运行遗留的目录。绑定、进入均限一次。
- `entry_adapter.py`：由固定旧 `gpu_child.run` 生成候选函数，仅修改启动
  顺序、scratch绑定及启动上下文清理。数值库导入移入原try/finally，故导入
  失败也会保存CHILD错误记录。撤销这些修改后完整AST必须与原函数一致。
- 不改变B2、32条16→1、严格模型加载、编译/观测生命周期、归档数值、
  容差、父结果匹配或GPU资源。旧GPU入口仍是旧源码，不会被本目录替换。

bootstrap加载的v18模块只负责目录创建，不签发模型或worker身份。
真实执行scratch仍继承由原加载器签发的执行模块类型。

## 本地验证与限制

15项测试，4个独立新进程检查全部通过；原GPU候选42项及旧38项回归重跑通过。
原导入顺序在本地torch2.12.1中实际复现FileExistsError；目录审计显示
torch的Dynamo导入链通过Inductor缓存工具先创建 `reference_cold/torchinductor`。
另有显式模拟缓存创建的反例，不与真实导入证据混称。

新reference进程先创建空目录再导入真实候选库链，原合成参考执行完整34次
forward、4个spill/mmap文件和两轮归档重验通过。新observed进程的原加载器
签发、同描述符绑定及清理通过；本轮不把它称作完整观测生命周期验收。

环境：Mac Python3.11.15 / torch2.12.1，CUDA未初始化，生产模型未加载。
本地测试只对Linux挂载判定使用显式 `LOCAL_TEST_MOUNT_STUB`；原目录
工厂的其他逻辑实际执行。此stub仅存在于测试文件，生产候选不含该替换。
这些结果不验证HAKUSAN的torch2.1.1、真实Linux挂载、A100或Inductor前向。

- [本轮完整报告](../../evidence/2026-09-14-job705468-startup-fix-local.md)
- [15项及四新进程回执](../../evidence/gpu-startup-local-20260913T164839Z-8k9s5rji/receipt.json)
- [旧80项回归回执](../../evidence/gpu-job-local-20260913T164544Z-6ovom4be/receipt.json)

仅重跑本地测试（新建独立证据目录，不连接超算）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_gpu_startup_20260914/validate_local.py
```

每个子进程最多90秒、日志最多2MiB；失败保留回执，不自动重试。
错误路径测试会有预期的synthetic traceback，以最终测试结果和回执为准。

下一步：恢复认证后设计并运行有界、无模型加载的同版本CPU启动复验，
使用真实Linux本地挂载检查；通过后把本候选接入新的、独立审核的GPU发布包。
必须更新对应controller/runner路径、源清单及资源申请，不可修改/复用
已提交705468的旧授权，也不可把旧manifest SHA冒充为新代码的身份。
新的GPU运行需要单独授权；当前 `ready_for_gpu=false`、新增作业0。
