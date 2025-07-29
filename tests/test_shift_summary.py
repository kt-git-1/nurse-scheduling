import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import sys

SHIFT_SUMMARY_PATH = Path(__file__).resolve().parents[1] / "output" / "shift_summary.csv"

OFF_CODES_FULL = ["休"]
OFF_CODES_HALF = ["休/", "/休", "1/", "2/", "3/", "4/", "/訪"]
OFF_CODES = OFF_CODES_FULL + OFF_CODES_HALF

WEEKDAYS = [(datetime(2025, 8, 1) - timedelta(days=11) + timedelta(days=i)).strftime('%A') for i in range(31)]
# 2025-07-21 is Monday and corresponds to day_0


def generate_shift_summary():
    """Run main.py to produce shift_summary.csv if it does not exist."""
    if not SHIFT_SUMMARY_PATH.exists():
        subprocess.run([sys.executable, Path(__file__).resolve().parents[1] / "main.py"], check=True)


def load_summary():
    generate_shift_summary()
    return pd.read_csv(SHIFT_SUMMARY_PATH)




def test_rest_days_minimum():
    df = load_summary()
    assert (df['休み合計'] >= 13).all(), "各看護師の休み合計は13以上である必要があります"


def test_shift_assignment_rules():
    df = load_summary()
    nurses = df['nurse'].tolist()
    for idx, day in enumerate(WEEKDAYS):
        col = f'day_{idx}'
        shifts = df[col].tolist()
        working = [s for s in shifts if s not in OFF_CODES + ['×']]
        if day in ['Monday', 'Tuesday', 'Wednesday', 'Friday']:
            if len(working) >= 8:
                required = ['1', '2', '3', '4', 'CT', '早', '残', '〇']
                for r in required:
                    assert shifts.count(r) == 1, f"{day} {col} では {r} が1人必要"
            elif len(working) == 7:
                required = ['1', '3', '4', '2・CT', '早', '残', '〇']
                for r in required:
                    assert shifts.count(r) == 1, f"{day} {col} では {r} が1人必要"
        elif day in ['Thursday', 'Sunday']:
            assert shifts.count('早日') == 1, f"{day} {col} は早日が1人必要"
            assert shifts.count('残日') == 1, f"{day} {col} は残日が1人必要"
            for s in shifts:
                if s not in ['早日', '残日']:
                    assert s in OFF_CODES, f"{day} {col} は早日・残日以外休みである必要があります"
        elif day == 'Saturday':
            kubo_shift = df.loc[df['nurse'] == '久保', col].iloc[0]
            if kubo_shift not in OFF_CODES:
                assert kubo_shift == '2/', f"{day} {col} で久保は2/担当のはず"
            required_outs = ['1/', '2/', '3/', '4/']
            for r in required_outs:
                assert r in shifts, f"{day} {col} では {r} が必要"


def test_individual_rules():
    df = load_summary()
    night_forbidden = ['板川', '三好']
    for nurse in night_forbidden:
        row = df[df['nurse'] == nurse]
        assert not row.filter(like='day_').isin(['夜']).any().any(), f"{nurse} は夜勤なし"

    gasho_row = df[df['nurse'] == '御書']
    forbidden = ['夜', '1', '2', '3', '4', 'CT', '1/', '2/', '3/', '4/', '2・CT', '残日', '早日']
    assert not gasho_row.filter(like='day_').isin(forbidden).any().any(), "御書には夜勤・外来・残日・早日が割り当てられていない"
