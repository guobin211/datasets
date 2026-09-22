# 05 成本与许可证

## 三层成本模型

| 层 | 说明 | 例子 |
|---|---|---|
| 开源软件（免费） | 自建部署 0 许可费 | PostgreSQL、ClickHouse 社区版、Redis、Kafka、RabbitMQ、Pulsar、Qdrant、MongoDB、Elasticsearch |
| 云托管服务（按量） | 「软件 + 运维 + 资源」打包 | COS、云数据库、ClickHouse Cloud |
| 资源与算力（大头） | 无论自建还是上云都省不掉 | 服务器、GPU、磁盘、流量 |

## 许可证速查表

| 组件 | 许可 | 能否免费自用 |
|---|---|---|
| PostgreSQL | PostgreSQL License（宽松） | ✅ 完全免费 |
| ClickHouse 社区版 | Apache 2.0 | ✅ 免费；Cloud/企业功能另收费 |
| Redis 7.4+ / 8.x | RSALv2 / SSPLv1 / AGPLv3 | ✅ 自托管免费；不可商业化再发行/做同类托管 |
| Kafka | Apache 2.0 | ✅ 免费 |
| RabbitMQ | MPL-2.0 | ✅ 免费 |
| Pulsar | Apache 2.0 | ✅ 免费 |
| Qdrant | Apache 2.0 | ✅ 免费 |
| MongoDB | SSPLv1 | ⚠️ 自托管免费；对外提供托管服务需开源整个服务栈 |
| Elasticsearch | ELv2 / SSPLv1 | ⚠️ 自托管免费；禁止对外提供托管服务；可选 OpenSearch |
| COS | 云服务 | ❌ 按量付费（有免费额度） |

## COS 计费参考（腾讯云刊例价，以官网为准）

| 存储类型 | 单价（元/GB/月） |
|---|---|
| 标准存储 | 0.118 |
| 低频存储 | 0.08 |
| 归档存储 | 0.033 |
| 深度归档存储 | 0.01 |
| 下行流量 | 0.5 元/GB |

免费额度：个人用户 50GB、企业用户 1TB 标准存储，免费 6 个月。

## 场景成本估算（数 GB 数据集）

| 项目 | 成本 |
|---|---|
| 软件（PostgreSQL + Redis + Kafka + RabbitMQ + Pulsar + ClickHouse + Qdrant + MongoDB + Elasticsearch 自建） | 0 元 |
| COS 存储（数 GB） | 约 0.1~1 元/月（免费额度内 0 元） |
| 云主机（4C8G 跑全套） | 几百元/月量级（有现成机器则 0） |
| GPU 训练/评测 | 视使用量，预算重点 |

## 成本优化建议

- 冷数据集走生命周期降冷：标准 0.118 → 归档 0.033 元/GB/月，长期可差一个数量级；
- 客户端预签名直传，避免服务端带宽中转；
- 评测结果用列存压缩，artifacts 桶设置生命周期定期清理中间产物。

## 参考资料

- [腾讯云对象存储定价页](https://buy.cloud.tencent.com/price/cos)
- [对象存储 存储容量费用（腾讯云文档）](https://cloud.tencent.com/document/product/436/53482)
- [对象存储 免费额度（腾讯云文档）](https://cloud.tencent.com/document/product/436/6240)
- [Redis Licenses 官方说明](https://redis.io/legal/licenses/)
- [ClickHouse OSS 使用 FAQ](https://clickhouse.com/docs/zh/resources/support-center/knowledge-base/general-faqs/who-is-using-clickhouse)
- [MongoDB Server Side Public License](https://www.mongodb.com/licensing/server-side-public-license)
- [Elastic License](https://www.elastic.co/licensing/elastic-license)
