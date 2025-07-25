from ortools.sat.python import cp_model
import pandas as pd
import calendar
from datetime import datetime, timedelta
import config
CFG = config.load_config()
TEMP_SHIFT_PATH = config.TEMP_SHIFT_PATH
DAYS_IN_MONTH = config.DAYS_IN_MONTH
SHIFT_TYPES = config.SHIFT_TYPES
FULL_OFF_SHIFTS = config.FULL_OFF_SHIFTS
HALF_OFF_SHIFTS = config.HALF_OFF_SHIFTS
TARGET_REST_SCORE = config.TARGET_REST_SCORE
YEAR = config.YEAR
MONTH = config.MONTH
dates = CFG["dates"]
weekday_list = CFG["weekday_list"]
nurse_names = CFG["nurses"]

def run():
    start_date = datetime(YEAR, MONTH - 1, 21)
    dates = [start_date + timedelta(days=i) for i in range(DAYS_IN_MONTH)]
    weekday_list = [calendar.day_name[d.weekday()] for d in dates]
    
    df = pd.read_csv(TEMP_SHIFT_PATH, index_col=0)  # temp_shift_1.csv
    days = [col for col in df.columns if col.startswith('day_')]
    nurse_names = df.index.tolist()
    date_cols = df.columns.tolist()
    
    model = cp_model.CpModel()
    
    # optimize_1.py からのロックされたシフトを保持する
    locked_shifts = {}
    for n in nurse_names:
        for d in date_cols:
            shift = df.at[n, d]
            if shift not in ['', None] and pd.notna(shift):
                locked_shifts[(n, d)] = shift
    
    # Soft制約：休みスコアが13に近づくように
    rest_score_vars = {}
    deviation_vars = {}
    
    # 1. 初期化と休み数の把握
    initial_rest_score = {}
    for n in nurse_names:
        score = 0
        for d in date_cols:
            shift = df.at[n, d]
            if shift in FULL_OFF_SHIFTS or shift == '×':
                score += 1
            elif shift in HALF_OFF_SHIFTS or shift in ['休/', '/休']:
                score += 0.5
        initial_rest_score[n] = score
    
    allowed_additional_rest = {
        n: max(0, TARGET_REST_SCORE - initial_rest_score[n])
        for n in nurse_names
    }
    
    # 休み制御用の優先度付き休みシフトリスト
    rest_shifts_priority = ['休', '休/', '/休']
    
    # シフトタイプリスト
    all_shifts = SHIFT_TYPES
    constrained_shifts = [s for s in all_shifts if s != 'F']
    
    # 変数定義: x[n,d,s] = 1 if nurse n works shift s on day d, else 0
    x = {}
    for n in nurse_names:
        for d_idx, d in enumerate(date_cols):
            if (n, d) in locked_shifts:
                continue
            for s in all_shifts:
                x[(n, d, s)] = model.NewBoolVar(f"x_{n}_{d}_{s}")
    
    # 1日1シフト制約
    for n in nurse_names:
        for d in date_cols:
            if (n, d) in locked_shifts:
                continue
            model.AddAtMostOne(x[(n, d, s)] for s in all_shifts)
    
    # 曜日ごとのシフト必要人数制約およびA/B/C日程の割当ルール設定
    shift_requirements = {}
    for d_idx, d in enumerate(date_cols):
        weekday = weekday_list[d_idx]
        # A日程: 月火水金
        if weekday in ['Monday', 'Tuesday', 'Wednesday', 'Friday']:
            # 8人の日と7人の日があるので、ここでは8人の日を仮定（要調整）
            # 8人の日
            shift_requirements[d] = {
                '1': 1,
                '2': 1,
                '3': 1,
                '4': 1,
                'CT': 1,
                '2・CT': 0,
                '早': 1,
                '残': 1,
                '〇': 1,
                '休': 0,
                '休/': 0,
                '/休': 0,
                '×': 0,
                '夜': 0,
                '1/': 0,
                '2/': 0,
                '3/': 0,
                '4/': 0,
                '早日': 0,
                '残日': 0,
                '/訪': 0,
            }
        elif weekday == 'Thursday' or weekday == 'Sunday':
            # B日程
            shift_requirements[d] = {
                '早日': 1,
                '残日': 1,
                '休': 0,
                '休/': 0,
                '/休': 0,
                '×': 0,
                '夜': 0,
                '1': 0,
                '2': 0,
                '3': 0,
                '4': 0,
                'CT': 0,
                '2・CT': 0,
                '1/': 0,
                '2/': 0,
                '3/': 0,
                '4/': 0,
                '/訪': 0,
                '早': 0,
                '残': 0,
                '〇': 0,
            }
        elif weekday == 'Saturday':
            # C日程
            shift_requirements[d] = {
                '2/': 1,
                '休': 0,
                '休/': 0,
                '/休': 0,
                '×': 0,
                '夜': 0,
                '1': 0,
                '2': 0,
                '3': 0,
                '4': 0,
                '早日': 0,
                '残日': 0,
                '早': 0,
                '残': 0,
                '〇': 0,
                'CT': 0,
                '2・CT': 0,
                '1/': 0,
                '3/': 0,
                '4/': 0,
                '/訪': 0,
            }
        else:
            # その他は0に設定（Fは除外）
            shift_requirements[d] = {s: 0 for s in constrained_shifts}
    
    # 看護師の特性制約
    for n in nurse_names:
        for d in date_cols:
            if (n, d) in locked_shifts:
                continue
            # 板川、三好は夜勤不可
            if n in ['板川', '三好']:
                if '夜' in all_shifts and (n, d, '夜') in x:
                    model.Add(x[(n, d, '夜')] == 0)
            # 御書は夜勤、外来（1〜4）、早日、残日不可
            if n == '御書':
                for s in ['夜', '1', '2', '3', '4', '早日', '残日']:
                    if s in all_shifts and (n, d, s) in x:
                        model.Add(x[(n, d, s)] == 0)
    
    # A/B/C日程ごとの割当ルールを厳密に制御
    # A日程（Mon, Tue, Wed, Fri）8人の日想定
    a_schedule_days = [d for d_idx, d in enumerate(date_cols) if weekday_list[d_idx] in ['Monday', 'Tuesday', 'Wednesday', 'Friday']]
    # A日程の優先割当グループ
    priority_group = ['小嶋', '久保（千）', '田浦']
    outpatient_shifts_a = ['1', '2', '3', '4', 'CT']
    ward_shifts_a = ['早', '残', '〇']
    excluded_for_4 = ['御書', '三好']
    
    # 久保のCT割当補助関数
    def get_ct_assignee(d):
        # まず久保が出勤可能なら久保
        if locked_shifts.get(('久保', d)) in [None, 'CT', '2・CT']:
            return '久保'
        # 次に三好
        if locked_shifts.get(('三好', d)) in [None, 'CT', '2・CT']:
            return '三好'
        # 次に前野
        if locked_shifts.get(('前野', d)) in [None, 'CT', '2・CT']:
            return '前野'
        return None
    
    # A日程の割当制約
    for d in a_schedule_days:
        # CTは久保優先
        ct_assignee = get_ct_assignee(d)
        if ct_assignee:
            # CT割当
            for n in nurse_names:
                if (n, d) in locked_shifts:
                    continue
                if (n, d, 'CT') in x:
                    if n == ct_assignee:
                        model.Add(x[(n, d, 'CT')] == 1)
                    else:
                        model.Add(x[(n, d, 'CT')] == 0)
        else:
            # CT割当なし
            for n in nurse_names:
                if (n, d) in locked_shifts:
                    continue
                if (n, d, 'CT') in x:
                    model.Add(x[(n, d, 'CT')] == 0)
    
        # 優先グループは1〜4に優先的に割当
        # 現状はハード制約を設けず、ソフト制約で調整する
    
        # '4'は御書、三好除外
        for n in ['御書', '三好']:
            if (n, d) in locked_shifts:
                continue
            if (n, d, '4') in x:
                model.Add(x[(n, d, '4')] == 0)
    
        # 御書、三好以外は1〜4の割当は月1回程度に制限（soft constraintの対象）
        # ここではハード制約は設定せず、soft constraintで調整
    
        # 病棟シフトは優先グループ以外で割当
        for s in ward_shifts_a:
            for n in nurse_names:
                if (n, d) in locked_shifts:
                    continue
                if (n, d, s) in x:
                    if n not in priority_group + ['御書', '三好']:
                        pass  # 割当可能
                    else:
                        model.Add(x[(n, d, s)] == 0)
    
        # その他シフトは0に設定（Fや休は許可）
        for s in all_shifts:
            if s not in ['1', '2', '3', '4', 'CT', '早', '残', '〇', 'F', '休', '休/', '/休', '×']:
                for n in nurse_names:
                    if (n, d) in locked_shifts:
                        continue
                    if (n, d, s) in x:
                        model.Add(x[(n, d, s)] == 0)
    
    # B日程（Thu, Sun）
    b_schedule_days = [d for d_idx, d in enumerate(date_cols) if weekday_list[d_idx] in ['Thursday', 'Sunday']]
    for d in b_schedule_days:
        # 早日、残日は優先グループ・御書・三好以外に割当
        for s in ['早日', '残日']:
            for n in nurse_names:
                if (n, d) in locked_shifts:
                    continue
                if (n, d, s) in x:
                    if n not in priority_group + ['御書', '三好']:
                        pass
                    else:
                        model.Add(x[(n, d, s)] == 0)
        # その他シフトは0に設定（Fや休は許可）
        for s in all_shifts:
            if s not in ['早日', '残日', 'F', '休', '休/', '/休', '×']:
                for n in nurse_names:
                    if (n, d) in locked_shifts:
                        continue
                    if (n, d, s) in x:
                        model.Add(x[(n, d, s)] == 0)
    
    # C日程（土曜）
    c_schedule_days = [d for d_idx, d in enumerate(date_cols) if weekday_list[d_idx] == 'Saturday']
    for d in c_schedule_days:
        # 久保が出勤可能なら2/を固定
        kubo_locked = locked_shifts.get(('久保', d))
        if kubo_locked is None or kubo_locked == '2/':
            for n in nurse_names:
                if (n, d) in locked_shifts:
                    continue
                if (n, d, '2/') in x:
                    if n == '久保':
                        model.Add(x[(n, d, '2/')] == 1)
                    else:
                        model.Add(x[(n, d, '2/')] == 0)
        else:
            # 久保が休みの場合、他メンバーで担当
            substitutes = ['小嶋', '久保（千）', '田浦']
            vars_sub = []
            for n in nurse_names:
                if (n, d) in locked_shifts:
                    continue
                if (n, d, '2/') in x:
                    if n in substitutes:
                        vars_sub.append(x[(n, d, '2/')])
                    else:
                        model.Add(x[(n, d, '2/')] == 0)
            if vars_sub:
                model.Add(sum(vars_sub) == 1)
        # その他シフトは0に設定（Fや休は許可）
        for s in all_shifts:
            if s not in ['2/', 'F', '休', '休/', '/休', '×']:
                for n in nurse_names:
                    if (n, d) in locked_shifts:
                        continue
                    if (n, d, s) in x:
                        model.Add(x[(n, d, s)] == 0)
    
    # 各日、各シフトで必要人数を満たす
    for d in date_cols:
        for s in constrained_shifts:
            required = shift_requirements[d].get(s, 0)
            # ロックされたシフトを考慮：この日のこのシフトに既に割り当てられている数をカウント
            locked_count = sum(1 for n in nurse_names if locked_shifts.get((n, d), None) == s)
            effective_required = required - locked_count
            if effective_required < 0:
                effective_required = 0
            vars_for_shift = [x[(n, d, s)] for n in nurse_names if (n, d) not in locked_shifts and (n, d, s) in x]
            model.Add(sum(vars_for_shift) == effective_required)
    
    # 看護師の外来シフト（1-4）割当は月1回程度の制限（soft constraint対象）
    # ここではハード制約は設けず、soft constraintで調整
    
    # 各看護師の休みスコア計算
    # FULL_OFF_SHIFTS=2点、HALF_OFF_SHIFTS=1点で計算
    for n in nurse_names:
        rest_score_var = model.NewIntVar(0, DAYS_IN_MONTH * 2, f"rest_score_{n}")
        rest_score_vars[n] = rest_score_var
        rest_expr = []
        for d in date_cols:
            if (n, d) in locked_shifts:
                s_locked = locked_shifts[(n, d)]
                coef_locked = 0
                if s_locked in FULL_OFF_SHIFTS:
                    coef_locked = 2
                elif s_locked in HALF_OFF_SHIFTS:
                    coef_locked = 1
                rest_expr.append(coef_locked)
            else:
                for s in all_shifts:
                    coef = 0
                    if s in FULL_OFF_SHIFTS:
                        coef = 2
                    elif s in HALF_OFF_SHIFTS:
                        coef = 1
                    if coef > 0 and (n, d, s) in x:
                        rest_expr.append(coef * x[(n, d, s)])
        model.Add(rest_score_var == sum(rest_expr))
    
        deviation_var = model.NewIntVar(0, DAYS_IN_MONTH * 2, f"deviation_{n}")
        deviation_vars[n] = deviation_var
        model.AddAbsEquality(deviation_var, rest_score_var - TARGET_REST_SCORE * 2)
    
    # ソフト制約：外来シフト '1'〜'4' の偏りに対するペナルティ
    outpatient_shifts = ['1', '2', '3', '4']
    outpatient_counts = {s: [] for s in outpatient_shifts}
    for s in outpatient_shifts:
        for n in nurse_names:
            count_var = model.NewIntVar(0, DAYS_IN_MONTH, f"count_{n}_{s}")
            sum_expr = []
            for d in date_cols:
                if (n, d) in locked_shifts:
                    if locked_shifts[(n, d)] == s:
                        sum_expr.append(1)
                    else:
                        sum_expr.append(0)
                else:
                    if (n, d, s) in x:
                        sum_expr.append(x[(n, d, s)])
            model.Add(count_var == sum(sum_expr))
            outpatient_counts[s].append(count_var)
    
    # 外来シフトの平均回数計算
    outpatient_avg = {}
    for s in outpatient_shifts:
        outpatient_avg[s] = model.NewIntVar(0, DAYS_IN_MONTH, f"avg_{s}")
        model.Add(outpatient_avg[s] * len(nurse_names) == sum(outpatient_counts[s]))
    
    # 外来シフト回数の平均からの偏差ペナルティ
    outpatient_imbalance_penalties = []
    for s in outpatient_shifts:
        for count_var in outpatient_counts[s]:
            diff = model.NewIntVar(0, DAYS_IN_MONTH, f"diff_outpatient_{s}_{count_var.Name()}")
            model.AddAbsEquality(diff, count_var - outpatient_avg[s])
            outpatient_imbalance_penalties.append(diff)
    
    # ソフト制約：病棟シフト '早', '残', '〇' の偏りに対するペナルティ
    ward_shifts = ['早', '残', '〇']
    ward_counts = {s: [] for s in ward_shifts}
    for s in ward_shifts:
        for n in nurse_names:
            count_var = model.NewIntVar(0, DAYS_IN_MONTH, f"count_{n}_{s}")
            sum_expr = []
            for d in date_cols:
                if (n, d) in locked_shifts:
                    if locked_shifts[(n, d)] == s:
                        sum_expr.append(1)
                    else:
                        sum_expr.append(0)
                else:
                    if (n, d, s) in x:
                        sum_expr.append(x[(n, d, s)])
            model.Add(count_var == sum(sum_expr))
            ward_counts[s].append(count_var)
    
    # 病棟シフトの平均回数計算
    ward_avg = {}
    for s in ward_shifts:
        ward_avg[s] = model.NewIntVar(0, DAYS_IN_MONTH, f"avg_{s}")
        model.Add(ward_avg[s] * len(nurse_names) == sum(ward_counts[s]))
    
    # 病棟シフト回数の平均からの偏差ペナルティ
    ward_imbalance_penalties = []
    for s in ward_shifts:
        for count_var in ward_counts[s]:
            diff = model.NewIntVar(0, DAYS_IN_MONTH, f"diff_ward_{s}_{count_var.Name()}")
            model.AddAbsEquality(diff, count_var - ward_avg[s])
            ward_imbalance_penalties.append(diff)
    
    # 休みスコア二乗誤差の最小化
    square_deviation_vars = []
    for n in nurse_names:
        square_dev = model.NewIntVar(0, 10000, f"square_deviation_{n}")
        model.AddMultiplicationEquality(square_dev, [deviation_vars[n], deviation_vars[n]])
        square_deviation_vars.append(square_dev)
    
    # 目的関数の重み設定
    w1 = 20  # 休みスコア偏差
    w2 = 1  # 外来シフト偏り
    w3 = 1  # 病棟シフト偏り
    
    model.Minimize(
        w1 * sum(square_deviation_vars) +
        w2 * sum(outpatient_imbalance_penalties) +
        w3 * sum(ward_imbalance_penalties)
    )
    
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        # 割り当て結果をdfに反映（空白またはNaNの場合のみ上書き）
        for n in nurse_names:
            for d in date_cols:
                if (n, d) in locked_shifts:
                    continue
                if df.at[n, d] == '' or pd.isna(df.at[n, d]):
                    for s in all_shifts:
                        if (n, d, s) in x and solver.BooleanValue(x[(n, d, s)]):
                            df.at[n, d] = s
                            break
    
        # 空白やNaNのシフトは「休」に置換
        for d in date_cols:
            for n in nurse_names:
                if df.at[n, d] == '' or pd.isna(df.at[n, d]):
                    df.at[n, d] = '休'
    
        # 1〜4を整数変換（Excel用）
        for d in date_cols:
            df[d] = df[d].apply(lambda x: int(x) if x in ['1', '2', '3', '4'] else x)
    
        df.to_csv("temp_shift_final.csv", encoding="utf-8-sig")
        print("✅ シフト割り振りを実施し、temp_shift_final.csv に保存しました。")
    
        # 休み合計列を追加して保存
        df_with_rest_col = df.copy()
        rest_col = []
        for n in nurse_names:
            total_rest = 0
            for d in date_cols:
                shift = df.at[n, d]
                if shift in FULL_OFF_SHIFTS or shift == '×':
                    total_rest += 1
                elif shift in HALF_OFF_SHIFTS or shift in ['休/', '/休']:
                    total_rest += 0.5
            rest_col.append(total_rest)
        df_with_rest_col['休み合計'] = rest_col
        df_with_rest_col.to_csv("shift_final_summary.csv", encoding="utf-8-sig")
        print("✅ 休み合計列付きのシフトCSVを shift_final_summary.csv に保存しました。")
    else:
        print("⚠️ 最適解が見つかりませんでした。")

if __name__ == "__main__":
    run()
