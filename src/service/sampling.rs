//! 抽样：随机 / 顺序 / 分层（条件抽样）。
//!
//! 三条口径贯穿所有策略：
//! - **输出保持原始行序**：抽完再按原下标排序，便于 diff 与复跑比对；
//! - **同 seed 可复现**：`--seed` 决定 `StdRng`，不传则用系统熵（不可复现，仅适合一次性冒烟）；
//! - **要的比有的多就全给**：`n >= 总行数` 时原样返回，不报错。

use std::collections::BTreeMap;

use rand::SeedableRng;
use rand::seq::SliceRandom;

use crate::dataset::reader::Row;

/// 抽样规模：绝对条数（`1000`）或占**筛选结果**的比例（`10%`）。
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum SampleSize {
    Count(u64),
    Percent(f64),
}

impl SampleSize {
    /// 换算为实际条数。
    ///
    /// 比例四舍五入，并夹到 `[1, total]`——用户写了 `--sample 1%` 却因为基数太小
    /// 算出 0 条、最后拿到空数据集，比给 1 条更难排查。
    pub fn resolve(&self, total: usize) -> usize {
        if total == 0 {
            return 0;
        }
        match self {
            Self::Count(n) => (*n as usize).min(total),
            Self::Percent(p) => (((total as f64) * p / 100.0).round() as usize).clamp(1, total),
        }
    }
}

impl std::str::FromStr for SampleSize {
    type Err = String;

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        let s = s.trim();
        if let Some(percent) = s.strip_suffix('%') {
            let value: f64 = percent
                .trim()
                .parse()
                .map_err(|_| format!("非法抽样比例 `{s}`，示例：10%"))?;
            if !(value > 0.0 && value <= 100.0) {
                return Err(format!("抽样比例须在 (0, 100] 之间，收到 `{s}`"));
            }
            return Ok(Self::Percent(value));
        }
        let value: u64 = s
            .parse()
            .map_err(|_| format!("非法抽样规模 `{s}`，支持条数（1000）或比例（10%）"))?;
        if value == 0 {
            return Err("抽样条数须大于 0".to_string());
        }
        Ok(Self::Count(value))
    }
}

impl std::fmt::Display for SampleSize {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Count(n) => write!(f, "{n}"),
            Self::Percent(p) => write!(f, "{p}%"),
        }
    }
}

/// 层内取数方式。
#[derive(Debug, Clone, Copy, PartialEq, Eq, clap::ValueEnum)]
pub enum SampleStrategy {
    /// 取前 N 条（不洗牌，`--seed` 无效）
    Head,
    /// 按 `--seed` 确定性随机抽取
    Random,
}

/// 抽样方案（`--sample` / `--sample-by` / `--sample-strategy` / `--seed` 的合集）。
#[derive(Debug, Clone, Default)]
pub struct SamplePlan {
    pub size: Option<SampleSize>,
    /// 分层字段：按该列取值分层，各层按占比分配额度
    pub by: Option<String>,
    pub strategy: Option<SampleStrategy>,
    pub seed: Option<u64>,
}

impl SamplePlan {
    fn strategy(&self) -> SampleStrategy {
        self.strategy.unwrap_or(SampleStrategy::Random)
    }

    fn rng(&self) -> rand::rngs::StdRng {
        match self.seed {
            Some(seed) => rand::rngs::StdRng::seed_from_u64(seed),
            None => rand::rngs::StdRng::from_entropy(),
        }
    }
}

/// 按方案抽样。未指定 `--sample` 时原样返回。
pub fn apply<'a>(rows: &[&'a Row], plan: &SamplePlan) -> Vec<&'a Row> {
    let Some(size) = plan.size else {
        return rows.to_vec();
    };
    let n = size.resolve(rows.len());
    if n >= rows.len() {
        return rows.to_vec();
    }
    let picked = match &plan.by {
        Some(field) => stratified_indices(rows, field, n, plan),
        None => flat_indices(rows.len(), n, plan),
    };
    take(rows, picked)
}

/// 整体抽样：按策略从全部行里取 n 条。
fn flat_indices(total: usize, n: usize, plan: &SamplePlan) -> Vec<usize> {
    match plan.strategy() {
        SampleStrategy::Head => (0..n).collect(),
        SampleStrategy::Random => {
            let mut idx: Vec<usize> = (0..total).collect();
            idx.shuffle(&mut plan.rng());
            idx.truncate(n);
            idx
        }
    }
}

