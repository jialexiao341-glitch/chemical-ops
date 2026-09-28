"""创建本地开发所需的演示计量单位和供应商。"""

from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.chemicals.model import Chemical
from app.modules.inventory.model import Warehouse, WarehouseLocation
from app.modules.products.model import Product
from app.modules.products.category_model import ProductCategory
from app.modules.purchase_requests.model import Unit
from app.modules.suppliers.model import Supplier


UNITS = (
    ("KG", "千克", "MASS"),
    ("L", "升", "VOLUME"),
)

SUPPLIERS = (
    ("SUP-2026-9001", "海川试剂供应中心"),
    ("SUP-2026-9002", "华研化工材料"),
)

DEMO_CHEMICAL = {
    "chemical_name": "乙醇",
    "english_name": "Ethanol",
    "cas_no": "64-17-5",
    "chemical_formula": "C2H6O",
    "molecular_weight": 46.068,
    "status": "ACTIVE",
}

DEMO_PRODUCT = {
    "product_code": "PRD-ETHANOL-99",
    "product_name": "乙醇 99%",
    "model": "AR",
    "purity_value": 99,
    "purity_unit": "%",
    "packaging_spec": "25kg/桶",
    "parameter_json": {"certificate_required": True},
    "version_no": 1,
    "status": "ACTIVE",
}

DEMO_WAREHOUSE = ("WH-2026-9001", "化学品综合仓")
DEMO_LOCATION = ("A-01-01", "A区 01 排 01 位")


def main() -> None:
    """幂等创建演示主数据，不覆盖已有信息。"""

    db = SessionLocal()
    try:
        for unit_code, unit_name, dimension in UNITS:
            unit = db.scalar(select(Unit).where(Unit.unit_code == unit_code))
            if unit is None:
                db.add(Unit(unit_code=unit_code, unit_name=unit_name, dimension=dimension, status="ACTIVE"))

        for supplier_code, supplier_name in SUPPLIERS:
            supplier = db.scalar(select(Supplier).where(Supplier.supplier_code == supplier_code))
            if supplier is None:
                db.add(
                    Supplier(
                        supplier_code=supplier_code,
                        supplier_name=supplier_name,
                        country_code="CN",
                        status="ACTIVE",
                    )
                )

        chemical = db.scalar(select(Chemical).where(Chemical.cas_no == DEMO_CHEMICAL["cas_no"]))
        if chemical is None:
            chemical = Chemical(**DEMO_CHEMICAL)
            db.add(chemical)
            db.flush()
        unit = db.scalar(select(Unit).where(Unit.unit_code == "KG"))
        product = db.scalar(select(Product).where(Product.product_code == DEMO_PRODUCT["product_code"]))
        if product is None and unit is not None:
            db.add(Product(chemical_id=chemical.id, unit_id=unit.id, **DEMO_PRODUCT))
        warehouse = db.scalar(select(Warehouse).where(Warehouse.warehouse_code == DEMO_WAREHOUSE[0]))
        if warehouse is None:
            warehouse = Warehouse(warehouse_code=DEMO_WAREHOUSE[0], warehouse_name=DEMO_WAREHOUSE[1], status="ACTIVE")
            db.add(warehouse)
            db.flush()
        location = db.scalar(
            select(WarehouseLocation).where(
                WarehouseLocation.warehouse_id == warehouse.id,
                WarehouseLocation.location_code == DEMO_LOCATION[0],
            )
        )
        if location is None:
            db.add(WarehouseLocation(warehouse_id=warehouse.id, location_code=DEMO_LOCATION[0], location_name=DEMO_LOCATION[1], status="ACTIVE"))
        db.commit()
        unit_count = db.query(Unit).count()
        supplier_count = db.query(Supplier).count()
        print("demo_master_data_ready=true")
        print(f"unit_count={unit_count}")
        print(f"supplier_count={supplier_count}")
        print("demo_product_code=" + DEMO_PRODUCT["product_code"])
        print("demo_warehouse_code=" + DEMO_WAREHOUSE[0])
        print("supplier_codes=" + ",".join(code for code, _ in SUPPLIERS))
    finally:
        db.close()


if __name__ == "__main__":
    main()
