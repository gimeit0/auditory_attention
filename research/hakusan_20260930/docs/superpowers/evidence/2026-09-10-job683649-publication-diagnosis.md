# Job683649：参考工件发布失败与下一步范围

## 实际结果

v16完成698项回归、实际torch2.1.1 CPU准备和eager/Inductor合成冷/热检查后，
独立发布、audit/freeze/check-only通过，仅提交一次Job683649。
2026-09-10 18:01:26–18:48:52 JST，spcc-a100g09，47分26秒，FAILED2:0。
验收为`DIAGNOSTIC_FAILURE_RECORDED`、`numeric_results_interpretable=false`，
matrix=null、post_errors=[]。不是Slurm TIMEOUT，不能称为数值差异已解释。

真实失败位于`_execute_worker_passes`调用`write_reference_artifacts`之后，
`_AttemptArtifactStore._publish`调用`_record_at`时拒绝：
`artifact must be a mode-0600 single-link regular file`。
两次reference pass已走到工件写入路径；仅留下含两个pass记录的
`reference_cold/REFERENCE_INPUTS.json`。没有REFERENCE_COMPLETE、A2或完整矩阵，
不得把这个未完成子任务的输出当作已验收实验，也不从它手工恢复成功标记。

六份[原始工件](job-683649-v16/README.md)只读下载，固定SHA全部通过。
PRECHECK/POSTCHECK相同，原v4、v15和v16工具未改，未重提任何作业。

## 无模型的小文件复现

原探针[publication-probe.py](2026-09-10-job683649-publication-probe.py)，SHA
`e368c39121516bb90c296cc986c564441dc04670147a1a23746cd4c73334ff61`。
增强描述符控制[publication-pin-probe.py](2026-09-10-job683649-publication-pin-probe.py)，SHA
`52f60d9305c99f54322d58cb38cad147ce8ef0bd9c5215c8fb5821dc54e5c98c`。
均在HAKUSAN登录节点、固定v16源码SHA下执行；不加载模型、不运行GPU、不提交作业。
每次仅在`/tmp`和既有ops目录下新建随机私有临时目录，测试后清理自身文件。
没有改动科学目录或已有证据；没有绕过主机密钥校验。

| 小文件操作 | `/tmp`观察 | home文件系统观察 |
|---|---|---|
| 固定v16原发布函数 | PASS | 同一single-link错误 |
| private FD保持打开，link后unlink private | nlink=1，无`.nfs` | nlink=2，出现1个`.nfs` |
| unlink private前先关闭private FD | nlink=1 | nlink=1，无`.nfs` |
| 先打开并核对final FD，再关闭private FD、unlink private | nlink=1，FD/路径/内容一致 | nlink=1，FD/路径/内容一致 |

所有测试最终权限为0600。原失败现场未记录瞬时nlink，所以区分观察与推断：
上述相同写入代码/同home文件系统复现强烈支持NFS临时名称/打开描述符的
生命周期兼容性问题，而不是证明原事件瞬时所有stat字段都已被记录。
原代码是在private描述符仍打开时unlink临时名称，然后要求final的nlink=1；
本地文件系统测试未覆盖这一NFS行为。

## 下一步建议（尚未修改生产发布算法、未建v17、未提交新GPU）

1. 在独立候选修复发布顺序：hard-link完成后，以O_NOFOLLOW打开最终名称，
   核对private FD、final FD和两条路径确为同一文件；保持final FD固定文件，
   关闭private FD，再移除自己拥有的临时链接。后续继续要求普通文件、0600、
   **单链接**、SHA/size/身份及祖先目录稳定，禁止覆盖现存目标。
2. 增加真实NFS与本地对照，以及路径替换/额外硬链接/权限变化/短写/异常清理
   的回归；不要用允许nlink=2、睡眠重试或忽略身份检查掩盖问题。
3. 先做有界CPU阶段耗时分析。本轮在冷参考工件发布处结束就用了47分26秒，
   不能保证现有一小时allocation能容纳全矩阵。日志没有逐阶段计时，尚未证明
   编译/推理/各类校验的具体耗时比例。不得把全部47分钟武断归于某个函数。
4. 在性能与发布路径均验收前不再提交GPU。不能扩大原数值容差、替换模型/
   bank/精度/compile、加时或删减矩阵。若需更改校验接受边界或资源合同，
   另行明确审批；原698测试和本轮失败证据保留。

这是一项独立于本轮编译初始化接受边界的新发布/性能工作，不把小文件控制
组成功误写为完整生产修复完成。完整三模型10k对比与科研提交仍未达到。
