import os
import requests
import pytz
from datetime import datetime, timedelta
from icalendar import Calendar, Event

# --- [설정] ---
# GitHub Secrets에서 설정한 값을 그대로 가져옵니다.
# (Secrets에 해당 이름이 없으면 None을 반환하며, NX/NY는 정수로 변환합니다)
NX = int(os.environ.get('KMA_NX'))
NY = int(os.environ.get('KMA_NY'))
LOCATION_NAME = os.environ.get('LOCATION_NAME')
REG_ID_TEMP = os.environ.get('REG_ID_TEMP')
REG_ID_LAND = os.environ.get('REG_ID_LAND')
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
                # 오늘 기준 4일차 이후의 이벤트를 수집하여 백업
                target_date = (now + timedelta(days=4)).date()
                for event in old_cal.walk('VEVENT'):
                    start_dt = event.get('dtstart').dt
                    if isinstance(start_dt, datetime): start_dt = start_dt.date()
                    if start_dt >= target_date:
                        old_mid_events.append(event)
        except:
            has_old_file = False

    # --- [2. 중기 데이터 수집 조건 판단] ---
    # 기상청 중기 발표(06시, 18시) 직전/직후 회차인 05시, 17시(KST)에 업데이트
    is_mid_update_time = now.hour in [5, 17]
    # 파일이 없거나 백업이 비었으면 무조건 새로 가져옴
    should_fetch_mid = (not has_old_file) or (not old_mid_events) or is_mid_update_time

    # --- [3. 단기 예보 수집] (항상 실행) ---
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
        print(f"📢 중기 예보 업데이트를 수행합니다. (기준시간: {now.hour}시)")
        # 06시/18시 데이터 분기 (기상청 규칙 준수)
        tm_fc = now.strftime('%Y%m%d') + ("0600" if now.hour < 12 else "1800")
        
        url_mid_temp = f"https://apihub.kma.go.kr/api/typ02/openApi/MidFcstInfoService/getMidTa?dataType=JSON&regId={REG_ID_TEMP}&tmFc={tm_fc}&authKey={API_KEY}"
        url_mid_land = f"https://apihub.kma.go.kr/api/typ02/openApi/MidFcstInfoService/getMidLandFcst?dataType=JSON&regId={REG_ID_LAND}&tmFc={tm_fc}&authKey={API_KEY}"
        
        t_res = fetch_api(url_mid_temp)
        l_res = fetch_api(url_mid_land)
        
        if t_res and l_res:
            try:
                t_item = t_res['response']['body']['items']['item'][0]
                l_item = l_res['response']['body']['items']['item'][0]
                # 3일~10일차 데이터 매핑
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
    else:
        print("📦 현재는 중기 업데이트 시간이 아니므로 기존 데이터를 유지합니다.")

    # --- [5. 최종 ics 조립] ---
    # 5-1. 단기 예보 (0~3일차)
    for i in range(4):
        target_dt = now + timedelta(days=i)
        d_str = target_dt.strftime('%Y%m%d')
        if d_str in forecast_map:
            event = Event()
            d_data = forecast_map[d_str]
            times = sorted(d_data.keys())
            tmps = [float(d_data[t]['TMP']) for t in times if 'TMP' in d_data[t]]
            if tmps:
                t_min, t_max = int(min(tmps)), int(max(tmps))
                mid_t = "1200" if "1200" in d_data else times[len(times)//2]
                rep_em, _ = get_weather_info(d_data[mid_t].get('SKY'), d_data[mid_t].get('PTY'))
                event.add('summary', f"{rep_em} {t_min}°C / {t_max}°C")
                desc = [f"📍 {LOCATION_NAME}\n"]
                for t in times:
                    it = d_data[t]
                    em, status = get_weather_info(it.get('SKY'), it.get('PTY'))
                    pop_str = f"☔{it.get('POP')}% " if it.get('PTY') != '0' else ""
                    line = f"[{int(t[:2])}시] {em} {it.get('TMP')}°C {status} ({pop_str}💧{it.get('REH')}% 💨{it.get('WSD')}m/s)"
                    desc.append(line)
                desc.append(f"\n최종 갱신: {now.strftime('%Y-%m-%d %H:%M:%S')} KST")
                event.add('description', "\n".join(desc))
                event.add('dtstart', target_dt.date()); event.add('dtend', (target_dt + timedelta(days=1)).date())
                event.add('uid', f"{d_str}@kma_weather")
                cal.add_component(event)

    # 5-2. 중기 예보 (4~10일차)
    if should_fetch_mid and mid_map:
        for d_str, m in mid_map.items():
            # 단기 예보와 겹치는 날짜는 스킵
            if d_str in [ (now + timedelta(days=x)).strftime('%Y%m%d') for x in range(4) ]: continue
            
            event = Event()
            target_dt = datetime.strptime(d_str, '%Y%m%d')
            rep_wf = m.get('wf_pm') or m.get('wf')
            event.add('summary', f"{get_mid_emoji(rep_wf)} {m['min']}°C / {m['max']}°C")
            desc = [f"📍 {LOCATION_NAME}\n"]
            if 'wf_am' in m:
                desc.append(f"[오전] {get_mid_emoji(m['wf_am'])} {m['wf_am']} (☔{m['rn_am']}%)")
                desc.append(f"[오후] {get_mid_emoji(m['wf_pm'])} {m['wf_pm']} (☔{m['rn_pm']}%)")
            else:
                desc.append(f"[종일] {get_mid_emoji(m['wf'])} {m['wf']} (☔{m['rn']}%)")
            event.add('description', "\n".join(desc))
            event.add('dtstart', target_dt.date()); event.add('dtend', (target_dt + timedelta(days=1)).date())
            event.add('uid', f"{d_str}@kma_weather")
            cal.add_component(event)
    else:
        # 새로 안 받았으면 백업해둔 데이터 그대로 추가
        for event in old_mid_events:
            cal.add_component(event)

    with open('weather.ics', 'wb') as f:
        f.write(cal.to_ical())
    print("✅ weather.ics 갱신 완료")

if __name__ == "__main__":
    main()
