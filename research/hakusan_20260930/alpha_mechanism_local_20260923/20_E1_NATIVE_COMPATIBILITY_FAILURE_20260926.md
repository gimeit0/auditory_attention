# E1原生CPU检查失败与本地v2候选

本次唯一一次远端CPU检查未通过；没有GPU提交、checkpoint加载或自动重试。

证据：[TRANSPORT.json](e1-clean-native-20260926-v1/TRANSPORT.json)，returncode=1。原生PyTorch2.1.1拒绝 `torch.any(t != 0, dim=(1,2))`，调用栈停在首批 `clean_pair -> tensor_ok`，尚未完成新cue/旧cue比较。不是90秒超时，不是音频字节不一致，不应解释成模型效果失败。

本地PyTorch2.12.1支持该写法，因而此前本地8项通过未发现原生API差异。修正采用形状已验证后的 `torch.any((t != 0).reshape(n,-1),dim=1)`，仍逐样本检查全部通道/时间位置，不改变音频、dtype或数值。

保留已冻结的 `e1_clean_input.py` 和所有v1证据；新建 [e1_clean_input_v2.py](e1_clean_input_v2.py) 与对应 [8项测试](test_e1_clean_input_v2.py)，本地回归通过（0.129秒）。不宣称原生通过。

下一次探针还必须将探针自身 `torch.any(c!=0,dim=(1,2))` 改为等价的单维归约；不能只改适配器后漏掉验收代码。应另建v2探针与源码绑定记录，引用同一已冻结候选ID、音频清单及数据身份，不能修改旧manifest里的代码SHA后冒充旧包。

数据身份冻结继续有效（候选/anchor/音频未改变），但执行代码v1不具备原生兼容性，production_ready仍为false。需审定v2源码与新一次90秒单线程原生CPU检查，单独授权后执行，无自动重试。
