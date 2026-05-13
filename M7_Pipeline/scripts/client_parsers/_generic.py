"""client_parsers/_generic.py — fallback parser for brands without a dedicated module.

對沒寫專屬 parser 的 brand (DKS/TGT/KOH/UA/ANF/GU/BY/HLF/WMT/QCE/HLA/JF/SAN/DST/ZAR/ASICS/NET/LEV/CATO/SMC...),
extract_pdf_all 還是會跑 page classifier 認 page type, 然後用 GenericParser:
  - parse_cover: 抽不到 (return {})
  - parse_construction_page: 把 page 完整 text 當 raw_text return (給 VLM 之後用)
  - parse_measurement_chart: 抽不到 (return None)

callout page 仍然會 render 成 PNG image, 給 VLM 認 zone/iso。
metadata 跟 mc 要等之後逐 brand 寫專屬 parser。
"""
from __future__ import annotations
from typing import Optional

from ._base import ClientParser


class GenericParser(ClientParser):
    def parse_cover(self, page, text: str) -> dict:
        # 沒結構化 parser, 但保留整頁 text 給之後 fallback
        return {"_raw_cover_text": text[:5000]}  # cap to avoid huge json

    def parse_construction_page(self, page, text: str) -> list[dict]:
        # 給 VLM 之後處理, 這裡只保留 raw text
        return [{"_raw_callout_text": text[:5000]}]

    def parse_measurement_chart(self, page, text: str) -> Optional[dict]:
        # 沒 brand-specific MC parser, fallback skip
        return None
