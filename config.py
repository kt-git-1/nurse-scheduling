from datetime import datetime, timedelta
import calendar
import pandas as pd

# 初期設定
REQ_SHIFT_PATH = 'req_shift_8.csv'
TEMPLATE_PATH = 'shift_template.xlsx'
TEMP_SHIFT_PATH = 'temp_shift.csv'

YEAR = 2025
MONTH = 8
DAYS_IN_MONTH = 31
SHIFT_TYPES = [
    '休', '夜', '早', '残', '〇', '1', '2', '3', '4', '×',
    '/訪', 'CT', '早日', '残日', '1/', '2/', '3/', '4/', '/休', '休/',
    'F', '2・CT'
]
HOLIDAY_MAP = {
    '①': ['休'],
    '②': ['休', '×'],
    '③': ['休/'],
    '④': ['/休'],
    '⑤': ['/休', '×'],
}

INPUT_CSV = pd.read_csv(REQ_SHIFT_PATH)
NURSES = [n for n in INPUT_CSV['日付'].dropna().tolist() if n != '曜日']
HOLIDAY_NO_WORKERS = ['久保', '小嶋', '久保（千）', '田浦']
HOLIDAY_WORKERS = [n for n in NURSES if n not in HOLIDAY_NO_WORKERS]
FULL_OFF_SHIFTS = ['休', '×']
HALF_OFF_SHIFTS = ['休/', '/休', '1/', '2/', '3/', '4/']
TARGET_REST_SCORE = 13  # 各看護師が取得したい休みの目標

start_date = datetime(YEAR, MONTH - 1, 21)
dates = [start_date + timedelta(days=i) for i in range(DAYS_IN_MONTH)]
weekday_list = [calendar.day_name[d.weekday()] for d in dates]