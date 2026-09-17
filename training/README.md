# training/ — 训练阶段

本目录承载微调训练侧的工作区，对应数据流水线的最后一个阶段（source → format → evaluation → **training**）。

## 目录结构

| 路径 | 用途 | 状态 |
|---|---|---|
| `data/categorized/` | 微调输入数据：4 个分类桶（question / question-multi / question-answer / question-answer-tool-call），由 `scripts/cate-*.ts` 产出 | 已有（由 `resource/categorized` 迁移而来） |
| `config/` | 训练配置（模型、数据路径、超参、LoRA 等） | 骨架，待补充 |
| `scripts/` | 训练脚本（数据打包、训练启动、评估后处理） | 骨架，待补充 |

## 数据流

```
training/data/categorized/<category>/<source>.jsonl   (归一化后的微调输入)
        │
        ├── 直接用于 SFT 训练（messages 格式）
        └── extract-qa-csv.ts → evaluation/qa-csv/ → build-eval-csv.ts → 评测集
```

- `data/categorized/` 内每条记录为 `{ messages, source_file, line, category }`，`messages` 为标准对话格式，可直接作为微调样本。
- 新增数据源后重新运行分类脚本（`scripts/cate-jsonl.ts` / `cate-other-jsonl.ts`），产物自动写入本目录。

## 待办（骨架占位）

- [ ] `config/`：补充训练配置文件（框架、模型、超参）
- [ ] `scripts/`：补充训练/数据打包脚本
