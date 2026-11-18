"""Shop configuration: seeding a new shop with editable defaults, and loading the catalog the engine uses."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Machine, Material, OutsideProcess, RateType, Shop
from .costing.defaults import (DEFAULT_MACHINES, DEFAULT_OUTSIDE, DEFAULT_RATES, DEFAULT_SHOP_SETTINGS, MATERIALS, REFERENCE_DATE)


def ensure_reference_materials(db: Session):
    if db.scalar(select(Material.id).where(Material.shop_id.is_(None)).limit(1)):
        return
    for code, name, aliases, fam, dens, mach, price in MATERIALS:
        db.add(Material(shop_id=None, code=code, name=name, aliases=aliases, family=fam, density_g_cm3=dens, machinability=mach,
                        reference_price_per_kg=price, reference_price_date=REFERENCE_DATE))


def seed_shop(db: Session, name: str) -> Shop:
    shop = Shop(name=name, settings=dict(DEFAULT_SHOP_SETTINGS))
    db.add(shop)
    db.flush()
    ensure_reference_materials(db)
    for key, nm, rate in DEFAULT_RATES:
        db.add(RateType(shop_id=shop.id, key=key, name=nm, rate_per_hour=rate))
    for nm, kind, rk, travel, caps in DEFAULT_MACHINES:
        db.add(Machine(shop_id=shop.id, name=nm, kind=kind, rate_key=rk, travel_mm=travel, capabilities=caps))
    for nm, kw, basis, price, lot in DEFAULT_OUTSIDE:
        db.add(OutsideProcess(shop_id=shop.id, name=nm, keywords=kw, basis=basis, price=price, lot_charge=lot, supplier="(default, verify)"))
    return shop


def shop_catalog(db: Session, shop_id: str) -> dict:
    shop = db.get(Shop, shop_id)
    settings = {**DEFAULT_SHOP_SETTINGS, **(shop.settings or {})}
    rows = db.scalars(select(Material).where(or_(Material.shop_id.is_(None), Material.shop_id == shop_id))).all()
    by_code: dict[str, Material] = {}
    for m in rows:  # shop rows override the global reference row of the same code
        if m.code not in by_code or m.shop_id:
            by_code[m.code] = m
    stale_days = settings.get("material_price_stale_days", 90)
    mats = []
    for m in by_code.values():
        if m.shop_price_per_kg:
            price, src, dt = m.shop_price_per_kg, "shop price", m.shop_price_date
        else:
            price, src, dt = m.reference_price_per_kg, "reference price (not live market data; enter your supplier price)", m.reference_price_date
        stale = False
        if dt:
            try:
                stale = (date.today() - datetime.strptime(dt, "%Y-%m-%d").date()).days > stale_days
            except ValueError:
                pass
        mats.append({"code": m.code, "name": m.name, "aliases": m.aliases, "family": m.family, "density_g_cm3": m.density_g_cm3,
                     "machinability": m.machinability, "price_per_kg": price, "price_source": src + (f", dated {dt}" if dt else "") + (" (STALE)" if stale else ""),
                     "price_stale": stale})
    rates = {r.key: r.rate_per_hour for r in db.scalars(select(RateType).where(RateType.shop_id == shop_id))}
    machines = [{"name": m.name, "kind": m.kind, "rate_key": m.rate_key, "travel_mm": m.travel_mm, "active": m.active, "capabilities": m.capabilities}
                for m in db.scalars(select(Machine).where(Machine.shop_id == shop_id))]
    procs = [{"name": p.name, "keywords": p.keywords, "basis": p.basis, "price": p.price, "lot_charge": p.lot_charge, "markup_pct": p.markup_pct, "supplier": p.supplier, "lead_days": p.lead_days}
             for p in db.scalars(select(OutsideProcess).where(OutsideProcess.shop_id == shop_id))]
    return {"settings": settings, "materials": mats, "rates": rates, "machines": machines, "processes": procs, "currency": shop.currency}
