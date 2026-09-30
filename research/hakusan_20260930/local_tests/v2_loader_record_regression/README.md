# v2 加载器记录不一致：本地回归记录

2026-09-08，根据用户提供的 HAKUSAN 审计错误进行本地复现。

运行命令（工作区根目录）：

```sh
python3 -I -B local_tests/v2_loader_record_regression/test_loader_record.py
```

本轮结果：2 项测试，1 项通过，1 项 ERROR，进程退出码 1。
这是旧生产代码上的预期 RED 回归结果，不是修复完成。

- 真实文件读取证明：两份记录只有 relative_path 不同；其余字段（包括 SHA-256、size、device、inode）全部相同。
- 外层 read_frozen_context 使用 v4 根目录作为基准，得到 tools/locked_same_bank_eval.py。
- load_verified_v4_evaluator 使用文件父目录作为基准，得到 locked_same_bank_eval.py。
- 真实加载器生成 facade 并登记记录后，调用真实生产 capability 注册函数，复现同一错误：production capability requires exact verified loader objects。

边界：使用临时的最小 evaluator、manifest 和 source 文件；manifest 与 inventory 权威登记是测试夹具。没有执行完整 read_frozen_context、真实 v4 evaluator、音频处理、GPU 推理或集群操作。因此该测试证明具体的读取/登记冲突，不代表端到端诊断已经验证。

测试位于已发布包之外。测试后 v2-release-manifest.sha256 的七项校验全部 OK；未修改 v2 生产代码、测试文件或 README。没有创建新的发布版本、冻结输入或提交作业。

下一步：在新的本地候选版本中统一记录基准，保持文件身份、路径边界与篡改拒绝校验，增加完整上下文调用路径覆盖，再运行相关回归与全套测试。不得以移除严格校验来让测试通过。
