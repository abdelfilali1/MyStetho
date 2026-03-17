"""Import Moroccan medications from medicaments_maroc.xlsx into the database.
Run once from the medfollow/ directory: python -m database.import_medications
"""
import asyncio
import openpyxl
from pathlib import Path
from config import DATABASE_PATH
import aiosqlite

XLSX_PATH = Path(__file__).parents[2] / "medicaments_maroc.xlsx"


async def run():
    wb = openpyxl.load_workbook(XLSX_PATH)
    ws = wb.active

    rows = []
    seen = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = (row[1] or "").strip()
        form = (row[2] or "").strip()
        lab  = (row[7] or "").strip()
        price_raw = row[4]
        try:
            price = float(str(price_raw).replace(",", ".")) if price_raw else None
        except ValueError:
            price = None
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append((name, form, lab, price))

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Ensure columns exist
        for col_def in [
            "ALTER TABLE medications ADD COLUMN form TEXT",
            "ALTER TABLE medications ADD COLUMN lab TEXT",
            "ALTER TABLE medications ADD COLUMN price REAL",
        ]:
            try:
                await db.execute(col_def)
                await db.commit()
            except Exception:
                pass

        # Remove old general medications (keep dentiste)
        await db.execute("DELETE FROM medications WHERE specialty = 'general' OR specialty IS NULL")
        await db.commit()

        # Insert all xlsx medications as general
        await db.executemany(
            "INSERT INTO medications (name, form, lab, price, specialty) VALUES (?, ?, ?, ?, 'general')",
            rows,
        )
        await db.commit()
        print(f"Imported {len(rows)} medications.")


if __name__ == "__main__":
    asyncio.run(run())
