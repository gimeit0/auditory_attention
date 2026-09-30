# G2 同版本接口检查与编译执行取证候选

2026-09-16。**接口检查通过；真实Inductor执行检查超时，未验收。没有新Slurm作业。**

本目录延续[G2加载准备候选](../g2_profiles_20260916/README.md)，不修改该已验证候选或旧v4/v19源码。

## 本轮已实际执行

- HAKUSAN Python3.11.5/torch2.1.1+cu118，单CPU亲和性、单线程，四组准备设置/API检查通过，34.798秒。
  R/C保留实际包装；D/E改绑同一底层对象，适配前后参数内容、对象、RNG和运行设置一致。
  此步骤没有forward、没有真实checkpoint、CUDA未初始化。
- 读取并哈希实际安装的7份PyTorch源码；确认默认后端是精确的`_TorchCompileInductorWrapper`。
- 新取证候选跟踪“目标编译器返回→该目标生成的代码→该代码实际调用/返回”，不把context进入当成执行证明。
  不挂模型forward hook或替换编译器回调；使用`sys.setprofile`，因此仍须验证观测干扰与开销。
- 10项本地事件匹配/拒绝测试通过；HAKUSAN小型CPU编译检查50.150秒超时、返回-9，临时目录清理成功。
  没有阶段日志，无法定位超时阶段；不能声称Inductor、本候选或G2真实推理已通过。

## 现在可以安全运行的命令

只读复核固定的成功/失败证据，不连接超算、不重试：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_native_20260916/review.py
```

本地事件匹配器测试，不连接超算：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_native_20260916/run_compiled.py test
```

`run_compiled.py native`已主动禁用，避免重复登录节点超时检查。
此前运行源码保存在失败证据目录中；当前子检查已补阶段日志和一次30秒栈，但**尚未远端重跑**。
`run.py native`是此前完成的纯API读取入口，不是编译执行补测或提交命令，现在无需再运行。

## 下一步需批准的独立CPU验证

建议单次计算节点作业：1CPU、6000MiB、10分钟、0GPU；不复用Job718727的授权。
两个独立冷进程依次做同一小型合成模型的原生Inductor基线与带取证运行，各限240秒、监督器540秒；
输入固定、缓存独立，输出/状态/RNG/精度/来源核验，失败即停，不自动重提。
实际分区、账户、内存/GRES和新发布包需提交前再核验。该预算尚未批准，也没有可用的submit命令。

此验证只解决编译取证工程缺口，不能代替formal40真实32条/A100数值矩阵。
完整G2生产worker、来源/输入绑定与独立结果验收仍需集成，G2-M/G2-R GPU预算也未获批准。

详见[本轮证据与后续范围](../../evidence/2026-09-16-g2-native-backend-progress.md)。
