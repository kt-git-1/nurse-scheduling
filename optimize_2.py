from ortools.sat.python import cp_model
import pandas as pd
import random
import calendar
from datetime import datetime, timedelta
from config import (
    TEMP_SHIFT_PATH, YEAR, MONTH, DAYS_IN_MONTH, SHIFT_TYPES, NURSES, FULL_OFF_SHIFTS, HALF_OFF_SHIFTS, TARGET_REST_SCORE, is_japanese_holiday
)

# 夜勤を行うメンバー（夜勤明けは必ず×とする）
YAKIN_WORKERS = ['樋渡', '中山', '川原田', '友枝', '奥平', '前野', '森園']

start_date = datetime(YEAR, MONTH - 1, 21)
dates = [start_date + timedelta(days=i) for i in range(DAYS_IN_MONTH)]
weekday_list = [calendar.day_name[d.weekday()] for d in dates]

# Load temp_shift produced by optimize_1.
# We must keep the shift assignments written by optimize_1 intact.
orig_df = pd.read_csv(TEMP_SHIFT_PATH, index_col=0)
fixed_mask = orig_df.notna()  # True where the shift was pre-assigned
df = orig_df.copy()
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
        if shift in FULL_OFF_SHIFTS:
            score += 1
        elif shift in HALF_OFF_SHIFTS:
            score += 0.5
    initial_rest_score[n] = score


# 看護師ごとの現在の休みスコア（2点満点制）を初期化
current_rest_score = {}
for n in nurse_names:
    score = 0
    for d in date_cols:
        shift = df.at[n, d]
        if shift in FULL_OFF_SHIFTS:
            score += 2
        elif shift in HALF_OFF_SHIFTS:
            score += 1
    current_rest_score[n] = score

# 休み制御用の優先度付き休みシフトリスト
rest_shifts_priority = ['休', '休/', '/休']

# 土曜担当メンバー
土曜担当 = ['小嶋', '久保（千）', '田浦']

# 休み割当用の関数
def assign_rest_shifts(nurses, col):
    """Assign rest shifts prioritizing nurses still lacking days off."""
    # 各看護師が目標休み数にどれだけ足りていないかを計算
    need = {
        n: TARGET_REST_SCORE * 2 - current_rest_score.get(n, 0)
        for n in nurses
    }
    # 休みが不足している順に並べる
    sorted_nurses = sorted(nurses, key=lambda n: need[n], reverse=True)
    for n in sorted_nurses:
        if fixed_mask.at[n, col]:
            continue  # don't overwrite pre-assigned shifts
        remaining = need[n]
        if remaining <= 0:
            continue
        if remaining >= 2:
            df.at[n, col] = '休'
            current_rest_score[n] += 2
        elif remaining >= 1:
            df.at[n, col] = '休/'
            current_rest_score[n] += 1


def balance_rest_days():
    """Simple post-process to even out total rest days."""
    totals = {}
    for n in nurse_names:
        total = 0
        for d in date_cols:
            shift = df.at[n, d]
            if shift in FULL_OFF_SHIFTS:
                total += 1
            elif shift in HALF_OFF_SHIFTS:
                total += 0.5
        totals[n] = total

    # 偏りが多少残ってもよいので差が2以上の場合のみ調整
    while max(totals.values()) - min(totals.values()) > 2:
        high = max(totals, key=totals.get)
        low = min(totals, key=totals.get)
        moved = False
        for idx, col in enumerate(date_cols):
            high_shift = df.at[high, col]
            low_shift = df.at[low, col]
            if fixed_mask.at[high, col] or fixed_mask.at[low, col]:
                continue  # keep original assignments intact
            # 夜勤の翌日の×は動かさない
            if (
                high_shift == '×'
                and idx > 0
                and df.at[high, date_cols[idx - 1]] == '夜'
            ):
                continue
            # 夜勤シフトの移動は行わない
            if low_shift == '夜':
                continue
            if high_shift in FULL_OFF_SHIFTS and low_shift not in FULL_OFF_SHIFTS + HALF_OFF_SHIFTS:
                df.at[high, col], df.at[low, col] = low_shift, '休'
                totals[high] -= 1
                totals[low] += 1
                moved = True
                break
        if not moved:
            break


