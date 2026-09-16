"""Generate the runtime Baidu region catalog from the official API code files.

The generated JSON is committed with the application so runtime code never
needs to read documentation from another project directory.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_catalog(source_dir: Path) -> dict:
    flat_source = (source_dir / "14.3.1 二级地域代码").read_text(encoding="utf-8-sig")
    province_city_ids = {int(value) for value in re.findall(r":\s*(\d+)", flat_source)}
    province_city = load_json(source_dir / "14.3.2 三级地域代码")
    roots: list[dict] = []
    all_ids: set[int] = set()

    for province_name, province_value in province_city.items():
        if not isinstance(province_value, dict):
            continue
        if province_name in {"日本", "其他国家"}:
            continue
        province_id = int(province_value["id"])
        all_ids.add(province_id)
        children: list[dict] = []
        for city_name, city_value in province_value.get("市", {}).items():
            city_id = int(city_value["id"])
            if city_id not in province_city_ids:
                continue
            all_ids.add(city_id)
            children.append({"id": city_id, "name": city_name, "level": "city"})

        roots.append(
            {
                "id": province_id,
                "name": province_name,
                "level": "province",
                "children": children,
            }
        )

    return {
        "version": "baidu-province-city-codes-14.3-v1",
        "country": {"id": 9999999, "name": "中国"},
        "source": {
            "province_city_flat": "14.3.1 二级地域代码",
            "province_city": "14.3.2 三级地域代码",
        },
        "selectable_count": len(all_ids) + 1,
        "regions": roots,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    catalog = build_catalog(args.source_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"generated {args.output} with {catalog['selectable_count']} selectable regions"
    )


if __name__ == "__main__":
    main()
