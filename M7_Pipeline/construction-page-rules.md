# Construction Page 辨識規則

> Centric 8 Techpack PDF 中，哪些頁面是「Construction Page」、哪些不是。
> 用於 `detect_callout_pages()` 邏輯、VLM/OCR 提取前的頁面篩選、以及 AI 訓練資料標註。

---

## 一句話定義

Construction Page = **服裝圖示 + 指向特定部位的做工文字標註**。
圖示可以是 flat sketch 或 avatar 穿衣圖；文字必須描述「怎麼車」而非「長什麼樣」。

---

## Construction Page 的三種格式

### 格式 A：文字區塊在上方，圖在下方

最乾淨的格式。做工規格以文字列表寫在頁面頂部，下方放 flat sketch 或 avatar 圖。

**範例**：D188 HR FLOUNCE SKORT
```
All body seams are 607 unless otherwise noted***
WAIST SEAM: 514 + 605
POCKET OPENING & SHORT HEM: Single turnback w/ 602
SKIRT SEAMS: 607 w/ bartacks at hem
SKIRT HEM: Free cut
```

**特徵**：Zone 名稱在冒號前，ISO 或做法在冒號後，一行一個部位。

### 格式 B：箭頭指向 flat sketch

平面款式圖（線稿）左右兩側拉箭頭/引線，每條箭頭配一段做工描述。

**範例**：
- D470 SLEEP PANT —「SET ELASTIC WB TO BODY WITH 1/4" GG 2N3TH COVERSTITCH AT 1/16" MARGIN」
- D1455 WOVEN SHIRT —「SN TS, 1/4" M」「2N TS, 1/4"GG, 1/16" M FELLED SEAM」
- D101 WOVEN DRESS —「Neck & A/H Turn in binding」「Bottom Tiers 1.4:1 Shirring ratio」

**特徵**：通常正面圖在左、背面圖在右，callout 文字散佈在圖的周圍。

### 格式 C：箭頭指向 avatar（人台穿衣）

服裝穿在 Alvanon 3D 人台上，做工文字以彩色或黑字標註。

**範例**：
- D22872 QTR ZIP —「3/8"VOS BINDING ON COLLAR & ZIPPER WELT」「3N5TH COVERSTITCH FOR POCKET STITCHING」
- D20258 BRA — 紅色文字：「3/4" EXPOSED ELASTIC STRAPS W/ ADJUSTABLE SLIDERS」
- D34493 BRA — 紅色文字：「UNDERSTITCHED WITH 2NDL 3TH CS」「INTERNAL MESH LAYER AND LINING FINISHED @ ELASTIC W/ 3NDL 5TH CS」
- D46162 JOGGER — 藍色文字 + 藍色 banner：「1/16"gg SN Chainstich @FRT/BK Rises」「Clean finish」

**特徵**：文字顏色可能是黑/紅/藍，字體大小不一，位置不固定。部分頁面有「CONSTRUCTION CALLOUTS」或「INTERNAL/CONSTRUCTION VIEWS」標題。

---

## 做工描述的辨識信號

Construction page 的文字標註至少包含以下一種：

### ISO 代碼（直接標）
`301` / `401` / `406` / `514` / `602` / `605` / `607` / `514+605`

### 縫法關鍵字（需經 GLOSSARY_TO_ISO 映射）
| 關鍵字 | ISO |
|--------|-----|
| SN TS / SNTS / TOPSTITCH | 301 |
| CHAINSTITCH / CHAIN STITCH | 401 |
| COVERSTITCH / CVRST / CS（2N3TH/3N5TH） | 406 |
| OVERLOCK / SERGE | 514 |
| FLATLOCK / FLATSEAM | 607 |
| BINDING / TURN IN BINDING | BINDING（非 ISO） |
| FELLED SEAM / LAPPED SEAM | 301 系 |
| SATIN STITCH | 304 |
| BARTACK / BAR TACK | 車止 |
| EDGESTITCH | 301 系 |
| CLEAN FINISH / CLEAN FIN | 收邊 |
| TURNBACK / TURN BACK / TURN & TURN | 反摺 |
| UNDERSTITCHED | 壓線 |

### Margin 規格
數字 + 引號格式：`1/4"` / `1/8"` / `3/8"` / `1/16"` / `7/8"` / `1"` / `1 1/4"`
通常搭配 `M`（margin）或 `GG`（gauge）出現。

### 針數描述
`2N` / `3N` / `2NDL` / `3NDL` / `2N3TH` / `3N5TH`（N=needle, TH=thread）

---

## 不是 Construction Page 的頁面類型

### 1. Fit Photo 頁
- **視覺特徵**：真人穿著實品照片（非 sketch、非 avatar 穿線稿）
- **文字特徵**：「PM [日期] ON」「Fit comments:」「Please send revised pattern」「Proceed to final」
- **範例**：D46167 p45、D46091 p46