def ensure_min_rest_days_balanced():
    """各看護師にTARGET_REST_SCOREを満たすよう、出勤人数を考慮しながら「休」または半休を割り当てる"""

    # 1. 各看護師の現在の休日日数
    rest_totals = {}
    for n in nurse_names:
        total = 0
        for d in date_cols:
            shift = df.at[n, d]
            if shift in FULL_OFF_SHIFTS:
                total += 1
            elif shift in HALF_OFF_SHIFTS:
                total += 0.5
        rest_totals[n] = total

    # 2. 各日付の出勤者数を数える（休みでない人数）
    work_count_per_day = {}
    for d in date_cols:
        count = 0
        for n in nurse_names:
            shift = df.at[n, d]
            if shift not in FULL_OFF_SHIFTS + HALF_OFF_SHIFTS:
                count += 1
        work_count_per_day[d] = count

    # 3. 出勤余裕がある日から順に並べる
    sorted_days = sorted(date_cols, key=lambda d: work_count_per_day[d], reverse=True)

    # 4. 看護師ごとに、必要休み数を満たすよう割り当て（半休含む）
    for n in nurse_names:
        while rest_totals[n] < TARGET_REST_SCORE:
            inserted = False
            for d in sorted_days:
                if fixed_mask.at[n, d]:
                    continue
                shift = df.at[n, d]
                if shift in FULL_OFF_SHIFTS + HALF_OFF_SHIFTS:
                    continue
                if shift != '' and not pd.isna(shift):
                    continue
                if shift == '×' and date_cols.index(d) > 0 and df.at[n, date_cols[date_cols.index(d)-1]] == '夜':
                    continue
                if work_count_per_day[d] > 7:
                    # 残りスコアに応じて「休」または半休を割り当て
                    remaining = TARGET_REST_SCORE - rest_totals[n]
                    if remaining >= 1:
                        df.at[n, d] = '休'
                        rest_totals[n] += 1
                        work_count_per_day[d] -= 1
                        inserted = True
                        break
                    elif remaining >= 0.5:
                        df.at[n, d] = '休/'  # 半休として割り当て
                        rest_totals[n] += 0.5
                        work_count_per_day[d] -= 1
                        inserted = True
                        break
            if not inserted:
                break


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
    if weekday in ['Monday', 'Tuesday', 'Wednesday', 'Friday'] and not is_japanese_holiday(dates[d]):
        assigned_nurses = set()
        available_nurses = [n for n in nurse_names if df.at[n, col] not in busy_shifts and not fixed_mask.at[n, col]]

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
                other_candidates = [
                    n
                    for n in available_nurses
                    if n not in assigned_nurses
                    and n != '御書'
                    and not fixed_mask.at[n, col]
                ]  # 御書は外来に入らない
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
                other_candidates = [
                    n
                    for n in available_nurses
                    if n not in assigned_nurses
                    and n != '御書'
                    and not fixed_mask.at[n, col]
                ]  # 御書は外来に入らない
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
        remain_nurses = [
            n
            for n in nurse_names
            if (df.at[n, col] == '' or pd.isna(df.at[n, col]))
            and n in available_nurses
            and not fixed_mask.at[n, col]
        ]
        assign_rest_shifts(remain_nurses, col)

    # 3. 木曜・日曜（B日程）の処理
    elif weekday in ['Thursday', 'Sunday'] or is_japanese_holiday(dates[d]):
        forbidden_shifts = ['休', '休/', '/休', '×', '夜', '/訪']
        candidates = [
            n
            for n in nurse_names
            if df.at[n, col] not in forbidden_shifts and not fixed_mask.at[n, col]
        ]

        # 「早日」「残日」を1人ずつ均等割当
        early_counts = {n: (df == '早日').loc[n].sum() for n in candidates}
        min_early = min(early_counts.values()) if early_counts else 0
        candidates_early = [n for n in candidates if early_counts[n] == min_early]

        if candidates_early:
            assign_early = sorted(candidates_early)[0]
            df.at[assign_early, col] = '早日'

        late_counts = {n: (df == '残日').loc[n].sum() for n in candidates if n != assign_early}
        min_late = min(late_counts.values()) if late_counts else 0
        candidates_late = [n for n in late_counts if late_counts[n] == min_late]
        if candidates_late:
            assign_late = sorted(candidates_late)[0]
            df.at[assign_late, col] = '残日'

        # 残りの人は休みスコアに基づき割当
        rest_candidates = [
            n
            for n in candidates
            if df.at[n, col] not in ['早日', '残日'] and not fixed_mask.at[n, col]
        ]
        assign_rest_shifts(rest_candidates, col)

        # 他の看護師で空白の人には休み割当優先度付きで割当
        remain_nurses = [
            n
            for n in nurse_names
            if (df.at[n, col] == '' or pd.isna(df.at[n, col]))
            and df.at[n, col] not in busy_shifts
            and not fixed_mask.at[n, col]
        ]
        assign_rest_shifts(remain_nurses, col)

    # 4. 土曜（C日程）の処理
    elif weekday == 'Saturday':
        assigned_nurses = set()
        busy_shifts = ['休', '休/', '/休', '×', '夜']

        # 「久保」が出勤の場合、「2/」優先
        if '久保' in nurse_names and df.at['久保', col] not in busy_shifts:
            df.at['久保', col] = '2/'
            shift_counts_saturday['久保']['2/'] += 1
            assigned_nurses.add('久保')
            gai_shift = random.sample(['1/', '3/', '4/'], k=3)
            for s, nurse in zip(gai_shift, 土曜担当): # 「小嶋」「久保（千）」「田浦」から優先に外来「1/」「3/」「4/」に入る
                if nurse in nurse_names and df.at[nurse, col] not in busy_shifts and not fixed_mask.at[nurse, col]:
                    df.at[nurse, col] = s
                    shift_counts_saturday[nurse][s] += 1
                    assigned_nurses.add(nurse)
                else:
                    candidates = [
                        n
                        for n in nurse_names
                        if n not in assigned_nurses
                        and n not in 土曜担当
                        and df.at[n, col] not in busy_shifts
                        and n != '御書'
                        and not fixed_mask.at[n, col]
                    ]  # 御書は外来に入らない
                    if candidates:
                        min_count = min(shift_counts_saturday[n][s] for n in candidates)
                        assign = min([n for n in candidates if shift_counts_saturday[n][s] == min_count])
                        df.at[assign, col] = s
                        shift_counts_saturday[assign][s] += 1
                        assigned_nurses.add(assign)
            
        # 「久保」が休みの場合
        else: 
            # 外来は土曜担当から優先
            gai_shift = random.sample(['1/', '2/', '3/', '4/'], k=4)
            for s, nurse in zip(gai_shift, 土曜担当):
                # 「小嶋」「久保（千）」「田浦」から優先に外来「1/」「2/」「3/」「4/」に入る
                if nurse in nurse_names and df.at[nurse, col] not in busy_shifts and not fixed_mask.at[nurse, col]:
                    df.at[nurse, col] = s
                    shift_counts_saturday[nurse][s] += 1
                    assigned_nurses.add(nurse)
                else:
                    candidates = [
                        n
                        for n in nurse_names
                        if n not in assigned_nurses
                        and n not in 土曜担当
                        and df.at[n, col] not in busy_shifts
                        and n != '御書'
                        and not fixed_mask.at[n, col]
                    ]  # 御書は外来に入らない
                    if candidates:
                        min_count = min(shift_counts_saturday[n][s] for n in candidates)
                        assign = min([n for n in candidates if shift_counts_saturday[n][s] == min_count])
                        df.at[assign, col] = s
                        shift_counts_saturday[assign][s] += 1
                        assigned_nurses.add(assign)

            # 残り外来を他から均等割り
            gai_members = [n for n in 土曜担当 if n in assigned_nurses]
            remain = 4 - len(gai_members)
            if remain > 0:
                other_candidates = [
                    n
                    for n in nurse_names
                    if n not in assigned_nurses
                    and n != '御書'
                    and not fixed_mask.at[n, col]
                ]  # 御書は外来に入らない
                for s in gai_shift[len(gai_members):]:
                    if other_candidates:
                        min_count = min(shift_counts_saturday[n][s] for n in other_candidates)
                        assign = min([n for n in other_candidates if shift_counts_saturday[n][s] == min_count])
                        df.at[assign, col] = s
                        shift_counts_saturday[assign][s] += 1
                        assigned_nurses.add(assign)
                        other_candidates.remove(assign)

        # 病棟シフト（早、残、〇）
        病棟シフト = ['早', '残', '〇']
        candidates = [
            n
            for n in nurse_names
            if n not in assigned_nurses
            and df.at[n, col] not in busy_shifts
            and not fixed_mask.at[n, col]
        ]
        for s in 病棟シフト:
            if candidates:
                count_dict = {n: (df.loc[n] == s).sum() for n in candidates}
                min_count = min(count_dict[n] for n in candidates)
                assign = min([n for n in candidates if count_dict[n] == min_count])
                df.at[assign, col] = s
                assigned_nurses.add(assign)
                candidates.remove(assign)

        # 休み割り振り（休み不足が多い人から優先）
        remain_nurses = [
            n
            for n in nurse_names
            if (df.at[n, col] == '' or pd.isna(df.at[n, col]))
            and df.at[n, col] not in busy_shifts
            and not fixed_mask.at[n, col]
        ]
        assign_rest_shifts(remain_nurses, col)

    # その他の日は特に処理なし
    else:
        # 休み割当が必要な場合は割当
        remain_nurses = [
            n
            for n in nurse_names
            if (df.at[n, col] == '' or pd.isna(df.at[n, col]))
            and df.at[n, col] not in busy_shifts
            and not fixed_mask.at[n, col]
        ]
        assign_rest_shifts(remain_nurses, col)

