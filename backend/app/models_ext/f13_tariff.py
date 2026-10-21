"""F13 tariff: the hospital's price list. Reference data, so it is not resettable."""

from __future__ import annotations

from sqlalchemy import Column, Float, String

from ..db import Base

TARIFF_KINDS = ("procedure", "medication", "investigation", "consult", "bed_day")


class TariffItem(Base):
    __tablename__ = "tariff_items"

    code = Column(String, primary_key=True)
    description = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # procedure | medication | investigation | consult | bed_day
    unit_price = Column(Float, nullable=False, default=0)