/// 分层抽样：按 `field` 取值分层，按各层占比分配额度，层内再按策略取。
///
/// 额度用**最大余数法**补齐，保证各层之和恰好等于 n（按比例直接取整会少给几条）。
/// 余数相同时优先给大层，再按分层键排序，保证同一输入永远得到同一结果。
///
/// 注意：这是**纯比例分配**，占比过小的层可能分不到额度（如 10 条里 1 条的层、抽 50%，
/// 额度算出来是 0.5 条）。需要每层保底就提高 `--sample`，或对该层单独跑一次 prepare——
/// 这里不做"每层至少 1 条"的兜底，否则层数多于 n 时无解，且会悄悄破坏比例。
///
/// 字段缺失的行归入 `""` 层——不静默丢弃，否则统计口径会和 `--where` 的筛选结果对不上。
fn stratified_indices(rows: &[&Row], field: &str, n: usize, plan: &SamplePlan) -> Vec<usize> {
    // BTreeMap 保证分层遍历顺序稳定，否则同 seed 不可复现
    let mut strata: BTreeMap<&str, Vec<usize>> = BTreeMap::new();
    for (i, row) in rows.iter().enumerate() {
        strata
            .entry(row.get(field).unwrap_or_default())
            .or_default()
            .push(i);
    }

    let total = rows.len();
    let sizes: Vec<usize> = strata.values().map(Vec::len).collect();
    // n < total 保证 floor(n*size/total) < size，层内额度不会超过层本身大小
    let mut quotas: Vec<usize> = sizes.iter().map(|size| n * size / total).collect();

    // 最大余数法：余数大的先补；余数相同给大层，再按分层键顺序，保持确定性
    let remainders: Vec<usize> = sizes.iter().map(|size| n * size % total).collect();
    let assigned: usize = quotas.iter().sum();
    let mut order: Vec<usize> = (0..quotas.len()).collect();
    order.sort_by(|a, b| {
        remainders[*b]
            .cmp(&remainders[*a])
            .then(sizes[*b].cmp(&sizes[*a]))
            .then(a.cmp(b))
    });
    for slot in order.into_iter().take(n.saturating_sub(assigned)) {
        quotas[slot] += 1;
    }

    let mut rng = plan.rng();
    let mut picked = Vec::with_capacity(n);
    for (members, quota) in strata.values().zip(&quotas) {
        match plan.strategy() {
            SampleStrategy::Head => picked.extend(members.iter().take(*quota).copied()),
            SampleStrategy::Random => {
                let mut shuffled = members.clone();
                shuffled.shuffle(&mut rng);
                shuffled.truncate(*quota);
                picked.extend(shuffled);
            }
        }
    }
    picked
}

/// 按下标取行，并恢复原始行序。
fn take<'a>(rows: &[&'a Row], mut picked: Vec<usize>) -> Vec<&'a Row> {
    picked.sort_unstable();
    picked.into_iter().map(|i| rows[i]).collect()
}

#[cfg(test)]
mod tests {
    use super::{SamplePlan, SampleSize, SampleStrategy, apply};
    use crate::dataset::reader::{Row, parse_jsonl_for_test};

    fn rows_of(jsonl: &str) -> crate::dataset::reader::Rows {
        parse_jsonl_for_test(jsonl)
    }

    fn refs(data: &crate::dataset::reader::Rows) -> Vec<&Row> {
        data.rows.iter().collect()
    }

    fn values(rows: &[&Row], field: &str) -> Vec<String> {
        rows.iter()
            .map(|r| r.get(field).unwrap_or_default().to_string())
            .collect()
    }

    #[test]
    fn parses_count_and_percent() {
        assert_eq!(
            "1000".parse::<SampleSize>().unwrap(),
            SampleSize::Count(1000)
        );
        assert_eq!(
            "10%".parse::<SampleSize>().unwrap(),
            SampleSize::Percent(10.0)
        );
        assert_eq!(
            "2.5 %".trim().parse::<SampleSize>().unwrap(),
            SampleSize::Percent(2.5)
        );
        for bad in ["0", "-5", "abc", "0%", "101%", "%", "10%%"] {
            assert!(
                bad.parse::<SampleSize>().is_err(),
                "{bad} should be rejected"
            );
        }
    }

    #[test]
    fn percent_rounds_but_never_to_zero() {
        assert_eq!(SampleSize::Percent(50.0).resolve(10), 5);
        // 1% of 10 → 0.1，夹到至少 1 条，避免静默产出空数据集
        assert_eq!(SampleSize::Percent(1.0).resolve(10), 1);
        assert_eq!(SampleSize::Percent(100.0).resolve(10), 10);
        assert_eq!(SampleSize::Count(99).resolve(10), 10);
        assert_eq!(SampleSize::Percent(50.0).resolve(0), 0);
    }