# 最終的に空白やNaNのシフトは「休」に置換（休み割当不可の人も含む）
for d, col in enumerate(date_cols):
    for n in nurse_names:
        if df.at[n, col] == '' or pd.isna(df.at[n, col]):
            df.at[n, col] = '休'

balance_rest_days()


def prevent_seven_day_streaks():
    """Ensure nobody works 7 days in a row by inserting rest days."""
    off_codes = FULL_OFF_SHIFTS + HALF_OFF_SHIFTS
    for n in nurse_names:
        streak = 0
        for i, col in enumerate(date_cols):
            shift = df.at[n, col]
            if shift in off_codes:
                streak = 0
                continue

            streak += 1
            if streak >= 7:
                # Try to change one of the last 7 days to a rest day
                changed = False
                for j in range(i, i - 7, -1):
                    col_j = date_cols[j]
                    shift_j = df.at[n, col_j]
                    if fixed_mask.at[n, col_j]:
                        continue
                    # Do not modify night shift or the x immediately after it
                    if shift_j == "夜":
                        continue
                    if (
                        shift_j == "×"
                        and j > 0
                        and df.at[n, date_cols[j - 1]] == "夜"
                    ):
                        continue
                    df.at[n, col_j] = "休"
                    changed = True
                    streak = 0
                    break

                if not changed and not fixed_mask.at[n, col] and shift != "夜":
                    df.at[n, col] = "休"
                    streak = 0


