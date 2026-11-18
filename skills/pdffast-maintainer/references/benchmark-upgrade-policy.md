# Benchmark 和升级准入门禁

1. 冻结项目 HEAD、Provider/模型/硬件、配置、Manifest/GT 的哈希。相同页必须提供相同版本的 raster-only PNG/PDF，不能把 Native 文本层作为 OCR 参考答案。
2. 先 prepare/plan，后经授权 execute；不要自行下载大模型或执行来源不可信的在线安装脚本。未知依赖环境放在隔离 Worktree/venv。
3. compare 在无 GT 的情况下只代表输出相似度；有 reviewed/approved 人工 GT 才能 score 文字 CER。字面字段出现不代表键值关系正确。
4. evaluate_upgrade.py 的默认初筛：5 页人工确认 GT、两边同一 Manifest 完整配对、候选成功数量不下降、配对 CER 不退化、P95 推理时间不得超出 Baseline 1.25 倍。阈值可按已批准的业务门禁调整。
5. 即便 READY_FOR_END_TO_END，也必须继续做完整 PDF 解析和未知扫描类型的回归，检查内容完整性、表格、公式、顺序、证据、Canonical、Audit、HTTP、成本及 JudgeAI 兼容，经过维护者审批才允许修改生产配置。
6. 无 GT 必须输出 INSUFFICIENT_EVIDENCE；内容退化或无完整配对则 BLOCKED。任何门禁都不自动改写生产 Provider 配置。
7. 不向 GitHub 提交私有 PDF、人工标注 GT、OCR 文本结果、模型权重和日志中的业务内容。