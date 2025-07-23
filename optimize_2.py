from ortools.sat.python import cp_model
import pandas as pd
import calendar
from datetime import datetime, timedelta
from config import (
    REQ_SHIFT_PATH, TEMPLATE_PATH, TEMP_SHIFT_1_PATH, YEAR, MONTH, DAYS_IN_MONTH, SHIFT_TYPES, HOLIDAY_MAP, INPUT_CSV, NURSES, HOLIDAY_NO_WORKERS, HOLIDAY_WORKERS, 
)

start_date = datetime(YEAR, MONTH - 1, 21)
dates = [start_date + timedelta(days=i) for i in range(DAYS_IN_MONTH)]
weekday_list = [calendar.day_name[d.weekday()] for d in dates]
df = pd.read_csv(TEMP_SHIFT_1_PATH,  index_col=0)
days = [col for col in df.columns if col.startswith('day_')]
nurse_names = df.index.tolist()
date_cols = df.columns.tolist()


# ==========モデル定義==========
model = cp_model.CpModel()
x = {}
for n in NURSES:
    for d in range(DAYS_IN_MONTH):
        for s in SHIFT_TYPES:
            x[n, d, s] = model.NewBoolVar(f'x_{n}_{d}_{s}')

# 休日フラグを作成（木曜・日曜はfull、土曜はhalf）
holiday_flags = []
for d in dates:
    if d.weekday() == 3 or d.weekday() == 6:
        holiday_flags.append('full')
    elif d.weekday() == 5:
        holiday_flags.append('half')
    else:
        holiday_flags.append('none')

# 既存シフトを固定
# for i, n in enumerate(NURSES):
#     for d, day_col in enumerate(days):
#         shift = df.loc[i, day_col]
#         if shift in SHIFT_TYPES:
#             model.Add(x[n, d, shift] == 1)
#             for s in SHIFT_TYPES:
#                 if s != shift:
#                     model.Add(x[n, d, s] == 0)

# 木・日曜において「早日」「残日」を割り振る
for d, col in enumerate(date_cols):
    if weekday_list[d] in ['Thursday', 'Sunday']:
        forbidden_shifts = ['休', '休/', '/休', '×', '夜', '/訪']
        candidates = []
        for nurse in nurse_names:
            if df.at[nurse, col] not in forbidden_shifts:
                candidates.append(nurse)
        # 「早日」「残日」を割り当てる人を決定（毎回順番 or ランダム or 均等に分散でもOK）
        early_counts = {n: (df.iloc[i] == '早日').sum() for i, n in enumerate(nurse_names)}
        late_counts = {n: (df.iloc[i] == '残日').sum() for i, n in enumerate(nurse_names)}
        # ソートして割り当て先決定
        candidates_early = sorted(candidates, key=lambda n: early_counts[n])
        candidates_late = sorted(candidates, key=lambda n: late_counts[n] if n != candidates_early[0] else float('inf'))
        if candidates_early:
            df.at[candidates_early[0], col] = '早日'
        if len(candidates_late) > 1:
            df.at[candidates_late[0], col] = '残日'
        # 残りの候補者には「休」を割り当て
        for n in candidates:
            if df.at[n, col] not in ['早日', '残日']:
                df.at[n, col] = '休'


# 土曜の外来割り振り
土曜担当 = ['小嶋', '久保（千）', '田浦']

start_date = datetime(YEAR, MONTH - 1, 21)
dates = [start_date + timedelta(days=i) for i in range(DAYS_IN_MONTH)]
weekday_list = [calendar.day_name[d.weekday()] for d in dates]

# それぞれのシフト割り振りカウンタを用意
shift_names = ['1/', '2/', '3/', '4/', '早', '残', '〇/']
shift_counts = {n: {s: 0 for s in shift_names} for n in nurse_names}
休みカウント = {n: 0 for n in nurse_names}

for d, col in enumerate(date_cols):
    if weekday_list[d] == 'Saturday':
        assigned_nurses = set()

        # 2/割り当て
        if '久保' in nurse_names and df.at['久保', col] not in ['休', '休/', '/休', '×', '夜']:
            df.at['久保', col] = '2/'
            shift_counts['久保']['2/'] += 1
            assigned_nurses.add('久保')
        else:
            candidates_2 = [n for n in nurse_names if n not in assigned_nurses and n not in 土曜担当 and df.at[n, col] not in ['休', '休/', '/休', '×', '夜']]
            if candidates_2:
                # 割り当て回数が一番少ない人を選ぶ（複数の場合は名前順で先の人）
                min_count = min(shift_counts[n]['2/'] for n in candidates_2)
                assign_2 = min([n for n in candidates_2 if shift_counts[n]['2/'] == min_count])
                df.at[assign_2, col] = '2/'
                shift_counts[assign_2]['2/'] += 1
                assigned_nurses.add(assign_2)

        # 外来1/,3/,4/は土曜担当から均等に（休み等以外）
        for s, nurse in zip(['1/', '3/', '4/'], 土曜担当):
            if nurse in nurse_names and df.at[nurse, col] not in ['休', '休/', '/休', '×', '夜']:
                df.at[nurse, col] = s
                shift_counts[nurse][s] += 1
                assigned_nurses.add(nurse)
            else:
                candidates = [n for n in nurse_names if n not in assigned_nurses and n not in 土曜担当 and df.at[n, col] not in ['休', '休/', '/休', '×', '夜']]
                if candidates:
                    min_count = min(shift_counts[n][s] for n in candidates)
                    assign = min([n for n in candidates if shift_counts[n][s] == min_count])
                    df.at[assign, col] = s
                    shift_counts[assign][s] += 1
                    assigned_nurses.add(assign)

        # 病棟シフト
        病棟シフト = ['早', '残', '〇/']
        candidates = [n for n in nurse_names if n not in assigned_nurses and df.at[n, col] not in ['休', '休/', '/休', '×', '夜']]
        for s in 病棟シフト:
            if candidates:
                count_dict = {n: (df.loc[n] == s).sum() for n in candidates}
                min_count = min(count_dict[n] for n in candidates)
                assign = min([n for n in candidates if count_dict[n] == min_count])
                df.at[assign, col] = s
                assigned_nurses.add(assign)
                candidates.remove(assign)

        # 残り未割り当ての人は「休」
        for n in nurse_names:
            if df.at[n, col] == '' or pd.isna(df.at[n, col]):
                df.at[n, col] = '休'