def prevent_four_day_rest_streaks():
    """
    休みが4日連続した場合、固定されていない休みを他の勤務日と入れ替えて休みを分散させる。
    入れ替え候補が見つからなければ、何も変更せずそのままにする。
    """
    off_codes = FULL_OFF_SHIFTS + HALF_OFF_SHIFTS
    for n in nurse_names:
        streak = 0
        for i, col in enumerate(date_cols):
            shift = df.at[n, col]
            if shift in off_codes:
                streak += 1
                if streak >= 4:
                    swapped = False
                    # 直近4日の休みのうち、固定されていない休みを探す
                    for j in range(i, i - 4, -1):
                        col_j = date_cols[j]
                        shift_j = df.at[n, col_j]
                        if fixed_mask.at[n, col_j] or shift_j not in off_codes:
                            continue
                        # 連続休み期間以外から勤務日を探して入れ替える
                        for k, col_k in enumerate(date_cols):
                            if i - 3 <= k <= i:
                                continue  # 連続休みの範囲は除外
                            shift_k = df.at[n, col_k]
                            if fixed_mask.at[n, col_k]:
                                continue
                            if shift_k in off_codes:
                                continue
                            if shift_k == '夜':
                                continue
                            if shift_k == '×' and k > 0 and df.at[n, date_cols[k-1]] == '夜':
                                continue
                            # 入れ替え実行
                            df.at[n, col_j], df.at[n, col_k] = df.at[n, col_k], df.at[n, col_j]
                            swapped = True
                            streak = 0
                            break
                        if swapped:
                            break
                    # 入れ替え候補が見つからない場合は、何も変更せずそのままにする
                    if not swapped:
                        streak = 0  # 連続カウントだけリセットして次へ
            else:
                # 勤務日なら連続休みカウントをリセット
                streak = 0


# 7日連続勤務を防止
prevent_seven_day_streaks()
# 4日連続休みを防止
prevent_four_day_rest_streaks()
# 休み数を均等化
ensure_min_rest_days_balanced()


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
        if shift in FULL_OFF_SHIFTS:
            total_rest += 1
        elif shift in HALF_OFF_SHIFTS:
            total_rest += 0.5
    rest_col.append(total_rest)
df_with_rest_col['休み合計'] = rest_col
df_with_rest_col.to_csv("output/shift_summary.csv", encoding="utf-8-sig")
print("✅ 休み合計列付きのシフトCSVを shift_summary.csv に保存しました。")