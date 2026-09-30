# 独立进程归档：超算同版本CPU复验已验收

2026-09-12 JST。用户运行认证后立即复验的单次入口，输出
REMOTE_ARCHIVE_LOCAL_RECHECK=PASS、ARCHIVE_CPU_PIPELINE_RC=0。
代理随后只读复核原始证据，没有重跑远端测试或提交GPU作业。

## 已核实结果

- 远端Python3.11.5、torch2.1.1+cu118，31项归档单元测试全部通过、零跳过，
  用时1.663秒。CUDA未初始化，未加载生产模型，jobs_submitted=0。
- dependent合成对照使用两个独立Python进程：reference PID553517、observed
  PID553661。两者各执行原合成计划32条输入、16→1顺序的34批；使用独立缓存，
  不使用Dynamo reset替代新进程。后端为eager，不是Inductor。
- 两个合成目标0/28的首个观测差异均为index2、model._orig_mod.gain、mixture，
  符合人工设定的差异；参考与观测端点门禁通过。捕获数据共384字节。
- 21份回传工件共1,025,811字节：两份archive.json、16份捕获文件、两份子进程
  日志和一份pair回执。Mac端完整字节重验一致；远端专属临时目录正常清理。

最终回执状态为REMOTE_ARCHIVE_CPU_AND_LOCAL_RECHECK_PASS、returncode=0、
error=null。此后代理在新的本地只读进程中再次核对十份固定源码、驱动SHA、
由固定源码重新生成的bootstrap与保存版本逐字节一致、原始输出和回执SHA，
原输出JSON与回执字段一致，21份文件与原输出base64解码字节一致。
独立ArchiveReader重验预期SHA/角色/计划/绑定/进程身份及所有捕获字节，复算
结果与远端及首次Mac检查一致：INDEPENDENT_REMOTE_ARCHIVE_RECHECK_PASS。
本次独立复核没有模型forward。原v18二十八项release SHA也全部仍通过。

## 证据入口及固定摘要

- [原始超算输出](archive-remote-cpu-20260911T152452Z-bcyhkj5v/output.log)
- [完整回执](archive-remote-cpu-20260911T152452Z-bcyhkj5v/receipt.json)
- [独立进程对照回执](archive-remote-cpu-20260911T152452Z-bcyhkj5v/remote-pair/PAIR_RECEIPT.json)
- [参考归档](archive-remote-cpu-20260911T152452Z-bcyhkj5v/remote-pair/reference/archive.json)
- [观测归档](archive-remote-cpu-20260911T152452Z-bcyhkj5v/remote-pair/observed/archive.json)

| 原始文件 | SHA256 |
|---|---|
| receipt.json | f0ff69048a5d340490dd9f519e199324ae98ac683e8e8fd39b3134d2f999a900 |
| output.log | dd1fbfbe05c884b071f0323e8440b4d103c57db14f8073ba9e972d1902f3e6e3 |
| bootstrap.py | ba53847cc353a5f465a7f6e9fe004267ee595777010a79c8110deea38824a9ca |
| PAIR_RECEIPT.json | 015d3424f6047706af14259255326c364a8ea230c776a142e630e1bdbda3bbd5 |
| reference/archive.json | 29ba8a4e13ce2bf96ccf050f108e9e2c160e0243b5946511196fe149eeb22102 |
| observed/archive.json | e2c837ba7b3ff55dbda0af78b91efac9aa244ad290e827bb082fb60daf04e193 |

原始输出最后一条JSON内含完整合成工件的base64载荷，避免直接打印整个文件。
用前40行查看测试计数及子进程返回码，读取回执查看结构化结果。

## 验收范围与下一项

本次31项是对同一套本地31项的超算版本复验，不计成62项独立测试。
远端额外运行了一组dependent对照；本地已有的invariant/interference两组
没有在此次远端重新运行。单次入口的9项离线测试是另一层入口行为检查。
合成trial0/28不是生产trial的数值结果，384字节不是生产采集量估计。

ready_for_gpu=false、production_execution_authority_verified=false保持。
端点一致不证明内部编译图等价。本阶段不证明真实formal40/Inductor/A100
观测不会干扰执行，也没有解释完Job685198的批大小差异。

下一项：把已经验证的绑定、分块采集、独立进程和归档接入真实生产worker
执行检查；重建完整原32条输入并核对v18边界摘要，再验收A100冷参考/观测。
不得关闭compile、修改精度设置、放宽1e-6阈值或绕过检查来获得PASS。
最终三模型smoke、10000条bank及control对比和置信区间仍未完成，结果必须
标注REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST。
本次无需再次运行连接/CPU入口或任何旧GPU提交脚本。