### 2. Grade Review 頁
- **視覺特徵**：「GRADE REVIEW」藍色 banner + 深色/淺色底打版片疊圖（多色線代表多尺碼）
- **文字特徵**：「Follow GSS」「Overall follow GSS for graded nest」
- **範例**：D45973 p28、D46091 p43

### 3. REF IMAGES / INSPIRATION IMAGES 頁
- **視覺特徵**：產品照片、靈感照片、市場參考圖
- **文字特徵**：標題為「REF IMAGES」「REFERENCE IMAGES」「INSPIRATION IMAGES」「MOCK NECK REFERENCES」
- **範例**：D46096 p37、D46103 p47、D46161 p11、D46162 p49

### 4. Measurement Chart / Evaluation 頁
- **視覺特徵**：POM 表格
- **文字特徵**：表頭含「POM Name」「Description」「Target」「Tol Fraction」「Vendor Actual」「Sample」「QC」
- **範例**：D46162 p37、p39

### 5. ADDITIONAL COMMENTS 頁（工廠回覆）
- **視覺特徵**：「ADDITIONAL COMMENTS」藍色 banner
- **文字特徵**：聚陽（MAKALOT）的製造建議，如「We would like to suggest following construction」「INSEAM/RISE SEAM – sew front and back seam firstly then overlock inseam」
- **⚠️ 注意**：此類頁面**有做工內容**（如具體縫法建議），但性質是工廠回覆建議，不是客人原始 construction spec。如果目標是提取「客人要求的做工」，應排除。如果目標是提取「所有做工資訊」，可納入但需標註來源為 factory_suggestion。
- **範例**：D46167 p41、p42

### 6. Pattern Review 頁
- **視覺特徵**：深色底 + 青色/藍色打版線條 + 紅色箭頭，單一版片放大圖
- **文字特徵**：大段 fit 調整說明，如「Currently the position of the front and back rises are too far apart」「lower the front rise position 1/4"」
- **⚠️ 注意**：文字中可能出現尺寸數字（1/4"），但這是版型修正指令，不是做工規格。
- **範例**：D46167 p44

### 7. 純產品照片頁
- **視覺特徵**：產品實物照片（口袋細節、silhouette），無任何文字標註或箭頭
- **範例**：D46162 p49

---

## 邊界案例處理

### 低密度 construction page
D15602 LEGGING —「V YOLK PANL」「MESH IN WAISTBAND」「SIDE POCKET LARGE ENOUGH FOR IPHONE」
→ 有 avatar 圖 + 箭頭標註，但內容偏設計特徵描述。**仍算 construction page**，但做工資訊密度低，提取時標註 `confidence: low`。

### Woven 的做工描述
Woven 通常不標 ISO 代碼，改用英文方法名：
- 「Turn in binding」（不是 BINDING 裁條，是反摺收邊）
- 「Turn & Turn Clean Finished」
- 「Felled Seam」
- 「Shirring Ratio 1.35:1」（抓皺比例，woven 特有）
→ 仍是 construction page，但 ISO 映射需要 woven-specific 規則。

### ADDITIONAL COMMENTS 的做工內容
D46167 p41 有「INSEAM/RISE SEAM – sew front and back seam firstly then overlock inseam for bulk production friendly」
→ 明確的做工建議（overlock = 514），但來源是工廠不是客人。
→ 建議：提取時標註 `source: factory_suggestion`，與客人 spec 分開存放。

---

## 偵測邏輯建議（給 detect_callout_pages()）

```python
score = 0

# Positive signals（加分）
if has_sketch_or_avatar:           score += 3
if has_arrow_or_leader_line:       score += 2
if text_contains_iso_code:         score += 3
if text_contains_sewing_keyword:   score += 2
if text_contains_margin_spec:      score += 2
if text_contains_needle_count:     score += 1
if title_contains("CONSTRUCTION CALLOUTS"):  score += 3
if title_contains("INTERNAL/CONSTRUCTION"):  score += 3

# Negative signals（扣分 / 直接排除）
if is_real_photo(not_sketch):      score -= 5   # Fit photo / product photo
if title_contains("GRADE REVIEW"): return False
if title_contains("REF IMAGES"):   return False
if title_contains("INSPIRATION"):  return False
if title_contains("REFERENCE IMAGES"): return False
if has_pom_table:                  return False
if title_contains("ADDITIONAL COMMENTS"): score -= 3  # 可選排除

# 判定
return score >= 5
```

---

*最後更新：2026-04-22*
*來源：20 張 Centric 8 PDF 頁面實例分析（10 positive + 10 negative）*
*涵蓋品類：Woven Dress / Skort / Sleep Pant / Woven Shirt / Qtr Zip / Bra / Legging / Jogger / Cargo Pant / Tunic*
