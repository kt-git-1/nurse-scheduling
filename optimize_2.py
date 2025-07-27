from ortools.sat.python import cp_model
import pandas as pd
import random
import calendar
from datetime import datetime, timedelta
from config import (
    TEMP_SHIFT_PATH, YEAR, MONTH, DAYS_IN_MONTH, SHIFT_TYPES, NURSES, FULL_OFF_SHIFTS, HALF_OFF_SHIFTS, TARGET_REST_SCORE
)

start_date = datetime(YEAR, MONTH - 1, 21)
dates = [start_date + timedelta(days=i) for i in range(DAYS_IN_MONTH)]
weekday_list = [calendar.day_name[d.weekday()] for d in dates]

df = pd.read_csv(TEMP_SHIFT_PATH, index_col=0)  # temp_shift_1.csv
days = [col for col in df.columns if col.startswith('day_')]
nurse_names = df.index.tolist()
date_cols = df.columns.tolist()

model = cp_model.CpModel()

# Soft制約：休みスコアが13に近づくように
rest_score_vars = {}
deviation_vars = {}
for n in nurse_names:
    rest_score_vars[n] = model.NewIntVar(0, 26, f"rest_score_{n}")
    deviation_vars[n] = model.NewIntVar(0, 26, f"deviation_{n}")

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

# 土曜担当メンバー
土曜担当 = ['小嶋', '久保（千）', '田浦']

# 休み割当用の関数
def assign_rest_shifts(nurses, col):
    for n in nurses:
        if allowed_additional_rest[n] >= 1:
            df.at[n, col] = '休'
            allowed_additional_rest[n] -= 1
        elif allowed_additional_rest[n] >= 0.5:
            df.at[n, col] = '休/'
            allowed_additional_rest[n] -= 0.5
        else:
            # 休み割当不可なら空白のままにする（後で他の処理で割当）
            pass

# シフトカウント初期化（平日用）
shift_names_weekday = ['1', '2', '3', '4', '早', '残', '〇', 'CT', '2・CT']
shift_counts_weekday = {n: {s: 0 for s in shift_names_weekday} for n in nurse_names}

# シフトカウント初期化（土曜用）
shift_names_saturday = ['1/', '2/', '3/', '4/', '早', '残', '〇']
shift_counts_saturday = {n: {s: 0 for s in shift_names_saturday} for n in nurse_names}


