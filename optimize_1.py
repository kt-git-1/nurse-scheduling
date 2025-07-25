from ortools.sat.python import cp_model
import pandas as pd
import calendar
from datetime import datetime, timedelta

import config

CFG = config.load_config()

TEMP_SHIFT_PATH = config.TEMP_SHIFT_PATH
YEAR = config.YEAR
MONTH = config.MONTH
DAYS_IN_MONTH = config.DAYS_IN_MONTH
SHIFT_TYPES = config.SHIFT_TYPES
HOLIDAY_MAP = config.HOLIDAY_MAP

NURSES = CFG["nurses"]
HOLIDAY_NO_WORKERS = CFG["holiday_no_workers"]
INPUT_CSV = CFG["input_csv"]
dates = CFG["dates"]
weekday_list = CFG["weekday_list"]


def run():
    model = cp_model.CpModel()
    x = {}
    for n in NURSES:
        for d in range(DAYS_IN_MONTH):
            for s in SHIFT_TYPES:
                x[n, d, s] = model.NewBoolVar(f"x_{n}_{d}_{s}")

    holiday_flags = []
    for d in dates:
        if d.weekday() in (3, 6):
            holiday_flags.append("full")
        elif d.weekday() == 5:
            holiday_flags.append("half")
        else:
            holiday_flags.append("none")

    def date_to_index(day: int) -> int:
        return day - 21 if day >= 21 else day + 10

    thursday_indices = [i for i, wd in enumerate(weekday_list) if wd == "Thursday"]
    second_thu = thursday_indices[1] if len(thursday_indices) >= 2 else None
    for d in range(DAYS_IN_MONTH):
        if holiday_flags[d] == "full":
            for n in HOLIDAY_NO_WORKERS:
                if n == "久保" and second_thu is not None and d == second_thu:
                    model.Add(x["久保", d, "/訪"] == 1)
                else:
                    model.Add(x[n, d, "休"] == 1)

    day_cols = [col for col in INPUT_CSV.columns if str(col).isdigit()]
    req_dayoff = {}
    for nurse in NURSES:
        reqs = []
        for col in day_cols:
            val = INPUT_CSV.loc[INPUT_CSV["日付"] == nurse, col]
            typ = str(val.values[0]).strip() if col in INPUT_CSV.columns and not val.empty else ""
            if typ in HOLIDAY_MAP:
                day = int(col)
                reqs.append((day, typ))
        req_dayoff[nurse] = reqs

    for nurse, reqs in req_dayoff.items():
        for day, typ in reqs:
            idx = date_to_index(day)
            if typ in ["①", "②"]:
                shift = "休"
            elif typ == "③":
                shift = "休/"
            elif typ in ["④", "⑤"]:
                shift = "/休"
            else:
                continue
            model.Add(x[nurse, idx, shift] == 1)
            for s in SHIFT_TYPES:
                if s != shift:
                    model.Add(x[nurse, idx, s] == 0)

    YAKIN_WORKERS = ["樋渡", "中山", "川原田", "友枝", "奥平", "前野", "森園", "御書"]
    for d in range(DAYS_IN_MONTH):
        model.Add(sum(x[n, d, "夜"] for n in YAKIN_WORKERS) == 1)

    total_night_days = DAYS_IN_MONTH
    base, rem = divmod(total_night_days, len(YAKIN_WORKERS))
    night_counts = [
        model.NewIntVar(base, base + (1 if i < rem else 0), f"{n}_night_count")
        for i, n in enumerate(YAKIN_WORKERS)
    ]
    for i, n in enumerate(YAKIN_WORKERS):
        model.Add(night_counts[i] == sum(x[n, d, "夜"] for d in range(DAYS_IN_MONTH)))

    for n in YAKIN_WORKERS:
        for d in range(DAYS_IN_MONTH - 1):
            model.Add(x[n, d + 1, "×"] == x[n, d, "夜"])
            for s in SHIFT_TYPES:
                if s != "×":
                    model.Add(x[n, d, "夜"] + x[n, d + 1, s] <= 1)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        result = []
        for n in NURSES:
            row = []
            for d in range(DAYS_IN_MONTH):
                shift = ""
                for s in SHIFT_TYPES:
                    if solver.Value(x[n, d, s]):
                        shift = s
                        break
                row.append(shift)
            result.append([n] + row)
        columns = ["nurse"] + [f"day_{i}" for i in range(DAYS_IN_MONTH)]
        df = pd.DataFrame(result, columns=columns)
        df.to_csv(TEMP_SHIFT_PATH, index=False, encoding="utf-8-sig")
        print(f"✅ シフトCSVを {TEMP_SHIFT_PATH} に保存しました。")
        return df
    else:
        print("❌ 解が見つかりませんでした。")
        return None


if __name__ == "__main__":
    run()