    #[test]
    fn head_takes_prefix_and_random_is_reproducible() {
        let data = rows_of("{\"i\":1}\n{\"i\":2}\n{\"i\":3}\n{\"i\":4}\n{\"i\":5}\n{\"i\":6}\n");
        let rows = refs(&data);

        let head = apply(
            &rows,
            &SamplePlan {
                size: Some(SampleSize::Count(3)),
                strategy: Some(SampleStrategy::Head),
                ..SamplePlan::default()
            },
        );
        assert_eq!(values(&head, "i"), ["1", "2", "3"]);

        let plan = SamplePlan {
            size: Some(SampleSize::Count(3)),
            strategy: Some(SampleStrategy::Random),
            seed: Some(42),
            ..SamplePlan::default()
        };
        let a = apply(&rows, &plan);
        assert_eq!(values(&a, "i"), values(&apply(&rows, &plan), "i"));
        assert_eq!(a.len(), 3);
        // 输出保持原始行序
        let mut sorted = values(&a, "i");
        sorted.sort();
        assert_eq!(values(&a, "i"), sorted);
    }

    #[test]
    fn sample_larger_than_input_keeps_everything() {
        let data = rows_of("{\"i\":1}\n{\"i\":2}\n");
        let rows = refs(&data);
        let all = apply(
            &rows,
            &SamplePlan {
                size: Some(SampleSize::Count(10)),
                seed: Some(1),
                ..SamplePlan::default()
            },
        );
        assert_eq!(all.len(), 2);
        assert_eq!(apply(&rows, &SamplePlan::default()).len(), 2);
    }

    #[test]
    fn stratified_allocates_proportionally() {
        // zh 6 / en 3 / ja 1，共 10 条，抽 5 条：
        // 比例取整得 3 / 1 / 0（共 4），余 1 条按最大余数法补——en 与 ja 余数同为 5，
        // 优先给大层 en，最终 3 / 2 / 0。ja 占比太小分不到额度，是纯比例分配的固有结果。
        let mut jsonl = String::new();
        for lang in ["zh"; 6] {
            jsonl.push_str(&format!("{{\"lang\":\"{lang}\"}}\n"));
        }
        for lang in ["en"; 3] {
            jsonl.push_str(&format!("{{\"lang\":\"{lang}\"}}\n"));
        }
        jsonl.push_str("{\"lang\":\"ja\"}\n");

        let data = rows_of(&jsonl);
        let rows = refs(&data);
        let picked = apply(
            &rows,
            &SamplePlan {
                size: Some(SampleSize::Count(5)),
                by: Some("lang".into()),
                strategy: Some(SampleStrategy::Random),
                seed: Some(7),
            },
        );

        assert_eq!(picked.len(), 5, "最大余数法必须补齐到恰好 n 条");
        let langs = values(&picked, "lang");
        assert_eq!(langs.iter().filter(|l| *l == "zh").count(), 3);
        assert_eq!(langs.iter().filter(|l| *l == "en").count(), 2);
        assert_eq!(langs.iter().filter(|l| *l == "ja").count(), 0);
    }

    #[test]
    fn stratified_keeps_missing_field_as_its_own_stratum() {
        let data = rows_of("{\"lang\":\"zh\"}\n{\"lang\":\"zh\"}\n{\"other\":1}\n{\"other\":2}\n");
        let rows = refs(&data);
        let picked = apply(
            &rows,
            &SamplePlan {
                size: Some(SampleSize::Count(2)),
                by: Some("lang".into()),
                strategy: Some(SampleStrategy::Head),
                seed: None,
            },
        );
        assert_eq!(picked.len(), 2);
        // 缺字段的行归入 "" 层，两层各 1 条，不被静默丢弃；
        // 输出按原始行序（zh 在文件里排前面），而非分层顺序
        assert_eq!(values(&picked, "lang"), ["zh", ""]);
    }

    #[test]
    fn stratified_is_reproducible_with_same_seed() {
        let mut jsonl = String::new();
        for i in 0..30 {
            jsonl.push_str(&format!("{{\"i\":{i},\"g\":\"g{}\"}}\n", i % 3));
        }
        let data = rows_of(&jsonl);
        let rows = refs(&data);
        let plan = SamplePlan {
            size: Some(SampleSize::Percent(30.0)),
            by: Some("g".into()),
            strategy: Some(SampleStrategy::Random),
            seed: Some(11),
        };
        assert_eq!(
            values(&apply(&rows, &plan), "i"),
            values(&apply(&rows, &plan), "i")
        );
        assert_eq!(apply(&rows, &plan).len(), 9);
    }
}