# シフト割り振り
for d, col in enumerate(date_cols):
    weekday = weekday_list[d]
    busy_shifts = ['休', '休/', '/休', '夜', '×']

    # 2. 平日（月・火・水・金）の処理
    if weekday in ['Monday', 'Tuesday', 'Wednesday', 'Friday']:
        assigned_nurses = set()
        available_nurses = [n for n in nurse_names if df.at[n, col] not in busy_shifts]

        n_to_assign = 8 if len(available_nurses) >= 8 else 7

        # CT, 2・CT 割り当て
        if n_to_assign == 8:
            if '久保' in available_nurses:
                df.at['久保', col] = 'CT'
                shift_counts_weekday['久保']['CT'] += 1
                assigned_nurses.add('久保')
            else:
                candidates = [n for n in ['三好', '前野'] if n in available_nurses]
                if candidates:
                    min_count = min(shift_counts_weekday[n]['CT'] for n in candidates)
                    assign = min([n for n in candidates if shift_counts_weekday[n]['CT'] == min_count])
                    df.at[assign, col] = 'CT'
                    shift_counts_weekday[assign]['CT'] += 1
                    assigned_nurses.add(assign)
        else: # 7人しか割り振れない時
            if '久保' in available_nurses:
                df.at['久保', col] = '2・CT'
                shift_counts_weekday['久保']['2・CT'] += 1
                assigned_nurses.add('久保')
            else:
                candidates = [n for n in ['三好', '前野'] if n in available_nurses]
                if candidates:
                    min_count = min(shift_counts_weekday[n]['2・CT'] for n in candidates)
                    assign = min([n for n in candidates if shift_counts_weekday[n]['2・CT'] == min_count])
                    df.at[assign, col] = '2・CT'
                    shift_counts_weekday[assign]['2・CT'] += 1
                    assigned_nurses.add(assign)

        # 8人以上割り当てれる時
        # 「小嶋」「久保（千）」「田浦」が「1」「2」「3」「4」を均等に割り当てる
        if n_to_assign == 8:
            gai_shift = random.sample(['1', '2', '3', '4'], k=4)
            gai_members = [n for n in 土曜担当 if n in available_nurses]
            assigned_gai = set()
            for s in gai_shift:
                # 各シフトごとの担当数が最小の人を選ぶ
                if gai_members:
                    count_dict = {n: shift_counts_weekday[n][s] for n in gai_members if n not in assigned_gai}
                    if count_dict:
                        min_count = min(count_dict.values())
                        candidates = [n for n, c in count_dict.items() if c == min_count]
                        assign = sorted(candidates)[0]  # 複数候補がいる場合は名前順で決定
                        df.at[assign, col] = s
                        shift_counts_weekday[assign][s] += 1
                        assigned_nurses.add(assign)
                        assigned_gai.add(assign)

            # 残り外来を他から均等割り
            remain = 4 - len(gai_members)
            if remain > 0:
                other_candidates = [n for n in available_nurses if n not in assigned_nurses and n != '御書'] # 御書は外来に入らない
                for s in gai_shift[len(gai_members):]:
                    if other_candidates:
                        min_count = min(shift_counts_weekday[n][s] for n in other_candidates)
                        assign = min([n for n in other_candidates if shift_counts_weekday[n][s] == min_count])
                        df.at[assign, col] = s
                        shift_counts_weekday[assign][s] += 1
                        assigned_nurses.add(assign)
                        other_candidates.remove(assign)

        else: # 7人しか割り振れない時
            gai_shift = random.sample(['1', '3', '4'], k=3)
            gai_members = [n for n in 土曜担当 if n in available_nurses]
            assigned_gai = set()
            for s in gai_shift:
                # 各シフトごとの担当数が最小の人を選ぶ
                if gai_members:
                    count_dict = {n: shift_counts_weekday[n][s] for n in gai_members if n not in assigned_gai}
                    if count_dict:
                        min_count = min(count_dict.values())
                        candidates = [n for n, c in count_dict.items() if c == min_count]
                        assign = sorted(candidates)[0]  # 複数候補がいる場合は名前順で決定
                        df.at[assign, col] = s
                        shift_counts_weekday[assign][s] += 1
                        assigned_nurses.add(assign)
                        assigned_gai.add(assign)

            # 残り外来を他から均等割り
            remain = 3 - len(gai_members)
            if remain > 0:
                other_candidates = [n for n in available_nurses if n not in assigned_nurses and n != '御書'] # 御書は外来に入らない
                for s in gai_shift[len(gai_members):]:
                    if other_candidates:
                        min_count = min(shift_counts_weekday[n][s] for n in other_candidates)
                        assign = min([n for n in other_candidates if shift_counts_weekday[n][s] == min_count])
                        df.at[assign, col] = s
                        shift_counts_weekday[assign][s] += 1
                        assigned_nurses.add(assign)
                        other_candidates.remove(assign)


        # 病棟シフト（早・残・〇）
        byoto_shifts = ['早', '残', '〇']
        remain_candidates = [n for n in available_nurses if n not in assigned_nurses]
        for s in byoto_shifts:
            if remain_candidates:
                min_count = min(shift_counts_weekday[n][s] for n in remain_candidates)
                assign = min([n for n in remain_candidates if shift_counts_weekday[n][s] == min_count])
                df.at[assign, col] = s
                shift_counts_weekday[assign][s] += 1
                assigned_nurses.add(assign)
                remain_candidates.remove(assign)

        # 休み割り振り（残った人）
        remain_nurses = [n for n in nurse_names if (df.at[n, col] == '' or pd.isna(df.at[n, col])) and n in available_nurses]
        assign_rest_shifts(remain_nurses, col)

    # 3. 木曜・日曜（B日程）の処理
    elif weekday in ['Thursday', 'Sunday']:
        forbidden_shifts = ['休', '休/', '/休', '×', '夜', '/訪']
        candidates = [n for n in nurse_names if df.at[n, col] not in forbidden_shifts]

        # 除外する4名（例として「久保」「三好」「前野」「田浦」など、要調整）
        excluded_for_early_late = ['久保', '三好', '前野', '田浦']
        candidates_for_early_late = [n for n in candidates if n not in excluded_for_early_late]

        # 「早日」「残日」を1人ずつ均等割当
        early_counts = {n: (df.loc[n] == '早日').sum() for n in candidates_for_early_late}
        late_counts = {n: (df.loc[n] == '残日').sum() for n in candidates_for_early_late}
        candidates_early = sorted(candidates_for_early_late, key=lambda n: early_counts[n])
        candidates_late = sorted(candidates_for_early_late, key=lambda n: late_counts[n] if n != candidates_early[0] else float('inf'))

        if candidates_early:
            df.at[candidates_early[0], col] = '早日'
        if len(candidates_late) > 1:
            df.at[candidates_late[0], col] = '残日'

        # 残りの人は休み割当。ただし allowed_additional_rest に基づき「休」「休/」
        rest_candidates = [n for n in candidates if df.at[n, col] not in ['早日', '残日']]
        for n in rest_candidates:
            if allowed_additional_rest[n] >= 1:
                df.at[n, col] = '休'
                allowed_additional_rest[n] -= 1
            elif allowed_additional_rest[n] >= 0.5:
                df.at[n, col] = '休/'
                allowed_additional_rest[n] -= 0.5
            else:
                # 休み割り当て不可なら空白のまま
                df.at[n, col] = ''

        # 他の看護師で空白の人には休み割当優先度付きで割当
        remain_nurses = [n for n in nurse_names if (df.at[n, col] == '' or pd.isna(df.at[n, col])) and df.at[n, col] not in busy_shifts]
        assign_rest_shifts(remain_nurses, col)

    # 4. 土曜（C日程）の処理
    elif weekday == 'Saturday':
        assigned_nurses = set()
        busy_shifts = ['休', '休/', '/休', '×', '夜']

        # 「久保」が「2/」優先
        if '久保' in nurse_names and df.at['久保', col] not in busy_shifts:
            df.at['久保', col] = '2/'
            shift_counts_saturday['久保']['2/'] += 1
            assigned_nurses.add('久保')
        else:
            candidates_2 = [n for n in nurse_names if n not in assigned_nurses and n not in 土曜担当 and df.at[n, col] not in busy_shifts]
            if candidates_2:
                min_count = min(shift_counts_saturday[n]['2/'] for n in candidates_2)
                assign_2 = min([n for n in candidates_2 if shift_counts_saturday[n]['2/'] == min_count])
                df.at[assign_2, col] = '2/'
                shift_counts_saturday[assign_2]['2/'] += 1
                assigned_nurses.add(assign_2)

        # 外来1/,3/,4/は土曜担当から優先
        for s, nurse in zip(['1/', '3/', '4/'], 土曜担当):
            if nurse in nurse_names and df.at[nurse, col] not in busy_shifts:
                df.at[nurse, col] = s
                shift_counts_saturday[nurse][s] += 1
                assigned_nurses.add(nurse)
            else:
                candidates = [n for n in nurse_names if n not in assigned_nurses and n not in 土曜担当 and df.at[n, col] not in busy_shifts]
                if candidates:
                    min_count = min(shift_counts_saturday[n][s] for n in candidates)
                    assign = min([n for n in candidates if shift_counts_saturday[n][s] == min_count])
                    df.at[assign, col] = s
                    shift_counts_saturday[assign][s] += 1
                    assigned_nurses.add(assign)

        # 病棟シフト（早、残、〇）
        病棟シフト = ['早', '残', '〇']
        candidates = [n for n in nurse_names if n not in assigned_nurses and df.at[n, col] not in busy_shifts]
        for s in 病棟シフト:
            if candidates:
                count_dict = {n: (df.loc[n] == s).sum() for n in candidates}
                min_count = min(count_dict[n] for n in candidates)
                assign = min([n for n in candidates if count_dict[n] == min_count])
                df.at[assign, col] = s
                assigned_nurses.add(assign)
                candidates.remove(assign)

        # 休み割り振り（allowed_additional_restに基づく）
        remain_nurses = [n for n in nurse_names if (df.at[n, col] == '' or pd.isna(df.at[n, col])) and df.at[n, col] not in busy_shifts]
        assign_rest_shifts(remain_nurses, col)

    # その他の日は特に処理なし
    else:
        # 休み割当が必要な場合は割当
        remain_nurses = [n for n in nurse_names if (df.at[n, col] == '' or pd.isna(df.at[n, col])) and df.at[n, col] not in busy_shifts]
        assign_rest_shifts(remain_nurses, col)

