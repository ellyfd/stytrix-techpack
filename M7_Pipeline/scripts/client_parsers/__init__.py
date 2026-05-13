"""client_parsers — per-brand Techpack parser library.

Each brand has its own module with parse_cover / parse_construction_page / parse_measurement_chart methods.
Centric 8 brands (ONY/ATH/GAP/GAP_OUTLET/BR) share centric8.py.

Registry pattern: get_parser(client_code) returns the right module's ClientParser instance.
"""
from __future__ import annotations
from typing import Optional

from ._base import ClientParser
from . import _generic
from . import centric8
from . import dicks
from . import gu as _gu
from . import kohls
from . import target as _tgt
from . import gerber as _gerber
from . import underarmour as _ua
from . import beyondyoga as _by


# Centric 8 同集團 5 家共用一個 parser
CENTRIC8_CODES = {"ONY", "ATH", "GAP", "BR"}

_REGISTRY: dict[str, ClientParser] = {}


def _build_registry():
    global _REGISTRY
    _REGISTRY = {
        "ONY": centric8.Centric8Parser("ONY"),
        "ATH": centric8.Centric8Parser("ATH"),
        "GAP": centric8.Centric8Parser("GAP"),
        "BR":  centric8.Centric8Parser("BR"),
        "DKS": dicks.DicksParser("DKS"),
        "GU":  _gu.GUParser("GU"),
        "KOH": kohls.KohlsParser("KOH"),
        "TGT": _tgt.TargetParser("TGT"),
        # 2026-05-11 新增 4 個 priority parser (~1,272 件 0% meta → 救起)
        "HLF": _gerber.GerberParser("HLF"),  # High Life — Gerber Technology PLM
        "ANF": _gerber.GerberParser("ANF"),  # A&F / Hollister / Gilly Hicks — Gerber Technology PLM
        "UA":  _ua.UnderArmourParser("UA"),  # Under Armour — Cover Sheet Properties
        "BY":  _by.BeyondYogaParser("BY"),   # Beyond Yoga — BILL OF MATERIALS
        # 之後加 WMT(xlsx) / SAN / QCE / HLA / JF / NET / ZAR / DST / ASICS / LEV / CATO / SMC ...
    }


_build_registry()


def get_parser(client_code: Optional[str]) -> ClientParser:
    """Look up parser by short brand code. Falls back to GenericParser if unknown."""
    if not client_code:
        return _generic.GenericParser("UNKNOWN")
    return _REGISTRY.get(client_code, _generic.GenericParser(client_code))


def supported_clients() -> list[str]:
    """List of brand codes with a dedicated parser (excluding generic fallback)."""
    return sorted(_REGISTRY.keys())
