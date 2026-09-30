# E1 v3 本地修正候选

状态：E1_LOCAL_RELEASE_CANDIDATE_PASS。仅本地，不上传、不提交。v1/v2 冻结包保留原字节；v3 以 29 号修正覆盖 28 号中的跨批恒零假设，统计签署与 GPU 预算仍待批准。

修正：完整 D 与 α=0 实测残差归档；生产来源严格验收；包外 CPU 演练显式标为合成。

## 冻结身份

- 唯一新候选：[package_ready](package_ready/)；release SHA `558fa3fb953704b3fbf52952c9e474ef9824dead2e4c0eb2adaaa21a561dffd3`。
- entry SHA `bc3ce55e57f1870df86cf89a48230c88476193afe9fa07a459fd8d30c11c47fd`。
- runner SHA `5f7fa068f203555c6f6ac42764ef70869b7b2488e341b4b25191d5a5adb32341`。
- 输入合同 SHA `396e233463f07b3bce3ba744cea5505bc6be55c560e25de527033a470a6877a7`，样本/批布局与 v2 相同。
- 候选远端目录 `/home/s2510040/audattn_e1/e1_20260927_v3`，本轮未创建。

## 实际核验

- 全目录 unittest：229 项通过，34.690 秒（9 项新增反例）。
- 隔离入口 check：E1_PACKAGE_BYTES_AND_INPUTS_PASS，jobs_submitted=0。
- [三进程合成演练](../e1-release-rehearsal-hhr8ype6/SUMMARY.json)：38400 条，A/B/VERIFY PID 50109、50110、50113；pipeline SHA `e6bf81283010f14cc4fc02a551a473827d1f88b1b213723451fce614e37c0c0f`。checkpoint_loaded=false、cuda_initialized=false、production_ready=false。
- 合成 VERIFY 的来源宽松模式只在包外 rehearse_e1_release.py 使用 mock 显式调用；生产入口始终使用严格默认模式。合成不证明 A100 运行成功。
- 新增反例覆盖 α=0 非零配对项不会被置零；空/错误 runtime、空 GPU、空版本、空显存、无效或倒序时间均被拒绝。

## 复验（从项目根目录）

```sh
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover -s alpha_mechanism_local_20260923 -p 'test_*.py' -q
/opt/anaconda3/envs/audattn/bin/python -I -B alpha_mechanism_local_20260923/release_e1_20260927_v3/package_ready/e1_entry.py check 558fa3fb953704b3fbf52952c9e474ef9824dead2e4c0eb2adaaa21a561dffd3
```

## 下一批边界

先审阅并签署 28+29 两份组成的统计合同；预算与远端上传/提交仍单独批准。尚未实现完整 E1 bootstrap 报告，不将配对算术验收当统计完成。任何后续代码变更都另行冻结，不改此 package_ready。
