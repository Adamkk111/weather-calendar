import os
import requests
import pytz
from datetime import datetime, timedelta
from icalendar import Calendar, Event

# --- [설정] ---
# GitHub Secrets에서 값을 가져오며, 없을 경우를 대비해 기본값을 지정합니다.
NX = int(os.environ.get('KMA_NX', 60))
NY = int(os.environ.get('KMA_NY', 127))
LOCATION_NAME = os.environ.get('LOCATION_NAME', '우리집')
REG_ID_TEMP = os.environ.get('REG_ID_TEMP', '11B10101')
REG_ID_LAND = os.environ.get('REG_ID_LAND', '11B00000')
API_KEY = os.environ.get('KMA_API_KEY')

def get_weather_info(sky, pty):
    sky, pty = str(sky), str(pty)
    if pty == '0':
        if sky == '1': return "☀️", "맑음"
        if sky == '3': return "⛅", "구름많음"
        if sky == '4': return "☁️", "흐림"
    else:
        if pty in ['1', '4']: return "🌧️", "비/소나기"
        if pty == '2': return "🌨️", "비/눈"
        if pty == '3': return "❄️", "눈"
    return "🌡️", "정보없음"

def get_mid_emoji(wf):
    if not wf: return "🌡️"  # 데이터가 None인 경우 에러 방지
    if '비' in wf or '소나기' in wf: return "🌧️"
    if '눈' in wf: return "🌨️"
    if '구름많음' in wf: return "⛅"
    if '흐림' in wf: return "☁️"
    return "☀️"

def fetch_api(url):
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200: return res.json()
    except: return None
    return None

def main():
    seoul_tz = pytz.timezone('Asia/Seoul')
    now = datetime.now(seoul_tz)
    cal = Calendar()
    cal.add('X-WR-CALNAME', '기상청 날씨')
    cal.add('X-WR-TIMEZONE', 'Asia/Seoul')

    # --- [1. 기존 데이터 확인 및 백업] ---
    old_mid_events = []
    has_old_file = os.path.exists('weather.ics')
    
    if has_old_file:
        try:
            with open('weather.ics', 'rb') as f:
                old_cal = Calendar.from_ical(f.read())
                target_date = (now + timedelta(days=4)).date()
                for event in old_cal.walk('VEVENT'):
                    start_dt = event.get('dtstart').dt
                    if isinstance(start_dt, datetime): start_dt = start_dt.date()
                    if start_dt >= target_date:
                        old_mid_events.append(event)
        except:
            has_old_file = False

    # --- [2. 중기 데이터 수집 조건] ---
    is_mid_update_time = now.hour in [5, 6, 17, 18]
    should_fetch_mid = (not has_old_file) or (not old_mid_events) or is_mid_update_time

    # --- [3. 단기 예보 수집] ---
    base_date = now.strftime('%Y%m%d')
    base_h = max([h for h in [2, 5, 8, 11, 14, 17, 20, 23] if h <= now.hour], default=2)
    base_time = f"{base_h:02d}00"
    url_short = f"https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst?dataType=JSON&base_date={base_date}&base_time={base_time}&nx={NX}&ny={NY}&numOfRows=1000&authKey={API_KEY}"
    
    forecast_map = {}
    short_res = fetch_api(url_short)
    if short_res and 'response' in short_res and 'body' in short_res['response']:
        items = short_res['response']['body']['items']['item']
        for it in items:
            d, t, cat, val = it['fcstDate'], it['fcstTime'], it['category'], it['fcstValue']
            if d not in forecast_map: forecast_map[d] = {}
            if t not in forecast_map[d]: forecast_map[d][t] = {}
            forecast_map[d][t][cat] = val

    # --- [4. 중기 예보 수집] ---
    mid_map = {}
    if should_fetch_mid:
        tm_fc = now.strftime('%Y%m%d') + ("0600" if now.hour < 12 else "1800")
        url_mid_temp = f"https://apihub.kma.go.kr/api/typ02/openApi/MidFcstInfoService/getMidTa?dataType=JSON&regId={REG_ID_TEMP}&tmFc={tm_fc}&authKey={API_KEY}"
        url_mid_land = f"https://apihub.kma.go.kr/api/typ02/openApi/MidFcstInfoService/getMidLandFcst?dataType=JSON&regId={REG_ID_LAND}&tmFc={tm_fc}&authKey={API_KEY}"
        
        t_res = fetch_api(url_mid_temp)
        l_res = fetch_api(url_mid_land)
        
        if t_res and l_res:
            try:
                t_item = t_res['response']['body']['items']['item'][0]
                l_item = l_res['response']['body']['items']['item'][0]
                for i in range(3, 11):
                    d_str = (now + timedelta(days=i)).strftime('%Y%m%d')
                    if i <= 7:
                        mid_map[d_str] = {
                            'min': t_item.get(f'taMin{i}'), 'max': t_item.get(f'taMax{i}'),
                            'wf_am': l_item.get(f'wf{i}Am'), 'wf_pm': l_item.get(f'wf{i}Pm'),
                            'rn_am': l_item.get(f'rnSt{i}Am'), 'rn_pm': l_item.get(f'rnSt{i}Pm')
                        }
                    else:
                        mid_map[d_str] = {
                            'min': t_item.get(f'taMin{i}'), 'max': t_item.get(f'taMax{i}'),
                            'wf': l_item.get(f'wf{i}'), 'rn': l_item.get(f'rnSt{i}')
                        }
            except: pass

    # --- [5. 최종 조립] ---
    for i in range(4):
        target_dt = now + timedelta(days=i)
        d_str = target_dt.strftime('%Y%m%d')
        if d_str in forecast_map:
            event = Event()
            d_data = forecast_map[d_str]
            tmps = [float(d_data[t]['TMP']) for t in d_data if 'TMP' in d_data[t]]
            if tmps:
                t_min, t_max = int(min(tmps)), int(max(tmps))
                event.add('summary', f"{get_weather_info(d_data.get('1200', {}).get('SKY','1'), d_data.get('1200', {}).get('PTY','0'))[0]} {t_min}°C/{t_max}°C")
                event.add('dtstart', target_dt.date()); event.add('dtend', (target_dt + timedelta(days=1)).date())
                event.add('uid', f"{d_str}@short")
                cal.add_component(event)

    if mid_map:
        for d_str, m in mid_map.items():
            if d_str in [ (now + timedelta(days=x)).strftime('%Y%m%d') for x in range(4) ]: continue
            event = Event()
            wf = m.get('wf_pm') or m.get('wf') or ""
            event.add('summary', f"{get_mid_emoji(wf)} {m.get('min','-')}°C/{m.get('max','-')}°C")
            event.add('dtstart', datetime.strptime(d_str, '%Y%m%d').date())
            event.add('dtend', (datetime.strptime(d_str, '%Y%m%d') + timedelta(days=1)).date())
            event.add('uid', f"{d_str}@mid")
            cal.add_component(event)
    else:
        for ev in old_mid_events: cal.add_component(ev)

    with open('weather.ics', 'wb') as f: f.write(cal.to_ical())

if __name__ == "__main__": main()
