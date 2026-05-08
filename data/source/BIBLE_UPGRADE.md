# 五階層 Bible 升級 SOP

## 是什麼

Bible = 聚陽 IE 部門維護的「五階層做工字典」,涵蓋 38 個 L1 部位,每部位下展開
L2(零件) → L3(形狀設計) → L4(工法描述) → L5(細工段)+ machine + grade + IE 標準秒。

## Source-of-truth 邊界

| 角色 | 位置 | 是否進 repo |
|---|---|---|
| **Working source**(IE 部門編輯用) | `五階層展開項目_YYYYMMDD.xlsx`(本機 Drive,~36 MB+) | ❌ 不進 repo |
| **Deliverable**(Bible JSON,前端讀的) | `l2_l3_ie/*.json` 38 檔 + `_index.json` | ✅ 進 repo,~9 MB |
| **Build script** | `scripts/core/build_l2_l3_ie.py` | ✅ 進 repo |
| **L1 name→code 對照表** | `data/source/L2_代號中文對照表.xlsx` | ✅ 進 repo,14 KB,輕量 |

## 為什麼 xlsx 不進 repo

- xlsx 持續增長(20260402 = 9 MB → 20260507 = 36 MB,2.3x),進 repo 會讓 clone 膨脹
- GitHub web upload 限 25 MB,大 xlsx 沒辦法走 web 直傳
- xlsx 是「編輯用 working file」,不是 deliverable;deliverable 是 38 個 JSON
- IE 部門更新節奏跟 platform 不同步,xlsx 在 repo 反而讓兩邊綁死

## 升級流程

### 1. 取得新 xlsx

從 IE 部門拿到新版 `五階層展開項目_YYYYMMDD.xlsx`(通常從 Drive 或共享資料夾)。
放到本機 `Source-Data/` 目錄下(或任意位置)。

### 2. 跑 build script

```bash
# 預設找最新 dated xlsx
python scripts/core/build_l2_l3_ie.py --source path/to/五階層展開項目_YYYYMMDD.xlsx

# 或先 dry-run 看 stats
python scripts/core/build_l2_l3_ie.py --source path/to/xlsx --dry-run
```

腳本會:
- 偵測 xlsx 是新格式(sheet `全部五階層`,2026/05+)還是舊格式(單 sheet,2026/04 之前)
- 用 header 名稱對齊 column index(對 schema 變動有 tolerance)
- 寫出 38 個 `l2_l3_ie/<L1>.json` + `_index.json`

### 3. Diff 確認預期改動

```bash
git diff --stat l2_l3_ie/
git diff l2_l3_ie/_index.json   # 看每檔 size 變化
```

通常 size 大幅成長 = 真的有新工法併進來;若異常縮水要回頭查 xlsx schema 是不是漏欄位。

### 4. Commit + push

```bash
git add l2_l3_ie/
git commit -m "feat(bible): upgrade IE 5-tier from <YYYYMMDD>"
git push origin HEAD
```

### 5. 前端 / API 自動拉新版

`recipes_master.json` 等 derive view 沒直接讀 `l2_l3_ie/`,但 frontend 的「五階層展開查表」
功能會 lazy-fetch。新 commit 進 main 後,下次 user 操作就會拿到新版。

## CI workflow

`.github/workflows/build_l2_l3_ie.yml` 是 `workflow_dispatch` 觸發(手動跑),不再 auto-trigger,
因為 xlsx 不在 repo 裡,沒有 push 事件可以鈎。

如果以後想要更乾淨的 CI 路徑(例如 push xlsx 上 GitHub LFS / Release Asset 由 CI 抓),
再來重新設計觸發機制。

## 已知 xlsx schema 演進

| 版本 | 結構 | columns | 列數 |
|---|---|---|---|
| 20260402 | 單 sheet | 部位/零件/形狀設計/工法描述/細工段/主副/等級/Woven_Knit/Second + 圖片相關 | ~200K |
| 20260507 | 雙 sheet(`語系資料` + `全部五階層`)| 同上 + **尺寸/機種**(machine)+ 圖片名字 + 4 個 *_Sort | 453,870 |

`build_l2_l3_ie.py` 對兩種 schema 都 tolerant — header-based column lookup,新 column 自動帶入,
舊 column 缺也不報錯。

## Step tuple 格式

`l2_l3_ie/<L1>.json` 的 `methods[].steps[]` 是陣列,每筆 step 是 list:

- 4 元素(20260402 之前):`[step_name, grade, seconds, main_sub]`
- 5 元素(20260507+):`[step_name, grade, seconds, main_sub, machine]`

下游 reader 讀前 4 個元素永遠 work,讀第 5 個 (machine) 要先檢查長度。
