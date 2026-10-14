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
        └── extract-qa-csv.ts → evaluation/third-dataset/qa-csv/ → build-eval-csv.ts → evaluation/upload/ 评测集
```

- `data/categorized/` 内每条记录为 `{ messages, source_file, line, category }`，`messages` 为标准对话格式，可直接作为微调样本。
- 新增数据源后重新运行分类脚本（`scripts/cate-jsonl.ts` / `cate-other-jsonl.ts`），产物自动写入本目录。

## 分布统计

`scripts/stat-categorized.ts` 全量扫描 4 个桶，产出分布看板：

```bash
npx tsx scripts/stat-categorized.ts
```

- 产物：`data/categorized-stats.html`（ECharts 看板，12 张图）、
  `.agents/cache/categorized-stats.json`（结构化结果）
- 维度：条数 / 磁盘体积 / 文本量 / 消息数与角色构成 / 真实 user 轮次 /
  文本量分桶 / 语种 / 数据源 × 桶矩阵 / 解析失败行
- 当前规模：573,455 条 / 1.58 GB，其中单轮问答占磁盘 69%（平均 3,376 字符/条），
  纯提问占条数 50% 但仅占文本量 8.8%

**已知数据缺陷**：`question/claude-sonnet-4-6-opus-4-8-mythos-5-fable-5-openai-finetuning-dataset.jsonl`
有 8 个解析失败行（约合 2 条记录），源于历史产物写入时 user 文本中的换行未转义被物理断行。
当前 `scripts/utils.ts` 已改用 `JSON.stringify` 写入，重跑该数据源分类即可消除。

## 待办（骨架占位）

- [ ] `config/`：补充训练配置文件（框架、模型、超参）
- [ ] `scripts/`：补充训练/数据打包脚本