shift_names = ['1', '2', '3', '4', '早', '残', '〇', 'CT', '2・CT']
shift_counts = {n: {s: 0 for s in shift_names} for n in nurse_names}


# 平日割り振り
for d, col in enumerate(date_cols):
    if weekday_list[d] in ['Monday', 'Tuesday', 'Wednesday', 'Friday']:
        # 休/夜/休/休/夜 以外の人を候補
        assigned_nurses = set()
        busy_shifts = ['休', '休/', '/休', '夜']
        available_nurses = [n for n in nurse_names if df.at[n, col] not in busy_shifts]

        # 8人 or 7人どちらで入れるか判定
        n_to_assign = 8
        if len(available_nurses) < 8:
            n_to_assign = 7

        # --- CT・2・CTの割り振り ---
        if n_to_assign == 8:
            if '久保' in available_nurses:
                df.at['久保', col] = 'CT'
                shift_counts['久保']['CT'] += 1
                assigned_nurses.add('久保')
            else:
                # 久保休み→三好 or 前野（均等割り）
                candidates = [n for n in ['三好', '前野'] if n in available_nurses]
                if candidates:
                    min_count = min(shift_counts[n]['CT'] for n in candidates)
                    assign = min([n for n in candidates if shift_counts[n]['CT'] == min_count])
                    df.at[assign, col] = 'CT'
                    shift_counts[assign]['CT'] += 1
                    assigned_nurses.add(assign)
        else:
            # 7人時：久保がいれば「2・CT」
            if '久保' in available_nurses:
                df.at['久保', col] = '2・CT'
                shift_counts['久保']['2・CT'] += 1
                assigned_nurses.add('久保')
            else:
                # 久保休み→三好 or 前野（均等割り）
                candidates = [n for n in ['三好', '前野'] if n in available_nurses]
                if candidates:
                    min_count = min(shift_counts[n]['2・CT'] for n in candidates)
                    assign = min([n for n in candidates if shift_counts[n]['2・CT'] == min_count])
                    df.at[assign, col] = '2・CT'
                    shift_counts[assign]['2・CT'] += 1
                    assigned_nurses.add(assign)

        # --- 外来1,3,4割り振り ---
        gai_shift = ['1', '3', '4']
        gai_assign = []
        gai_candidates = [n for n in 土曜担当 if n in available_nurses and n not in assigned_nurses]
        # 土曜担当優先、候補が足りなければ他から
        for s, nurse in zip(gai_shift, gai_candidates):
            df.at[nurse, col] = s
            shift_counts[nurse][s] += 1
            assigned_nurses.add(nurse)
            gai_assign.append(nurse)
        # 残り外来枠（例えば1枠だけ空き）にはその他の人を均等割
        remain = 3 - len(gai_candidates)
        if remain > 0:
            other_candidates = [n for n in available_nurses if n not in assigned_nurses]
            for s in gai_shift[len(gai_candidates):]:
                if other_candidates:
                    min_count = min(shift_counts[n][s] for n in other_candidates)
                    assign = min([n for n in other_candidates if shift_counts[n][s] == min_count])
                    df.at[assign, col] = s
                    shift_counts[assign][s] += 1
                    assigned_nurses.add(assign)
                    other_candidates.remove(assign)

        # --- 外来2割り振り ---
        if n_to_assign == 8:
            # 久保CTのときの外来2
            remain_candidates = [n for n in available_nurses if n not in assigned_nurses]
            if remain_candidates:
                min_count = min(shift_counts[n]['2'] for n in remain_candidates)
                assign = min([n for n in remain_candidates if shift_counts[n]['2'] == min_count])
                df.at[assign, col] = '2'
                shift_counts[assign]['2'] += 1
                assigned_nurses.add(assign)
        # 7人の場合はすでに2・CTで割り振っている

        # --- 病棟シフト（早・残・〇） ---
        byoto_shifts = ['早', '残', '〇']
        remain_candidates = [n for n in available_nurses if n not in assigned_nurses]
        for s in byoto_shifts:
            if remain_candidates:
                min_count = min(shift_counts[n][s] for n in remain_candidates)
                assign = min([n for n in remain_candidates if shift_counts[n][s] == min_count])
                df.at[assign, col] = s
                shift_counts[assign][s] += 1
                assigned_nurses.add(assign)
                remain_candidates.remove(assign)

        # --- 休み割り振り ---
        # 割り当てられていない人は「休」
        for n in nurse_names:
            if (df.at[n, col] == '' or pd.isna(df.at[n, col])) and n in available_nurses:
                # 休み総数の上限を見ながら13を維持するための制御（後述で微調整可）
                if 休みカウント[n] < 13:
                    df.at[n, col] = '休'
                    休みカウント[n] += 1


df.to_csv("temp_shift_final.csv", encoding="utf-8-sig")
print("✅ 土曜外来の均等割り振りを実施し、temp_shift_final.csv に保存しました。")