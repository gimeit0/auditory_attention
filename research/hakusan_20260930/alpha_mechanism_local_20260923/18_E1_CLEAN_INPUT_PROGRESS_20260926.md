# E1 clean正确cue路径与冻结进度

状态：`E1_CLEAN_INPUT_LOCAL_TEST_PASS_REMOTE_HASH_BLOCKED`。

## 已实现

[e1_clean_input.py](e1_clean_input.py)独立构建同布局的 `target_only_correct_cue` 与 `target_only_zero_cue`：

- 只接受clean、零干扰、非control，核对trial顺序、说话人及独立录音配对。
- 使用受审 `_raw_scene_batch` 构建target-only；正确cue直接走 `_role_batch(..., 'correct_cue', ...)`，不调用会对clean清零的 `_correct_cue_batch`，也不伪造scene_kind。
- 检查输入/输出形状、dtype、有限与非零；cue构建不得修改scene或元数据；返回的两个条件各有独立张量存储和相同target字节。
- 批提供器固定顺序，支持尾批及重复遍历；此模块不加载checkpoint，也不自动绑定/信任任意生产回调。后续生产入口仍须完成源码哈希绑定。

## 测试证据与边界

`/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover -s alpha_mechanism_local_20260923 -p test_e1_clean_input.py -v`：8项通过，0.236秒。

测试从SHA核验的原始源码抽取 `_raw_scene_batch`、`_role_batch`、`_correct_cue_batch` 和 `crop_centered` 的AST函数体，使用明确的合成音频cache与隔离依赖模块。验证原clean路径确实清零，新路径保留cue且target不变；误接清零函数、元数据修改、错误顺序、mixed输入、同录音cue均拒绝；尾批与重复通过。

这比只模拟回调返回值多覆盖了实际旧函数体，但仍是**本地合成输入测试**，不是在超算原生环境执行200条真实音频，也不是GPU/模型验收。本地pandas/torch产生了一条旧函数torch.as_tensor读取只读NumPy掩码的兼容性警告，测试未改旧源码；不把本地警告当成远端模型失败。

## 未完成与阻塞

现有SSH socket检查返回 `No such file or directory`，未自动重连。本轮没有远端哈希读取、上传、作业提交或冻结。

用户终端重新认证：

```bash
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-10-hakusan-connect.sh"
```

连接恢复后只读核验远端音频。完整E1输入冻结不仅要覆盖309份新增clean音频，还要覆盖所选2000条实际使用的target/cue/distractor/shuffled音频及布局；不能以clean子集哈希通过代替全输入冻结。冻结包需记录本地/远端字节比对、候选/anchor/source SHA和剩余执行合同边界。

原候选与E0冻结包保持不变；下一阶段不能绕过上述门槛生成虚假的INPUTS_FROZEN标记。
