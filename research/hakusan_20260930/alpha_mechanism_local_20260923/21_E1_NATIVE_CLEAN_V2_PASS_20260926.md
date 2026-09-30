# E1 clean v2原生真实音频检查通过

用户单独批准后，执行唯一一次v2探针；不是自动重试v1。范围为单CPU线程、90秒上限、不加载checkpoint、不使用GPU、不写远端文件。

## 核验结果

- 状态：`E1_NATIVE_CLEAN_REAL_AUDIO_INPUT_PASS`，进程退出码0；远端实测14.771秒，stderr为空。
- 环境：Python3.11.5、PyTorch2.1.1+cu118，threads=1，cuda_initialized=false。
- 200条固定clean，309份真实音频；13批（12×16+8），批次与冻结布局完全一致。
- 原生受审源码中的真实WaveformCache、重采样、crop_centered、raw_scene和role函数体在内存隔离命名空间中执行；全部来源先核验SHA。不是合成音频cache。
- 每批新正确cue非零，并与原生role输出字节一致；零cue与旧clean输出字节一致；新旧两条件target波形与原始target-only输出逐位一致；标签不变。
- 309份远端音频在检查前后均与数据冻结SHA匹配。
- 未加载模型、未提交作业、未上传持久源码文件、无自动重连或重试。

证据：[原始传输结果](e1-clean-native-20260926-v2/TRANSPORT.json)、[核验回执](e1-clean-native-20260926-v2/VERIFIED.json)、[源码及参数绑定](e1-clean-native-20260926-v2/INTENT.json)。VERIFIED.json SHA=`f9f80022b687d2022630aff0e6ffc0c0438ba15c06832e083ca0215800022e0e`。

## 版本绑定与限制

- 数据冻结仍引用 `E1_DATA_FREEZE_20260926_v1.json`，SHA=`6c4df571e897a2c13aa6c693a86783c83ac8620b1f24b7f932ddbe6d93ab62fe`，不修改旧manifest。
- 本次适配器是 `e1_clean_input_v2.py`，SHA=`1bd244b5c71aeed62c14a0da6c2f4b981c5201ccf7953b6d445225ca58231e7b`；通过INTENT和回执单独绑定，后续生产包必须使用此版本而非冻结清单中保留的历史v1适配器。
- v2适配器及探针均改为单维any归约。运行前本地8项回归通过，0.157秒；没有修改冻结E0包和候选ID。
- 此PASS证明原生函数体+真实音频的输入路径通过，**不是完整生产导入器/worker已接通，也不是模型α效应或GPU验收**。

下一步：组装E1生产worker和离线验收器，明确新增clean端点/旁路/重复的全部预测计数与硬超时，再提交最终执行合同和GPU预算申请。当前没有E1 GPU作业号。
