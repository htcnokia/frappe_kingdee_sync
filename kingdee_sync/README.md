# Kingdee Sync

从金蝶云星空 (K3Cloud) WebApi 同步基础资料/单据到 Frappe，全部通过前端界面配置，无需改代码：

- **Kingdee Settings**（单例）：服务器地址、账套ID、AppID/Secret、登录用户名密码
- **Kingdee Sync Profile**：一个同步方案 = 一个 K3 FormId 查询（FieldKeys / FilterString / OrderString / Limit）+
  目标 Frappe DocType + 字段映射表 + Cron 定时表达式
- **Kingdee Sync Field Mapping**：K3 字段 <-> Frappe 字段映射，标记其中一个字段作为"匹配键"（通常用 K3 内码，如
  FMATERIALID / FCUSTID / FSUPPLIERID）用于判断记录是否已存在
- **Kingdee Sync Log**：每次同步的执行记录（成功/失败、新建数、更新数、失败明细）

## 安装

```bash
cd ~/frappe-bench
# 1) 把本目录放到 apps/kingdee_sync
./env/bin/pip install -e apps/kingdee_sync
bench --site <你的site> install-app kingdee_sync
bench --site <你的site> migrate
bench restart
```

## 使用步骤

1. 打开 **Kingdee Settings**，填写服务器地址 / 账套ID / AppID / AppSecret / 用户名密码，点击"测试连接"确认成功。
2. 打开 **Kingdee Sync Profile**，新建一个方案，例如同步物料：
   - `Form Id` = `BD_MATERIAL`
   - `Field Keys` = `FMATERIALID,FNumber,FName,FSpecification`
   - `Filter String`（可留空，或用 SQL Server 表达式）= `FCreateOrgId.FNumber='10'`
   - `Order String`（可留空）= `FNumber`
   - `Target DocType` = `Item`
   - 字段映射表：
     | K3 字段 | Frappe 字段 | 匹配键 |
     |---|---|---|
     | FMATERIALID | custom_kingdee_id | ✅ |
     | FNumber | item_code | |
     | FName | item_name | |
     | FSpecification | description | |
   - `Cron 表达式` = `0 */2 * * *`（每2小时同步一次）
3. 点击"预览数据"确认字段和过滤条件正确，再点击"立即同步"手动跑一次，或等待定时任务自动执行。
4. 在 **Kingdee Sync Log** 中查看每次同步的结果。

> **K3 内码自动落地**：Profile 上默认勾选"自动创建缺失的自定义字段"，同步前会自动检测字段映射
> （含匹配键，如 `FMATERIALID`/`FCUSTID`/`FSupplierId`）在目标 DocType 上是否存在对应字段，
> 不存在会自动用 Custom Field 建出来，不需要提前手工 Customize Form。如果想自己控制字段创建，
> 关掉这个开关即可。

## 物料多规格 / 辅助属性变体

金蝶常用"辅助资料"类自定义字段在物料上标记规格（例如某字段 `F_WSDY_Assistant_peima`，字段名
完全由你在方案里配置，程序不写死）。该字段本身只存一个**引用键**（如 `FId`），要拿这个键去
**辅助资料明细**（默认 FormId 为 `BOS_ASSISTANTDATA_DETAIL`，同样可配置成其他表单）里按匹配字段
查出对应明细行的编码/值/内码。

在 `Kingdee Sync Profile` 上打开 `Is Variant Material`，然后在 `Variant Attributes` 子表里配置每一个
辅助属性字段，例如：

| 字段 | 示例值 | 说明 |
|---|---|---|
| K3 物料字段 | `F_WSDY_Assistant_peima` | 物料上存放引用键的字段 |
| 取值子字段 | （留空或按需填） | 若需要 `字段.子属性` 语法取值才填 |
| 对应 Item Attribute | `配码` | 不存在会自动创建 |
| 辅助资料明细 FormId | `BOS_ASSISTANTDATA_DETAIL` | 用来解析引用键的表单 |
| 明细表-匹配字段 | `FId` | 明细表里用来匹配引用键的字段 |
| 明细表-编码字段 | `FNumber` | |
| 明细表-值字段 | `FDataValue` | 作为规格值文本(Item Attribute Value) |
| 明细表-内码字段 | `FEntryID` | 该明细行的实体主键 |
| 内码存储字段(Frappe) | `kingdee_entry_id` | 自动在 Item Attribute Value 上建此字段保存内码 |

同步时会：
1. 按方案预取一次辅助资料明细字典（避免逐行查询 K3）；
2. 对每条物料，用引用键在字典里匹配出具体明细，取值字段作为规格值；
3. 自动确保对应 `Item Attribute` / `Item Attribute Value` 存在（含内码字段），写入 Item 的
   `attributes` 子表，并把 `has_variants` 置为 0；
4. 若配置了"母件字段(Variant Of - K3 字段)"，还会反查母件 Item 写入 `variant_of`。

> 该功能依赖 ERPNext 的 `Item Attribute` / `Item Attribute Value` / `Item.attributes` /
> `Item.has_variants` / `Item.variant_of`，仅安装了 ERPNext 的站点才会生效；不需要时把
> `Is Variant Material` 关掉即可，不影响其他 Profile 的普通字段同步。

