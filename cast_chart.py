import argparse
import json

import swisseph as swe

from ollama_proxy.astrology import THAI_CITIES, cast_chart, format_chart


def main() -> None:
    parser = argparse.ArgumentParser(description="ผูกดวงด้วย Swiss Ephemeris (โหราศาสตร์ไทย)")
    parser.add_argument("--date", required=True, help="วันเกิด YYYY-MM-DD")
    parser.add_argument("--time", required=True, help="เวลาเกิด HH:MM")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--place", default=None, help="ชื่อเมืองไทย (เช่น กรุงเทพ)")
    parser.add_argument("--tz", type=float, default=7.0)
    parser.add_argument("--tropical", action="store_true", help="ใช้ระบบสายนะแทนนิรายนะ")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.place:
        if args.place not in THAI_CITIES:
            raise SystemExit(f"ไม่รู้จักเมือง '{args.place}' ใช้ --lat/--lon แทน")
        lat, lon = THAI_CITIES[args.place]
    else:
        if args.lat is None or args.lon is None:
            raise SystemExit("ต้องระบุ --place หรือ --lat + --lon")
        lat, lon = args.lat, args.lon

    chart = cast_chart(args.date, args.time, lat, lon, args.tz, sidereal=not args.tropical)
    if args.json:
        print(json.dumps(chart, ensure_ascii=False, indent=2))
    else:
        print(format_chart(chart))
    swe.close()


if __name__ == "__main__":
    main()