# 最終的に空白やNaNのシフトは「休」に置換（休み割当不可の人も含む）
for d, col in enumerate(date_cols):
    for n in nurse_names:
        if df.at[n, col] == '' or pd.isna(df.at[n, col]):
            df.at[n, col] = '休'

for n in nurse_names:
    total = 0
    for d in date_cols:
        shift = df.at[n, d]
        if shift in FULL_OFF_SHIFTS:
            total += 2
        elif shift in HALF_OFF_SHIFTS:
            total += 1
    model.Add(rest_score_vars[n] == total)
    model.AddAbsEquality(deviation_vars[n], rest_score_vars[n] - TARGET_REST_SCORE * 2)
# 休みスコア二乗誤差の最小化: sum((rest_score - 13*2)^2)
square_deviation_vars = []
for n in nurse_names:
    square_dev = model.NewIntVar(0, 10000, f"square_deviation_{n}")
    model.AddMultiplicationEquality(square_dev, [deviation_vars[n], deviation_vars[n]])
    square_deviation_vars.append(square_dev)
model.Minimize(sum(square_deviation_vars))

 # 出力前に 1〜4 を整数に変換（Excelで数値認識させるため）
for d in date_cols:
    df[d] = df[d].apply(lambda x: int(x) if x in ['1', '2', '3', '4'] else x)

df.to_csv("output/shift_final.csv", encoding="utf-8-sig")
print("✅ シフト割り振りを実施し、shift_final.csv に保存しました。")

# 各看護師の休み合計数を列として追加して保存
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
df_with_rest_col.to_csv("output/shift_summary.csv", encoding="utf-8-sig")
print("✅ 休み合計列付きのシフトCSVを shift_summary.csv に保存しました。")