# P05b本地实现与回归记录

2026-09-18。状态：LOCAL_LAYOUT_IMPLEMENTATION_TESTED；NOT_READY_FOR_DEPLOYMENT。

实现与限制见[候选README](../../../../same_bank_compare_2026_09_18_layout_v1/README.md)。本轮仅本地代码/文档写入和CPU测试，无SSH、上传、checkpoint正式推理、GPU作业或数值资格批准。

## 最终测试

- [新候选43项](layout-tests.log)：5.162秒，exit0。
- [旧eager21项](old-eager-tests.log)：1.717秒，exit0。
- [旧reader/统计18项](old-readers-tests.log)：2.662秒，exit0。
- [v4基线74项](v4-tests.log)：3.968秒，exit0。
- [CLI与布局SHA](cli-and-layout-sha.log)：命令帮助/固定清单输出，无推理。
- ruff format/check完成，All checks passed。

解释：156项是四组最终测试执行数，新候选43项包含21项迁移回归。此前21项初跑有1项测试接口未迁移的TypeError，已修正并被最终运行覆盖；未删除旧证据或放宽验收以消除错误。CPU测试环境为Python3.11.15、Torch2.12.1，不能代替HAKUSAN的3.11.5/2.1.1+cu118环境验证。

## 关键实现检查

固定四布局；external layout SHA必须匹配规范内容；布局ID、trial顺序、batch成员、原历史scene绑定一起验收。按trial ID匹配condition专属logits和cue，不能把控制子集索引当全bank索引。多余/重复/缺失身份、错误cue、非有限logits、错误AMP/状态声明等均拒绝；有效数值差异如实输出DIFF及翻转，不自动写资格PASS。

合成旧产物经原reader重新验证后，与新bridge16/cold1成功桥接。已确认旧科学函数AST不变，旧科学源码与旧reader SHA均未改。产物验收要求规范执行顺序；比较层在验收后可按trial ID对齐，不承诺任意改写磁盘CSV仍能通过receipt或身份校验。

## 源码与布局指纹（本地候选，不是远端发布回执）

| 文件 | SHA256 |
| --- | --- |
| eager_compare.py | 8a191e7afc5a7e382b26039fb409041910bc250e7b9b84b8a483244d7c3042ed |
| review_layouts.py | a2648549402e3e56b2b670078557ded09b1dbc1015fa00320073088cc65eed23 |
| tests/fixture_model.py | df5143faf57de3eab2ae0fc8373429b9b597eb7c27f24b5ee4c76705264b5b8f |
| tests/test_eager_compare.py | b170a62e66249fc3706ac8b1187df2d66a146a6f1c26b8435614ad9d7d4f9494 |
| tests/test_layouts.py | c1c8d0ebf0d2b604054f40d83346fd0e51be0aa76889b2046f19c6fb79a5098f |
| layouts/bridge16.json | a5d966886f165239da4ed6daaf2501e0df403c859d24ea9e7706b678da0b25b1 |
| layouts/cold1.json | b4e00da4cc8380d58e23372565105662530fca22eefd038ed9481d30a0f4d6b3 |
| layouts/peers16.json | b36d6865a4d0001d0a1c852921aba0f977cab03fd30d8a049da2765130b6e9be |
| layouts/tail17.json | b842944aef89f139bed43054765be74037ab9beefb9351602ed46405b73b4235 |

日志SHA：layout-tests `b1db44681498d8cbd3e9e892e1fe33d123c0ff72273d916a1411138f557fa262`；old-eager `ae9dcbeefda5c0996e51dc1367d0ec5d1f90af87ffd462fd8522ec8448833634`；old-readers `d990d36fed6243c8ebb42bb1445912e33c313ea2a4bd24588bfbc36ea3004043`；v4 `c50574581ddd68baed4c289e26b0ef49c2ae340666f7e31a496ad7ef51071f75`。

## 下一步

实现并测试四进程/限时/桥接门/独占提交与收集包装，再做原生预检及预算确认。当前不提供可运行的GPU提交命令，不能沿用Job725677的submit/release脚本。旧1e-6 DIFF、研究身份、checkpoint选择与全量禁止状态均保持。
